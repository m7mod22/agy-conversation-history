#!/usr/bin/env python3
"""Antigravity PreInvocation hook for conversation-history startup detection."""

from __future__ import annotations

import json
import os
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


def handle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    workspace_paths = payload.get("workspacePaths") or []
    if not isinstance(workspace_paths, list) or not workspace_paths:
        return {}

    convo_id = str(payload.get("conversationId") or "default")
    state = _load_state(convo_id)
    if state.get("startup_injected"):
        return {}

    dirs = [Path(str(p)) for p in workspace_paths if isinstance(p, str) and p.strip()]
    if not dirs:
        return {}

    loc = history_tool.locate_project(dirs, check_drift=True)
    status = loc.get("status")

    state["startup_injected"] = True
    state["status"] = status
    state["stop_nudges"] = state.get("stop_nudges", {})

    msg: str | None = None
    if status == "found":
        hist_path = Path(loc["history_path"])
        try:
            state["last_seen_mtime_ns"] = hist_path.stat().st_mtime_ns
        except OSError:
            state["last_seen_mtime_ns"] = 0
        state["history_path"] = str(hist_path)

        rel = loc.get("history_rel_path", "conversation_history.md")
        turns = loc.get("total_turns", 0)
        drift = loc.get("drift") or {}
        drift_note = ""
        if drift.get("has_drift"):
            commits = drift.get("git_commit_count", 0)
            sessions = drift.get("unrecorded_sessions", 0)
            drift_note = (
                f" Drift detected ({commits} new git commit(s), {sessions} unrecorded session(s)); "
                "offer backfill via backfill-scan."
            )
        portable_note = ""
        if not loc.get("has_portable_setup"):
            portable_note = " Portable .agents setup missing; offer install-project."
        msg = (
            f"[conversation-history] Found '{rel}' ({turns} turn(s)). "
            "Read its Priority Index (P1->P3) before acting, and append the next Turn when done."
            f"{drift_note}{portable_note}"
        )
    elif status == "new_project":
        msg = (
            "[conversation-history] New project with no history file. "
            "Ask the user whether to create conversation_history.md and where in the project folder to locate it."
        )
    elif status == "existing_project":
        msg = (
            "[conversation-history] Existing project with no history file. "
            "Follow the conversation-history skill startup tree: ask whether a history file exists elsewhere "
            "or if this project never had one (generate from available conversation, ask owner, or opt out)."
        )

    _save_state(convo_id, state)
    if msg:
        return {"injectSteps": [{"ephemeralMessage": msg}]}
    return {}


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
