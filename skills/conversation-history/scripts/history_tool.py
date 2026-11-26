#!/usr/bin/env python3
"""Deterministic helper CLI for the Antigravity conversation-history skill/plugin."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

UNIQUE_MARKER = "<!-- AGY-CONVERSATION-HISTORY:v1 -->"
CONFIG_REL_PATH = Path(".agents") / "conversation-history.json"
PORTABLE_PLUGIN_REL_PATH = Path(".agents") / "plugins" / "conversation-history"

SKIP_DIRS = {
    ".git",
    ".agents",
    ".agent",
    "_agents",
    "_agent",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

IGNORED_NEW_PROJECT_FILES = {".DS_Store", "Thumbs.db", ".gitignore", ".gitattributes"}

VALID_PRIORITIES = ("P1", "P2", "P3", "P4")

# Programming / config languages disallowed as multi-line code dumps in AI Output
DISALLOWED_CODE_LANGS = {
    "python",
    "py",
    "javascript",
    "js",
    "typescript",
    "ts",
    "tsx",
    "jsx",
    "c",
    "cpp",
    "c++",
    "h",
    "hpp",
    "java",
    "go",
    "golang",
    "rust",
    "rs",
    "bash",
    "sh",
    "zsh",
    "fish",
    "powershell",
    "ps1",
    "cmd",
    "bat",
    "json",
    "yaml",
    "yml",
    "toml",
    "ini",
    "sql",
    "html",
    "css",
    "scss",
    "qml",
    "xml",
    "php",
    "rb",
    "ruby",
    "swift",
    "kt",
    "kotlin",
    "dart",
    "r",
    "scala",
    "lua",
    "perl",
    "diff",
    "patch",
}

ALLOWED_DIAGRAM_LANGS = {"mermaid", "text", "txt", "plaintext", ""}

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
        ),
        "[REDACTED PRIVATE KEY]",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._-]{16,}"), r"\1[REDACTED_TOKEN]"),
    (
        re.compile(
            r"(?i)\b((?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd|client[_-]?secret)\s*[:=]\s*[\"']?)([^\s\"']{6,})([\"']?)"
        ),
        r"\1[REDACTED]\3",
    ),
]

FENCED_BLOCK_RE = re.compile(r"```([^\n`]*)\n([\s\S]*?)```", re.MULTILINE)
TURN_HEADER_RE = re.compile(r"^### Turn (\d+)\s+—\s+(.+?)\s*$", re.MULTILINE)
PRIORITY_POINT_RE = re.compile(r"^-\s+`\[(P[1-4])\]`\s+(.*)$")
SUPERSEDE_RE = re.compile(
    r"\[supersedes:\s*Turn\s+(\d+)(?:\s+(all))?\]", re.IGNORECASE
)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def now_short() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def redact_secrets(text: str) -> str:
    """Mask common credential, token, and private-key patterns."""
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def has_unredacted_secrets(text: str) -> bool:
    """Return True if any secret pattern matches text."""
    return any(pattern.search(text) for pattern, _ in SECRET_PATTERNS)


def sanitize_user_input(text: str) -> str:
    """Redact secrets and collapse >15-line fenced code pastes in User Input."""
    cleaned = redact_secrets(text).strip()

    def _replace_large_fence(match: re.Match[str]) -> str:
        body = match.group(2)
        lines = body.splitlines()
        if len(lines) > 15:
            lang = match.group(1).strip() or "code"
            return f"[User shared {lang} snippet ({len(lines)} lines) — see project files]"
        return match.group(0)

    return FENCED_BLOCK_RE.sub(_replace_large_fence, cleaned)


def validate_ai_output_no_raw_code(text: str) -> list[str]:
    """Return validation error messages if AI Output contains raw source code dumps."""
    errors: list[str] = []
    for match in FENCED_BLOCK_RE.finditer(text):
        lang = match.group(1).strip().lower()
        body_lines = [ln for ln in match.group(2).splitlines() if ln.strip()]
        if lang in DISALLOWED_CODE_LANGS:
            errors.append(
                f"AI Output contains a fenced `{lang}` code block. "
                "Describe what the code is meant to do and its architecture instead of pasting raw code."
            )
        elif lang not in ALLOWED_DIAGRAM_LANGS:
            errors.append(
                f"AI Output contains a fenced `{lang}` block. "
                "Remove source code blocks and summarize intent/architecture in prose."
            )
        elif lang == "" and len(body_lines) > 4:
            errors.append(
                f"AI Output contains an untagged multi-line fenced block ({len(body_lines)} lines). "
                "Keep only inline backticks or compact diagrams (`mermaid`/`text` <= 15 lines)."
            )
        elif lang in {"text", "txt", "plaintext", "mermaid"} and len(body_lines) > 15:
            errors.append(
                f"AI Output `{lang}` block is {len(body_lines)} lines (>15). Summarize concisely in prose."
            )
    return errors


def safe_resolve_within(project_dir: Path, rel_or_abs: str) -> Path:
    """Resolve a path and verify it stays inside project_dir."""
    root = project_dir.resolve()
    candidate = Path(rel_or_abs)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"History file path '{rel_or_abs}' must stay inside project directory '{root}'."
        ) from exc
    return resolved


GENERIC_WORKSPACE_WORDS = {"project", "repo", "repository", "workspace", "codebase"}


def default_history_filename(project_dir: Path, project_name: str | None = None) -> str:
    """Derive a workspace-prefixed filename like Collarms_conversation_history.md."""
    raw = (project_name or project_dir.resolve().name or "").strip()
    tokens = re.findall(r"[A-Za-z0-9]+", raw)
    while len(tokens) > 1 and tokens[-1].lower() in GENERIC_WORKSPACE_WORDS:
        tokens.pop()
    if not tokens or (len(tokens) == 1 and tokens[0].lower() in GENERIC_WORKSPACE_WORDS):
        return "conversation_history.md"
    prefix = "_".join(tokens)
    return f"{prefix}_conversation_history.md"


def read_config(project_dir: Path) -> dict[str, Any] | None:
    cfg_path = project_dir / CONFIG_REL_PATH
    if not cfg_path.is_file():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_config(project_dir: Path, data: dict[str, Any]) -> Path:
    cfg_path = project_dir / CONFIG_REL_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def _global_pause_path(gemini_home: Path | None = None) -> Path:
    home = gemini_home or (Path.home() / ".gemini")
    return home / "config" / "plugins" / "conversation-history" / ".state" / "global_pause.json"


def read_global_pause(gemini_home: Path | None = None) -> dict[str, Any] | None:
    gp = _global_pause_path(gemini_home)
    if not gp.is_file():
        return None
    try:
        data = json.loads(gp.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("paused") else None
    except (OSError, json.JSONDecodeError):
        return None


def write_global_pause(
    paused: bool, paused_at: str | None = None, gemini_home: Path | None = None
) -> Path:
    gp = _global_pause_path(gemini_home)
    gp.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"version": 1, "paused": paused}
    if paused and paused_at:
        payload["paused_at"] = paused_at
    gp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return gp


def file_has_unique_marker(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            return False
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            head = fh.read(4096)
        return UNIQUE_MARKER in head
    except OSError:
        return False


def scan_for_history_file(project_dir: Path) -> Path | None:
    """Walk project_dir (excluding SKIP_DIRS) looking for UNIQUE_MARKER."""
    root = project_dir.resolve()
    candidates_priority: list[Path] = []
    candidates_other: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            lower = fname.lower()
            if "conversation_history" in lower:
                candidates_priority.append(fpath)
            elif fpath.suffix.lower() in {".md", ".txt", ""}:
                candidates_other.append(fpath)

    for path in candidates_priority + candidates_other:
        if file_has_unique_marker(path):
            return path
    return None


def is_new_project(project_dir: Path) -> bool:
    """Return True if project_dir looks empty / freshly initialized with no real files."""
    root = project_dir.resolve()
    if not root.exists():
        return True

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", ".agents", ".agent", "_agents", "_agent"}]
        for fname in filenames:
            if fname in IGNORED_NEW_PROJECT_FILES:
                continue
            fpath = Path(dirpath) / fname
            if fname.lower() == "readme.md" and Path(dirpath) == root:
                try:
                    if fpath.stat().st_size <= 250:
                        continue
                except OSError:
                    pass
            return False
    return True


def parse_history_file(path: Path) -> dict[str, Any]:
    """Parse conversation_history.md into header metadata and turn structures."""
    text = path.read_text(encoding="utf-8")
    if UNIQUE_MARKER not in text[:4096]:
        raise ValueError(f"File '{path}' does not contain unique marker '{UNIQUE_MARKER}'.")

    project_match = re.search(r"^- \*\*Project:\*\*\s*(.+)$", text, re.MULTILINE)
    updated_match = re.search(r"^- \*\*Last Updated:\*\*\s*(.+)$", text, re.MULTILINE)
    turns_match = re.search(r"^- \*\*Total Turns:\*\*\s*(\d+)$", text, re.MULTILINE)

    log_marker = "## Turn-by-Turn Log"
    log_pos = text.find(log_marker)
    log_section = text[log_pos + len(log_marker) :] if log_pos != -1 else ""

    matches = list(TURN_HEADER_RE.finditer(log_section))
    turns: list[dict[str, Any]] = []
    for idx, m in enumerate(matches):
        turn_num = int(m.group(1))
        timestamp = m.group(2).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(log_section)
        body = log_section[start:end].strip()

        user_input = _extract_subsection(body, "**User Input:**", "**AI Output:**")
        ai_output = _extract_subsection(body, "**AI Output:**", "**Priority Points:**")
        points_raw = _extract_subsection(body, "**Priority Points:**", None)

        points: list[dict[str, str]] = []
        for line in points_raw.splitlines():
            pm = PRIORITY_POINT_RE.match(line.strip())
            if pm:
                points.append({"priority": pm.group(1), "text": pm.group(2).strip()})

        turns.append(
            {
                "turn": turn_num,
                "timestamp": timestamp,
                "user_input": user_input.strip(),
                "ai_output": ai_output.strip(),
                "points": points,
            }
        )

    return {
        "project": project_match.group(1).strip() if project_match else path.parent.name,
        "last_updated": updated_match.group(1).strip() if updated_match else "",
        "declared_total_turns": int(turns_match.group(1)) if turns_match else len(turns),
        "turns": turns,
    }


def _extract_subsection(body: str, start_header: str, next_header: str | None) -> str:
    s_idx = body.find(start_header)
    if s_idx == -1:
        return ""
    content_start = s_idx + len(start_header)
    if next_header is None:
        return body[content_start:].strip()
    n_idx = body.find(next_header, content_start)
    if n_idx == -1:
        return body[content_start:].strip()
    return body[content_start:n_idx].strip()


def build_priority_index_markdown(turns: list[dict[str, Any]]) -> str:
    """Build P1/P2/P3 index sections, retiring points superseded by later turns."""
    retired: set[tuple[int, str]] = set()
    for t in turns:
        for pt in t["points"]:
            for m in SUPERSEDE_RE.finditer(pt["text"]):
                target_turn = int(m.group(1))
                is_all = bool(m.group(2))
                if is_all:
                    for prio in ("P1", "P2", "P3"):
                        retired.add((target_turn, prio))
                else:
                    retired.add((target_turn, pt["priority"]))

    buckets: dict[str, list[str]] = {"P1": [], "P2": [], "P3": []}
    for t in turns:
        tnum = t["turn"]
        for pt in t["points"]:
            prio = pt["priority"]
            if prio not in buckets:
                continue
            if (tnum, prio) in retired:
                continue
            buckets[prio].append(f"- `[Turn {tnum}]` {pt['text']}")

    p1_body = "\n".join(buckets["P1"]) if buckets["P1"] else "- _None recorded yet._"
    p2_body = "\n".join(buckets["P2"]) if buckets["P2"] else "- _None recorded yet._"
    p3_body = "\n".join(buckets["P3"]) if buckets["P3"] else "- _None recorded yet._"

    return (
        "## Priority Index\n\n"
        "### Priority 1 — Hard Rules (Always / Never)\n"
        f"{p1_body}\n\n"
        "### Priority 2 — Architecture, Workflow, Preferences & Mistakes\n"
        f"{p2_body}\n\n"
        "### Priority 3 — Verified Outcomes & Current State\n"
        f"{p3_body}"
    )


def render_history_markdown(
    project_name: str, last_updated: str, turns: list[dict[str, Any]]
) -> str:
    """Render the complete conversation_history.md document."""
    priority_index = build_priority_index_markdown(turns)
    turn_blocks: list[str] = []
    for t in turns:
        pts_md = "\n".join(f"- `[{pt['priority']}]` {pt['text']}" for pt in t["points"])
        turn_blocks.append(
            f"### Turn {t['turn']} — {t['timestamp']}\n"
            f"**User Input:**\n{t['user_input']}\n\n"
            f"**AI Output:**\n{t['ai_output']}\n\n"
            f"**Priority Points:**\n{pts_md}"
        )

    turns_body = "\n\n".join(turn_blocks) if turn_blocks else "_No turns recorded yet._"
    return (
        f"{UNIQUE_MARKER}\n"
        "# Project Conversation History\n\n"
        "> **For any AI assistant opening this project:** Read the **Priority Index** below first. "
        "Strictly follow `P1` rules, respect `P2` architecture/workflow/preferences/mistakes, and use `P3` for current state. "
        "Consult the **Turn-by-Turn Log** for full context. After every meaningful input or successful output, append the next Turn "
        "(summarize code by what it is meant to do and its architecture—never dump raw source code) and update the Priority Index.\n\n"
        f"- **Project:** {project_name}\n"
        f"- **Last Updated:** {last_updated}\n"
        f"- **Total Turns:** {len(turns)}\n\n"
        "---\n\n"
        f"{priority_index}\n\n"
        "---\n\n"
        "## Turn-by-Turn Log\n\n"
        f"{turns_body}\n"
    )


def normalize_points(raw_points: Any) -> list[dict[str, str]]:
    """Normalize JSON priority points into [{'priority': 'P1', 'text': '...'}]."""
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("points-json must be a non-empty JSON array.")

    normalized: list[dict[str, str]] = []
    for item in raw_points:
        if isinstance(item, dict):
            prio = str(item.get("priority", "")).strip().upper()
            text = str(item.get("text", "")).strip()
        elif isinstance(item, str):
            m = re.match(r"^(?:-\s+)?`?\[(P[1-4])\]`?\s+(.+)$", item.strip())
            if not m:
                raise ValueError(f"Invalid string priority point: {item!r}")
            prio, text = m.group(1), m.group(2).strip()
        else:
            raise ValueError(f"Unsupported point item type: {type(item).__name__}")

        if prio not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority '{prio}'. Expected one of {VALID_PRIORITIES}.")
        if not text:
            raise ValueError("Priority point text cannot be empty.")
        normalized.append({"priority": prio, "text": redact_secrets(text)})

    return normalized


def _parse_iso_dt(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed
    except ValueError:
        return None


def _iter_transcript_paths(project_dir: Path, gemini_home: Path | None = None) -> list[Path]:
    home = gemini_home or (Path.home() / ".gemini")
    candidates: list[Path] = []
    for root in (
        home / "antigravity" / "brain",
        home / "antigravity-cli" / "brain",
        home / "antigravity-ide" / "brain",
    ):
        if root.is_dir():
            candidates.extend(root.glob("*/.system_generated/logs/transcript.jsonl"))

    ws_gemini = project_dir / ".gemini"
    if ws_gemini.is_dir():
        candidates.extend(ws_gemini.glob("*/transcript.jsonl"))
        candidates.extend(ws_gemini.glob("*/.system_generated/logs/transcript.jsonl"))

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp not in seen and rp.is_file():
            seen.add(rp)
            unique.append(rp)
    return unique


def _load_full_transcript_map(compact_path: Path) -> dict[int, dict[str, Any]]:
    full_path = compact_path.with_name("transcript_full.jsonl")
    if not full_path.is_file():
        return {}
    mapping: dict[int, dict[str, Any]] = {}
    try:
        with full_path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    idx = obj.get("step_index")
                    if isinstance(idx, int):
                        mapping[idx] = obj
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {}
    return mapping


def _extract_paths_from_tool_calls(tool_calls: Any) -> list[str]:
    found: list[str] = []
    if not isinstance(tool_calls, list):
        return found
    path_keys = {"AbsolutePath", "TargetFile", "Cwd", "DirectoryPath", "SearchPath", "path"}
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        args = tc.get("args") or tc.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if isinstance(args, dict):
            for k in path_keys:
                v = args.get(k)
                if isinstance(v, str) and v.strip():
                    found.append(v.strip())
    return found


def scan_transcripts_for_project(
    project_dir: Path,
    since_iso: str | None = None,
    gemini_home: Path | None = None,
    max_sessions: int = 10,
) -> list[dict[str, Any]]:
    """Find Antigravity transcript.jsonl files that touched project_dir."""
    proj_root = project_dir.resolve()
    proj_prefix = str(proj_root)
    since_dt = _parse_iso_dt(since_iso or "")

    sessions: list[dict[str, Any]] = []
    for tpath in _iter_transcript_paths(proj_root, gemini_home):
        matched_paths: set[str] = set()
        raw_steps: list[dict[str, Any]] = []
        full_map: dict[int, dict[str, Any]] | None = None

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
                    if obj.get("truncated_fields"):
                        if full_map is None:
                            full_map = _load_full_transcript_map(tpath)
                        idx = obj.get("step_index")
                        if isinstance(idx, int) and idx in full_map:
                            obj = full_map[idx]
                    raw_steps.append(obj)
                    for p in _extract_paths_from_tool_calls(obj.get("tool_calls")):
                        if p == proj_prefix or p.startswith(proj_prefix + os.sep):
                            matched_paths.add(p)
        except OSError:
            continue

        if not matched_paths:
            continue

        turns = _extract_turns_from_steps(raw_steps, since_dt)
        if not turns:
            continue

        convo_id = tpath.parent.parent.parent.name if tpath.parent.name == "logs" else tpath.parent.name
        sessions.append(
            {
                "conversation_id": convo_id,
                "transcript_path": str(tpath),
                "matched_path_count": len(matched_paths),
                "latest_timestamp": turns[-1]["timestamp"],
                "candidate_turns": turns,
            }
        )

    sessions.sort(key=lambda s: s["latest_timestamp"], reverse=True)
    return sessions[:max_sessions]


def _extract_turns_from_steps(
    steps: list[dict[str, Any]], since_dt: dt.datetime | None
) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    current_user: str | None = None
    current_ts: str = ""
    assistant_chunks: list[str] = []

    def _flush() -> None:
        nonlocal current_user, current_ts, assistant_chunks
        if current_user and assistant_chunks:
            if since_dt is not None:
                step_dt = _parse_iso_dt(current_ts)
                if step_dt is not None and step_dt <= since_dt:
                    current_user = None
                    assistant_chunks = []
                    return
            combined_out = "\n".join(assistant_chunks).strip()
            turns.append(
                {
                    "timestamp": current_ts,
                    "user_input": sanitize_user_input(current_user)[:2000],
                    "raw_ai_output_preview": redact_secrets(combined_out)[:2000],
                }
            )
        current_user = None
        assistant_chunks = []

    def _clean_user_wrapper(text: str) -> str:
        text = re.sub(r"<ADDITIONAL_METADATA>[\s\S]*?</ADDITIONAL_METADATA>", "", text)
        text = re.sub(r"</?USER_REQUEST>", "", text)
        return text.strip()

    for st in steps:
        stype = str(st.get("type", ""))
        src = str(st.get("source", ""))
        content = str(st.get("content", "") or "").strip()
        ts = str(st.get("created_at", "") or "")

        if stype == "USER_INPUT" or (src == "USER_EXPLICIT" and content):
            _flush()
            current_user = _clean_user_wrapper(content)
            current_ts = ts
        elif stype == "PLANNER_RESPONSE" and content:
            if current_user is not None:
                assistant_chunks.append(content)
                if ts:
                    current_ts = ts

    _flush()
    return turns


def detect_git_drift(
    project_dir: Path, history_path: Path | None, since_iso: str
) -> list[dict[str, str]]:
    """Return git commits after since_iso that touched non-history files."""
    if not (project_dir / ".git").exists():
        return []
    cmd = ["git", "-C", str(project_dir), "log", "--name-only", "--pretty=format:__COMMIT__\t%h\t%cI\t%s"]
    if since_iso:
        cmd.append(f"--since={since_iso}")
    else:
        cmd.extend(["-n", "20"])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        if res.returncode != 0:
            return []
    except (OSError, subprocess.SubprocessError):
        return []

    hist_rel = None
    if history_path is not None:
        try:
            hist_rel = str(history_path.resolve().relative_to(project_dir.resolve()))
        except ValueError:
            hist_rel = None

    commits: list[dict[str, str]] = []
    cur: dict[str, Any] | None = None

    def _keep(c: dict[str, Any] | None) -> None:
        if not c:
            return
        files = [
            f
            for f in c["files"]
            if f
            and f != hist_rel
            and not f.startswith(".agents/plugins/conversation-history/")
            and f != ".agents/conversation-history.json"
        ]
        if files or not c["files"]:
            commits.append(
                {
                    "hash": c["hash"],
                    "timestamp": c["timestamp"],
                    "subject": c["subject"],
                    "files": ", ".join(files[:10]),
                }
            )

    since_dt = _parse_iso_dt(since_iso)
    for line in res.stdout.splitlines():
        if line.startswith("__COMMIT__\t"):
            _keep(cur)
            parts = line.split("\t", 3)
            if len(parts) == 4:
                c_dt = _parse_iso_dt(parts[2])
                if since_dt is not None and c_dt is not None and c_dt <= since_dt:
                    cur = None
                    continue
                cur = {"hash": parts[1], "timestamp": parts[2], "subject": parts[3], "files": []}
            else:
                cur = None
        elif cur is not None and line.strip():
            cur["files"].append(line.strip())
    _keep(cur)
    return commits


def locate_project(
    project_dirs: list[Path], gemini_home: Path | None = None, check_drift: bool = True
) -> dict[str, Any]:
    """Locate history file or classify project status across one or more roots."""
    if not project_dirs:
        return {"status": "no_workspace"}

    gp = read_global_pause(gemini_home)
    if gp:
        primary = project_dirs[0].resolve()
        return {
            "status": "paused",
            "scope": "global",
            "paused_at": gp.get("paused_at", ""),
            "project_dir": str(primary),
        }

    for project_dir in project_dirs:
        if not project_dir.exists():
            continue
        cfg = read_config(project_dir)
        has_portable = (project_dir / PORTABLE_PLUGIN_REL_PATH / "plugin.json").is_file()

        if cfg and cfg.get("status") == "opted_out":
            return {
                "status": "opted_out",
                "project_dir": str(project_dir.resolve()),
                "has_portable_setup": has_portable,
            }

        history_path: Path | None = None
        if cfg and cfg.get("historyFile"):
            try:
                candidate = safe_resolve_within(project_dir, str(cfg["historyFile"]))
                if file_has_unique_marker(candidate):
                    history_path = candidate
            except ValueError:
                history_path = None

        if cfg and cfg.get("status") == "paused":
            rel_path = (
                str(history_path.resolve().relative_to(project_dir.resolve()))
                if history_path is not None
                else cfg.get("historyFile")
            )
            return {
                "status": "paused",
                "scope": "project",
                "paused_at": cfg.get("paused_at", ""),
                "project_dir": str(project_dir.resolve()),
                "history_path": str(history_path.resolve()) if history_path else None,
                "history_rel_path": rel_path,
                "has_portable_setup": has_portable,
            }

        if history_path is None:
            history_path = scan_for_history_file(project_dir)

        if history_path is not None:
            parsed = parse_history_file(history_path)
            rel_path = str(history_path.resolve().relative_to(project_dir.resolve()))
            drift: dict[str, Any] = {"has_drift": False, "git_commits": [], "unrecorded_sessions": 0}
            if check_drift:
                git_commits = detect_git_drift(
                    project_dir, history_path, parsed["last_updated"]
                )
                sessions = scan_transcripts_for_project(
                    project_dir,
                    since_iso=parsed["last_updated"] or None,
                    gemini_home=gemini_home,
                    max_sessions=5,
                )
                drift = {
                    "has_drift": bool(git_commits or sessions),
                    "git_commit_count": len(git_commits),
                    "git_commits": git_commits[:5],
                    "unrecorded_sessions": len(sessions),
                }
            return {
                "status": "found",
                "project_dir": str(project_dir.resolve()),
                "history_path": str(history_path.resolve()),
                "history_rel_path": rel_path,
                "total_turns": len(parsed["turns"]),
                "last_updated": parsed["last_updated"],
                "has_portable_setup": has_portable,
                "drift": drift,
            }

    primary = project_dirs[0].resolve()
    proj_type = "new_project" if is_new_project(primary) else "existing_project"
    return {
        "status": proj_type,
        "project_dir": str(primary),
        "suggested_filename": default_history_filename(primary),
        "has_portable_setup": (primary / PORTABLE_PLUGIN_REL_PATH / "plugin.json").is_file(),
    }


def install_portable_project(project_dir: Path, history_rel_path: str) -> dict[str, Any]:
    """Install self-contained .agents/plugins/conversation-history/ into project_dir."""
    plugin_root = Path(__file__).resolve().parents[3]
    target_root = project_dir.resolve() / PORTABLE_PLUGIN_REL_PATH
    skill_src = plugin_root / "skills"
    skill_dst = target_root / "skills"

    (target_root / "rules").mkdir(parents=True, exist_ok=True)
    shutil.copy2(plugin_root / "plugin.json", target_root / "plugin.json")
    shutil.copy2(plugin_root / "rules" / "AGENTS.md", target_root / "rules" / "AGENTS.md")

    if skill_dst.exists():
        shutil.rmtree(skill_dst)
    shutil.copytree(
        skill_src,
        skill_dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )

    cfg = write_config(
        project_dir.resolve(),
        {"version": 1, "status": "active", "historyFile": history_rel_path},
    )
    return {
        "portable_plugin_dir": str(target_root),
        "config_path": str(cfg),
        "historyFile": history_rel_path,
    }


def cmd_locate(args: argparse.Namespace) -> int:
    dirs = [Path(p) for p in args.project]
    gemini_home = Path(args.gemini_home) if args.gemini_home else None
    result = locate_project(dirs, gemini_home=gemini_home, check_drift=not args.no_drift)
    print(json.dumps(result, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).resolve()
    chosen_path = args.path or default_history_filename(project_dir, args.project_name)
    target = safe_resolve_within(project_dir, chosen_path)
    if target.exists() and not args.force:
        if file_has_unique_marker(target):
            print(json.dumps({"status": "already_exists", "history_path": str(target)}, indent=2))
            return 0
        raise FileExistsError(
            f"Target '{target}' already exists without unique marker. Use --force to overwrite."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    proj_name = args.project_name or project_dir.name
    content = render_history_markdown(proj_name, now_iso(), [])
    target.write_text(content, encoding="utf-8")

    rel = str(target.relative_to(project_dir))
    installed: dict[str, Any] | None = None
    if args.install_setup:
        installed = install_portable_project(project_dir, rel)
    else:
        write_config(
            project_dir, {"version": 1, "status": "active", "historyFile": rel}
        )

    print(
        json.dumps(
            {
                "status": "initialized",
                "history_path": str(target),
                "history_rel_path": rel,
                "portable_setup": installed,
            },
            indent=2,
        )
    )
    return 0


def cmd_opt_out(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).resolve()
    cfg = write_config(project_dir, {"version": 1, "status": "opted_out"})
    print(json.dumps({"status": "opted_out", "config_path": str(cfg)}, indent=2))
    return 0


def cmd_history_pause(args: argparse.Namespace) -> int:
    gemini_home = Path(args.gemini_home) if args.gemini_home else None
    paused_at = now_iso()
    if args.is_global:
        gp = write_global_pause(True, paused_at, gemini_home=gemini_home)
        print(
            json.dumps(
                {
                    "status": "paused",
                    "scope": "global",
                    "paused_at": paused_at,
                    "state_path": str(gp),
                },
                indent=2,
            )
        )
        return 0

    project_dir = Path(args.project).resolve()
    existing_cfg = read_config(project_dir) or {}
    history_rel = existing_cfg.get("historyFile")
    if not history_rel:
        found = scan_for_history_file(project_dir)
        if found is not None:
            history_rel = str(found.resolve().relative_to(project_dir))

    new_cfg: dict[str, Any] = {"version": 1, "status": "paused", "paused_at": paused_at}
    if history_rel:
        new_cfg["historyFile"] = history_rel
    cfg_path = write_config(project_dir, new_cfg)
    print(
        json.dumps(
            {
                "status": "paused",
                "scope": "project",
                "paused_at": paused_at,
                "historyFile": history_rel,
                "config_path": str(cfg_path),
            },
            indent=2,
        )
    )
    return 0


def cmd_history_continue(args: argparse.Namespace) -> int:
    gemini_home = Path(args.gemini_home) if args.gemini_home else None
    project_dir = Path(args.project).resolve()

    paused_at = ""
    gp = read_global_pause(gemini_home)
    if gp:
        paused_at = str(gp.get("paused_at") or "")
        write_global_pause(False, None, gemini_home=gemini_home)

    existing_cfg = read_config(project_dir) or {}
    if not paused_at:
        paused_at = str(existing_cfg.get("paused_at") or "")

    history_rel = existing_cfg.get("historyFile")
    if not history_rel:
        found = scan_for_history_file(project_dir)
        if found is not None:
            history_rel = str(found.resolve().relative_to(project_dir))

    if not args.is_global or existing_cfg.get("status") == "paused":
        new_cfg: dict[str, Any] = {"version": 1, "status": "active"}
        if history_rel:
            new_cfg["historyFile"] = history_rel
        write_config(project_dir, new_cfg)

    loc = locate_project([project_dir], gemini_home=gemini_home, check_drift=False)
    gap_since = paused_at or loc.get("last_updated") or ""
    gap_drift: dict[str, Any] = {
        "has_drift": False,
        "git_commit_count": 0,
        "git_commits": [],
        "unrecorded_sessions": 0,
    }
    if loc.get("status") == "found" and gap_since:
        hist_path = Path(loc["history_path"])
        commits = detect_git_drift(project_dir, hist_path, gap_since)
        sessions = scan_transcripts_for_project(
            project_dir,
            since_iso=gap_since,
            gemini_home=gemini_home,
            max_sessions=5,
        )
        gap_drift = {
            "has_drift": bool(commits or sessions),
            "git_commit_count": len(commits),
            "git_commits": commits[:5],
            "unrecorded_sessions": len(sessions),
        }

    print(
        json.dumps(
            {
                "status": "active",
                "locate_status": loc.get("status"),
                "paused_at": paused_at,
                "history_path": loc.get("history_path"),
                "history_rel_path": loc.get("history_rel_path"),
                "total_turns": loc.get("total_turns", 0),
                "pause_gap_drift": gap_drift,
            },
            indent=2,
        )
    )
    return 0


def _read_text_arg(value: str | None, file_path: str | None, label: str) -> str:
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    if value is not None:
        return value
    raise ValueError(f"Either --{label} or --{label}-file must be provided.")


def cmd_append_turn(args: argparse.Namespace) -> int:
    history_path = Path(args.file).resolve()
    parsed = parse_history_file(history_path)

    raw_input = _read_text_arg(args.input, args.input_file, "input")
    raw_output = _read_text_arg(args.output, args.output_file, "output")
    raw_points = _read_text_arg(args.points_json, args.points_file, "points")

    code_errors = validate_ai_output_no_raw_code(raw_output)
    if code_errors:
        raise ValueError(" ".join(code_errors))

    clean_input = sanitize_user_input(raw_input)
    clean_output = redact_secrets(raw_output).strip()
    points = normalize_points(json.loads(raw_points))

    next_turn = (max((t["turn"] for t in parsed["turns"]), default=0)) + 1
    parsed["turns"].append(
        {
            "turn": next_turn,
            "timestamp": args.timestamp or now_short(),
            "user_input": clean_input,
            "ai_output": clean_output,
            "points": points,
        }
    )

    updated_iso = now_iso()
    rendered = render_history_markdown(parsed["project"], updated_iso, parsed["turns"])
    history_path.write_text(rendered, encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "appended",
                "turn": next_turn,
                "total_turns": len(parsed["turns"]),
                "history_path": str(history_path),
            },
            indent=2,
        )
    )
    return 0


def cmd_sync_index(args: argparse.Namespace) -> int:
    history_path = Path(args.file).resolve()
    parsed = parse_history_file(history_path)
    rendered = render_history_markdown(parsed["project"], now_iso(), parsed["turns"])
    history_path.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "synced",
                "total_turns": len(parsed["turns"]),
                "history_path": str(history_path),
            },
            indent=2,
        )
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    history_path = Path(args.file).resolve()
    issues: list[str] = []
    parsed = parse_history_file(history_path)

    if parsed["declared_total_turns"] != len(parsed["turns"]):
        issues.append(
            f"Declared Total Turns ({parsed['declared_total_turns']}) != actual turns ({len(parsed['turns'])})."
        )

    expected_num = 1
    for t in parsed["turns"]:
        if t["turn"] != expected_num:
            issues.append(f"Expected Turn {expected_num}, found Turn {t['turn']}.")
        expected_num += 1
        if not t["user_input"]:
            issues.append(f"Turn {t['turn']} has empty User Input.")
        if not t["ai_output"]:
            issues.append(f"Turn {t['turn']} has empty AI Output.")
        if not t["points"]:
            issues.append(f"Turn {t['turn']} has no Priority Points.")
        for err in validate_ai_output_no_raw_code(t["ai_output"]):
            issues.append(f"Turn {t['turn']}: {err}")
        if has_unredacted_secrets(t["user_input"]) or has_unredacted_secrets(t["ai_output"]):
            issues.append(f"Turn {t['turn']}: Potential unredacted secret detected.")

    result = {
        "valid": len(issues) == 0,
        "total_turns": len(parsed["turns"]),
        "issues": issues,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


def cmd_install_project(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).resolve()
    chosen = args.history_path or default_history_filename(project_dir)
    history_target = safe_resolve_within(project_dir, chosen)
    rel_path = str(history_target.relative_to(project_dir))
    info = install_portable_project(project_dir, rel_path)
    print(json.dumps({"status": "installed", **info}, indent=2))
    return 0


def cmd_backfill_scan(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).resolve()
    gemini_home = Path(args.gemini_home) if args.gemini_home else None
    since_iso = args.since
    if since_iso is None:
        loc = locate_project([project_dir], gemini_home=gemini_home, check_drift=False)
        if loc.get("status") == "found":
            since_iso = loc.get("last_updated") or None

    sessions = scan_transcripts_for_project(
        project_dir,
        since_iso=since_iso,
        gemini_home=gemini_home,
        max_sessions=args.max_sessions,
    )
    commits = detect_git_drift(project_dir, None, since_iso or "")
    print(
        json.dumps(
            {
                "project_dir": str(project_dir),
                "since": since_iso,
                "sessions": sessions,
                "git_commits": commits,
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Antigravity conversation-history helper CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_loc = sub.add_parser("locate", help="Locate history file or classify project")
    p_loc.add_argument("--project", action="append", required=True, help="Project root directory")
    p_loc.add_argument("--gemini-home", help="Override ~/.gemini directory for testing")
    p_loc.add_argument("--no-drift", action="store_true", help="Skip git/transcript drift checks")
    p_loc.set_defaults(func=cmd_locate)

    p_init = sub.add_parser("init", help="Initialize a new <Workspace>_conversation_history.md file")
    p_init.add_argument("--project", required=True)
    p_init.add_argument("--path", default=None, help="Relative path inside project (defaults to <Workspace>_conversation_history.md)")
    p_init.add_argument("--project-name")
    p_init.add_argument("--install-setup", action="store_true")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_opt = sub.add_parser("opt-out", help="Mark existing project as opted out of history tracking")
    p_opt.add_argument("--project", required=True)
    p_opt.set_defaults(func=cmd_opt_out)

    p_pause = sub.add_parser("history-pause", help="Pause conversation-history tracking to save tokens")
    p_pause.add_argument("--project", default=".")
    p_pause.add_argument("--global", dest="is_global", action="store_true", help="Pause globally across all projects")
    p_pause.add_argument("--gemini-home", help="Override ~/.gemini directory for testing")
    p_pause.set_defaults(func=cmd_history_pause)

    p_cont = sub.add_parser("history-continue", help="Resume conversation-history tracking and check paused gap")
    p_cont.add_argument("--project", default=".")
    p_cont.add_argument("--global", dest="is_global", action="store_true", help="Clear global pause across all projects")
    p_cont.add_argument("--gemini-home", help="Override ~/.gemini directory for testing")
    p_cont.set_defaults(func=cmd_history_continue)

    p_app = sub.add_parser("append-turn", help="Append a new turn and rebuild Priority Index")
    p_app.add_argument("--file", required=True)
    p_app.add_argument("--input")
    p_app.add_argument("--input-file")
    p_app.add_argument("--output")
    p_app.add_argument("--output-file")
    p_app.add_argument("--points-json")
    p_app.add_argument("--points-file")
    p_app.add_argument("--timestamp")
    p_app.set_defaults(func=cmd_append_turn)

    p_sync = sub.add_parser("sync-index", help="Rebuild Priority Index from Turn-by-Turn Log")
    p_sync.add_argument("--file", required=True)
    p_sync.set_defaults(func=cmd_sync_index)

    p_val = sub.add_parser("validate", help="Validate conversation_history file structure and rules")
    p_val.add_argument("--file", required=True)
    p_val.set_defaults(func=cmd_validate)

    p_inst = sub.add_parser("install-project", help="Install portable .agents plugin into project")
    p_inst.add_argument("--project", required=True)
    p_inst.add_argument("--history-path", default=None)
    p_inst.set_defaults(func=cmd_install_project)

    p_bf = sub.add_parser("backfill-scan", help="Scan local transcripts & git commits for missed work")
    p_bf.add_argument("--project", required=True)
    p_bf.add_argument("--since")
    p_bf.add_argument("--gemini-home")
    p_bf.add_argument("--max-sessions", type=int, default=10)
    p_bf.set_defaults(func=cmd_backfill_scan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
