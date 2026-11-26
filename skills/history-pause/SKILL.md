---
name: history-pause
description: >-
  Pause conversation-history tracking for the current project (or globally with --global) to save tokens.
  Trigger: /history-pause
user-invocable: true
---

# Pause Conversation History (`/history-pause`)

Immediately pause `conversation-history` tracking so it consumes zero extra tokens until `/history-continue` is called.

## Steps

1. Run the pause helper (checking `.agents/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py` first, or `~/.gemini/config/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py`):
   - For the current project (default):
     ```bash
     python3 <path-to>/history_tool.py history-pause --project "<workspace_root>"
     ```
   - If the user passed `--global` (or asked to pause globally):
     ```bash
     python3 <path-to>/history_tool.py history-pause --project "<workspace_root>" --global
     ```
2. Confirm to the user in one short line that conversation history tracking is now paused (and mention `/history-continue` to resume).
3. Do **not** read or write `<Workspace>_conversation_history.md` while paused.
