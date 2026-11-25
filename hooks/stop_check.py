#!/usr/bin/env python3
"""Antigravity Stop hook gently reminding once per execution if history was not updated."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "skills" / "conversation-history" / "scripts"
STATE_DIR = PLUGIN_ROOT / ".state"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import history_tool  # noqa: E402

SUBSTANTIVE_TOOLS = {"write_to_file", "replace_file_content", "run_command", "multi_replace_file_content"}


def _state_path(conversation_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", conversation_id or "default")
    return STATE_DIR / f"{safe_id}.json"


def _load_state(conversation_id: str) -> dict[str, Any]:
    p = _state_path(conversation_id)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(conversation_id: str, state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(conversation_id).write_text(json.dumps(state), encoding="utf-8")


def _transcript_has_substantive_activity(
    transcript_path: str, after_step_idx: int
) -> tuple[bool, int]:
    """Check transcript entries after after_step_idx for substantive work."""
    if not transcript_path:
        return False, after_step_idx
    tpath = Path(transcript_path)
    if not tpath.is_file():
        return False, after_step_idx

    max_step = after_step_idx
    substantive = False
    try:
        with tpath.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                idx = obj.get("step_index")
                if isinstance(idx, int):
                    if idx <= after_step_idx:
                        continue
                    if idx > max_step:
                        max_step = idx

                if obj.get("type") == "PLANNER_RESPONSE":
                    content = str(obj.get("content") or "")
                    if len(content.strip()) >= 250:
                        substantive = True
                    for tc in obj.get("tool_calls") or []:
                        if isinstance(tc, dict) and str(tc.get("name", "")) in SUBSTANTIVE_TOOLS:
                            substantive = True
    except OSError:
        return False, after_step_idx

    return substantive, max_step


def handle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("terminationReason") != "model_stop" or payload.get("error"):
        return {}

    workspace_paths = payload.get("workspacePaths") or []
    if not isinstance(workspace_paths, list) or not workspace_paths:
        return {}
    dirs = [Path(str(p)) for p in workspace_paths if isinstance(p, str) and p.strip()]
    if not dirs:
        return {}

    convo_id = str(payload.get("conversationId") or "default")
    exec_key = str(payload.get("executionNum") or "1")
    state = _load_state(convo_id)
    nudges = state.get("stop_nudges") or {}

    loc = history_tool.locate_project(dirs, check_drift=False)
    if loc.get("status") != "found":
        return {}

    hist_path = Path(loc["history_path"])
    try:
        current_mtime_ns = hist_path.stat().st_mtime_ns
    except OSError:
        return {}

    last_seen_mtime = int(state.get("last_seen_mtime_ns") or 0)
    last_step = int(state.get("last_checked_step_idx") or -1)
    substantive, max_step = _transcript_has_substantive_activity(
        str(payload.get("transcriptPath") or ""), last_step
    )

    if current_mtime_ns > last_seen_mtime:
        state["last_seen_mtime_ns"] = current_mtime_ns
        state["last_checked_step_idx"] = max_step
        _save_state(convo_id, state)
        return {}

    if int(nudges.get(exec_key, 0)) >= 1:
        state["last_checked_step_idx"] = max_step
        _save_state(convo_id, state)
        return {}

    if not substantive:
        state["last_checked_step_idx"] = max_step
        _save_state(convo_id, state)
        return {}

    nudges[exec_key] = 1
    state["stop_nudges"] = nudges
    state["last_seen_mtime_ns"] = current_mtime_ns
    _save_state(convo_id, state)

    rel = loc.get("history_rel_path", "conversation_history.md")
    next_turn = int(loc.get("total_turns") or 0) + 1
    return {
        "decision": "continue",
        "reason": (
            f"[conversation-history] This turn appears substantive, and '{rel}' has not been updated yet. "
            f"Append Turn {next_turn} via history_tool.py append-turn (architecture/intent summary only, no raw code) before stopping."
        ),
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        out = handle_payload(payload if isinstance(payload, dict) else {})
    except Exception:  # noqa: BLE001
        out = {}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
