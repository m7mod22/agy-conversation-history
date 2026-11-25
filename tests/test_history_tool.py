#!/usr/bin/env python3
"""Unit tests for conversation-history plugin CLI and lifecycle hooks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "skills" / "conversation-history" / "scripts"
HOOKS_DIR = PLUGIN_ROOT / "hooks"

for p in (str(SCRIPTS_DIR), str(HOOKS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import history_tool  # noqa: E402
import pre_invocation  # noqa: E402
import stop_check  # noqa: E402


class TestHistoryTool(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_locate_new_vs_existing_and_marker_uniqueness(self) -> None:
        proj = self.tmp_dir / "empty_proj"
        proj.mkdir()
        (proj / ".git").mkdir()
        (proj / "README.md").write_text("# New\n", encoding="utf-8")

        res_new = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(res_new["status"], "new_project")

        # Unrelated conversation_history.md without unique marker must NOT match
        (proj / "conversation_history.md").write_text("# Unrelated notes\n", encoding="utf-8")
        res_existing = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(res_existing["status"], "existing_project")

        # Opt-out works cleanly
        history_tool.main(["opt-out", "--project", str(proj)])
        res_opt = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(res_opt["status"], "opted_out")

        # Empty workspace list returns no_workspace
        self.assertEqual(history_tool.locate_project([], check_drift=False)["status"], "no_workspace")

    def test_default_workspace_keyword_filename(self) -> None:
        proj = self.tmp_dir / "Collarms Project"
        proj.mkdir()
        self.assertEqual(history_tool.default_history_filename(proj), "Collarms_conversation_history.md")
        loc = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(loc["suggested_filename"], "Collarms_conversation_history.md")

        # Calling init without --path uses <Workspace>_conversation_history.md
        rc = history_tool.main(["init", "--project", str(proj), "--install-setup"])
        self.assertEqual(rc, 0)
        self.assertTrue((proj / "Collarms_conversation_history.md").is_file())
        loc2 = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(loc2["status"], "found")
        self.assertEqual(loc2["history_rel_path"], "Collarms_conversation_history.md")

        # Generic-only folder name falls back cleanly
        generic = self.tmp_dir / "project"
        generic.mkdir()
        self.assertEqual(history_tool.default_history_filename(generic), "conversation_history.md")

    def test_init_install_portable_and_custom_location(self) -> None:
        proj = self.tmp_dir / "my_app"
        proj.mkdir()

        rc = history_tool.main(
            [
                "init",
                "--project",
                str(proj),
                "--path",
                "docs/conversation_history.md",
                "--project-name",
                "MyApp",
                "--install-setup",
            ]
        )
        self.assertEqual(rc, 0)

        hist_file = proj / "docs" / "conversation_history.md"
        self.assertTrue(hist_file.is_file())
        self.assertIn(history_tool.UNIQUE_MARKER, hist_file.read_text(encoding="utf-8"))

        portable_dir = proj / ".agents" / "plugins" / "conversation-history"
        self.assertTrue((portable_dir / "plugin.json").is_file())
        self.assertTrue((portable_dir / "rules" / "AGENTS.md").is_file())
        self.assertTrue((portable_dir / "skills" / "conversation-history" / "SKILL.md").is_file())
        self.assertTrue((portable_dir / "skills" / "conversation-history" / "scripts" / "history_tool.py").is_file())
        self.assertFalse((portable_dir / "hooks.json").exists())

        loc = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(loc["status"], "found")
        self.assertEqual(loc["history_rel_path"], "docs/conversation_history.md")
        self.assertTrue(loc["has_portable_setup"])

        # Remove config pointer and verify marker scan still discovers nested file
        (proj / ".agents" / "conversation-history.json").unlink()
        loc2 = history_tool.locate_project([proj], check_drift=False)
        self.assertEqual(loc2["status"], "found")
        self.assertEqual(loc2["history_rel_path"], "docs/conversation_history.md")

    def test_path_traversal_rejected(self) -> None:
        proj = self.tmp_dir / "safe_proj"
        proj.mkdir()
        rc = history_tool.main(["init", "--project", str(proj), "--path", "../escape.md"])
        self.assertEqual(rc, 1)

    def test_append_turn_multi_priority_supersede_and_sanitization(self) -> None:
        proj = self.tmp_dir / "turn_proj"
        proj.mkdir()
        history_tool.main(["init", "--project", str(proj), "--path", "conversation_history.md"])
        hist_file = proj / "conversation_history.md"

        long_user_code = "\n".join(f"x_{i} = {i}" for i in range(20))
        user_in_1 = (
            "Always use WebSockets for telemetry. Use token sk-1234567890abcdefghij.\n"
            f"```python\n{long_user_code}\n```"
        )
        ai_out_1 = (
            "Designed WebSocket telemetry publisher in `app/ws.py` (`TelemetrySocket`) "
            "decoupling GUI updates from hardware polling."
        )
        pts_1 = json.dumps(
            [
                {"priority": "P1", "text": "Always use WebSockets for live telemetry."},
                {"priority": "P2", "text": "**Architecture:** Telemetry runs in `app/ws.py` decoupled from GUI."},
                {"priority": "P3", "text": "**Current State:** Initial WebSocket design agreed."},
                {"priority": "P4", "text": "Discussed brief alternative comparison."},
            ]
        )
        self.assertEqual(
            history_tool.main(
                [
                    "append-turn",
                    "--file",
                    str(hist_file),
                    "--input",
                    user_in_1,
                    "--output",
                    ai_out_1,
                    "--points-json",
                    pts_1,
                ]
            ),
            0,
        )

        # Turn 2 supersedes Turn 1 P1 and P3 while allowing a small mermaid diagram
        pts_2 = json.dumps(
            [
                {"priority": "P1", "text": "[supersedes: Turn 1] Always use gRPC streams for telemetry."},
                {"priority": "P2", "text": "**Mistake to Avoid:** WebSockets choked on binary frames."},
                {"priority": "P3", "text": "[supersedes: Turn 1] **Current State:** Switched to gRPC in `app/grpc_srv.py`."},
            ]
        )
        ai_out_2 = (
            "Migrated telemetry transport from WebSockets to gRPC streaming in `app/grpc_srv.py`.\n\n"
            "```mermaid\nflowchart LR\n  Sensor --> gRPC --> UI\n```"
        )
        self.assertEqual(
            history_tool.main(
                [
                    "append-turn",
                    "--file",
                    str(hist_file),
                    "--input",
                    "Switch to gRPC instead.",
                    "--output",
                    ai_out_2,
                    "--points-json",
                    pts_2,
                ]
            ),
            0,
        )

        text = hist_file.read_text(encoding="utf-8")
        self.assertNotIn("sk-1234567890abcdefghij", text)
        self.assertIn("[REDACTED_API_KEY]", text)
        self.assertIn("User shared python snippet (20 lines)", text)

        # Priority Index should contain Turn 2 P1/P3 and NOT retired Turn 1 P1/P3, nor P4
        index_section = text.split("## Turn-by-Turn Log")[0]
        self.assertNotIn("`[Turn 1]` Always use WebSockets", index_section)
        self.assertIn("`[Turn 2]` [supersedes: Turn 1] Always use gRPC", index_section)
        self.assertIn("`[Turn 1]` **Architecture:**", index_section)
        self.assertNotIn("Discussed brief alternative", index_section)

        # Turn-by-Turn Log must still retain Turn 1 completely
        log_section = text.split("## Turn-by-Turn Log")[1]
        self.assertIn("### Turn 1 —", log_section)
        self.assertIn("Discussed brief alternative", log_section)

        # Raw code in AI Output must be rejected
        bad_rc = history_tool.main(
            [
                "append-turn",
                "--file",
                str(hist_file),
                "--input",
                "Show me",
                "--output",
                "Here is code:\n```python\ndef f():\n    return 1\n```",
                "--points-json",
                '[{"priority":"P4","text":"Sample"}]',
            ]
        )
        self.assertEqual(bad_rc, 1)

        # Validate passes cleanly
        self.assertEqual(history_tool.main(["validate", "--file", str(hist_file)]), 0)

    def test_backfill_scan_with_truncated_transcript_and_git_drift(self) -> None:
        proj = self.tmp_dir / "git_proj"
        proj.mkdir()
        subprocess.run(["git", "init", str(proj)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(proj), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(proj), "config", "user.name", "Tester"], check=True)

        history_tool.main(["init", "--project", str(proj), "--path", "conversation_history.md"])
        subprocess.run(["git", "-C", str(proj), "add", "."], check=True)
        subprocess.run(["git", "-C", str(proj), "commit", "-m", "init history"], check=True, capture_output=True)

        time.sleep(1.1)
        (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(proj), "add", "main.py"], check=True)
        subprocess.run(["git", "-C", str(proj), "commit", "-m", "add main.py"], check=True, capture_output=True)

        # Create mock ~/.gemini transcript with truncated_fields resolved from transcript_full.jsonl
        fake_gemini = self.tmp_dir / "fake_gemini"
        logs_dir = fake_gemini / "antigravity" / "brain" / "convo-abc" / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)

        compact = [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "created_at": "2099-01-01T10:00:00+00:00",
                "content": (
                    "<USER_REQUEST>\nCreate main.py greeting\n</USER_REQUEST>\n"
                    "<ADDITIONAL_METADATA>\ntime: now\n</ADDITIONAL_METADATA>"
                ),
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "created_at": "2099-01-01T10:00:05+00:00",
                "content": "TRUNCATED...",
                "truncated_fields": ["content"],
                "tool_calls": [{"name": "write_to_file", "args": {"TargetFile": str(proj / "main.py")}}],
            },
        ]
        full = [
            compact[0],
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "created_at": "2099-01-01T10:00:05+00:00",
                "content": "Created main.py printing a startup greeting.",
                "tool_calls": [{"name": "write_to_file", "args": {"TargetFile": str(proj / "main.py")}}],
            },
        ]
        (logs_dir / "transcript.jsonl").write_text(
            "\n".join(json.dumps(x) for x in compact) + "\n", encoding="utf-8"
        )
        (logs_dir / "transcript_full.jsonl").write_text(
            "\n".join(json.dumps(x) for x in full) + "\n", encoding="utf-8"
        )

        # Unrelated transcript for another folder should be ignored
        other_logs = fake_gemini / "antigravity" / "brain" / "convo-other" / ".system_generated" / "logs"
        other_logs.mkdir(parents=True)
        (other_logs / "transcript.jsonl").write_text(
            json.dumps(
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "created_at": "2099-01-01T11:00:00+00:00",
                    "content": "Other project",
                    "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/tmp/elsewhere/a.py"}}],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        loc = history_tool.locate_project([proj], gemini_home=fake_gemini, check_drift=True)
        self.assertTrue(loc["drift"]["has_drift"])
        self.assertEqual(loc["drift"]["git_commit_count"], 1)
        self.assertEqual(loc["drift"]["unrecorded_sessions"], 1)

        sessions = history_tool.scan_transcripts_for_project(
            proj, since_iso=loc["last_updated"], gemini_home=fake_gemini
        )
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["candidate_turns"][0]["user_input"], "Create main.py greeting")
        self.assertEqual(
            sessions[0]["candidate_turns"][0]["raw_ai_output_preview"],
            "Created main.py printing a startup greeting.",
        )

    def test_hooks_pre_invocation_and_stop_check(self) -> None:
        proj = self.tmp_dir / "hook_proj"
        proj.mkdir()
        history_tool.main(["init", "--project", str(proj), "--path", "conversation_history.md"])
        hist_file = proj / "conversation_history.md"

        # Redirect hook state dir to temp dir during test
        orig_pre_state = pre_invocation.STATE_DIR
        orig_stop_state = stop_check.STATE_DIR
        state_tmp = self.tmp_dir / "hook_state"
        pre_invocation.STATE_DIR = state_tmp
        stop_check.STATE_DIR = state_tmp
        try:
            convo_id = "test-convo-1"
            out1 = pre_invocation.handle_payload(
                {"conversationId": convo_id, "workspacePaths": [str(proj)], "invocationNum": 1}
            )
            self.assertIn("injectSteps", out1)
            self.assertIn("Found 'conversation_history.md'", out1["injectSteps"][0]["ephemeralMessage"])

            # Second invocation in same conversation does NOT spam
            out2 = pre_invocation.handle_payload(
                {"conversationId": convo_id, "workspacePaths": [str(proj)], "invocationNum": 2}
            )
            self.assertEqual(out2, {})

            # Mock transcript with substantive tool call without updating history_file
            tpath = self.tmp_dir / "t.jsonl"
            tpath.write_text(
                json.dumps(
                    {
                        "step_index": 0,
                        "type": "PLANNER_RESPONSE",
                        "content": "Updated code.",
                        "tool_calls": [{"name": "write_to_file"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stop1 = stop_check.handle_payload(
                {
                    "conversationId": convo_id,
                    "executionNum": 1,
                    "terminationReason": "model_stop",
                    "workspacePaths": [str(proj)],
                    "transcriptPath": str(tpath),
                }
            )
            self.assertEqual(stop1.get("decision"), "continue")

            # Second stop for same executionNum NEVER loops even if file unchanged
            stop2 = stop_check.handle_payload(
                {
                    "conversationId": convo_id,
                    "executionNum": 1,
                    "terminationReason": "model_stop",
                    "workspacePaths": [str(proj)],
                    "transcriptPath": str(tpath),
                }
            )
            self.assertEqual(stop2, {})

            # New executionNum after updating hist_file passes silently
            time.sleep(0.02)
            os.utime(hist_file, None)
            stop3 = stop_check.handle_payload(
                {
                    "conversationId": convo_id,
                    "executionNum": 2,
                    "terminationReason": "model_stop",
                    "workspacePaths": [str(proj)],
                    "transcriptPath": str(tpath),
                }
            )
            self.assertEqual(stop3, {})
        finally:
            pre_invocation.STATE_DIR = orig_pre_state
            stop_check.STATE_DIR = orig_stop_state


if __name__ == "__main__":
    unittest.main()
