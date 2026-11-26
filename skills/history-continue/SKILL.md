---
name: history-continue
description: >-
  Resume conversation-history tracking, reload the saved Priority Index, and ask whether to backfill any missed turns from the paused gap.
  Trigger: /history-continue
user-invocable: true
---

# Resume Conversation History (`/history-continue`)

Resume `conversation-history` tracking, reload the project's saved memory, and check if anything happened during the pause.

## Steps

1. Run the continue helper (add `--global` if the user paused globally):
   ```bash
   python3 <path-to>/history_tool.py history-continue --project "<workspace_root>"
   ```
2. Read the **Priority Index** (`P1` -> `P2` -> `P3`) of `history_path` so you remember all rules, architecture, preferences, mistakes, and current state from before the pause.
3. Check `pause_gap_drift.has_drift` in the command output:
   - If `true`: tell the user how many commits/sessions occurred while paused (`git_commit_count`, `unrecorded_sessions`) and **ask** whether they want you to backfill that gap now or skip it and record new turns from here onward.
   - If `false`: confirm tracking is resumed and proceed normally, recording subsequent substantive turns as the very last step.
