---
name: history-pause
description: >-
  Pause conversation-history tracking for the current project (or globally with --global)
  to save tokens. Trigger: /history-pause
---

# Pause Conversation History (`/history-pause`)

Immediately pause `conversation-history` tracking so no history reads, `history_tool.py` calls, or turn writes happen until `/history-continue` is run.

1. Run:
   ```bash
   python3 ~/.gemini/config/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py history-pause --project "<workspace_root>"
   ```
   *(If the project uses the portable `.agents/` copy and no global plugin is installed, run `.agents/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py` instead. Add `--global` if the user asks to pause all projects.)*
2. Confirm briefly to the user that conversation history tracking is paused (per-project or global) and stop all tracking activity.
