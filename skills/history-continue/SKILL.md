---
name: history-continue
description: >-
  Resume conversation-history tracking, reload the saved Priority Index, and ask whether
  to backfill any missed turns from the paused gap. Trigger: /history-continue
---

# Continue Conversation History (`/history-continue`)

Resume `conversation-history` tracking after a `/history-pause`:

1. Run:
   ```bash
   python3 ~/.gemini/config/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py history-continue --project "<workspace_root>"
   ```
   *(Use `.agents/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py` if running from a portable project setup; add `--global` if resuming a global pause.)*
2. If `history_path` exists, read its **Priority Index** (`P1` -> `P2` -> `P3`) so you remember all rules, architecture, preferences, mistakes, and current state from before the pause.
3. Check `pause_gap_drift.has_drift` in the command output:
   - If `true`, **ask the user** whether they want to backfill the turns/commits from the paused gap into the history file (using `backfill-scan` or conversation text) or skip the gap and only record new turns from here onward.
   - If `false`, confirm that history tracking is active again and record following substantive turns as the very last step.
