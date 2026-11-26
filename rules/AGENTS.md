# Conversation History Protocol

Follow the `conversation-history` skill in this strict order—**never** record a turn before the task is finished:

1. **Paused Check & Unique Commands:**
   - If the project (or global state) is **`paused`** (`history_tool.py locate` or `.agents/conversation-history.json` has `"status": "paused"`), **do nothing**—do not read, run `history_tool.py`, or write anything until the user says `history-continue`.
   - **`history-pause`** (or `history-pause --global`): Run `history_tool.py history-pause` and immediately stop all tracking to save tokens.
   - **`history-continue`** (or `history-continue --global`): Run `history_tool.py history-continue`, read the saved **Priority Index**, ask the user whether to backfill if `pause_gap_drift.has_drift` is true, and resume final-step recording.
2. **Start of Session (Read-Only):** Locate the project's `<!-- AGY-CONVERSATION-HISTORY:v1 -->` file (`history_tool.py locate --project "<workspace>"` or `.agents/conversation-history.json`).
   - If found: Read the **Priority Index** (`P1` -> `P2` -> `P3`) quietly so you follow all rules and context, and note any unrecorded drift. **Do not write to the history file yet.**
   - If `opted_out`: Proceed normally without nagging.
   - If missing in a **new project**: Ask whether to create `<Workspace>_conversation_history.md` (e.g., `Collarms_conversation_history.md`) and where inside the project folder to place it.
   - If missing in an **existing project**: Ask whether (a) a history file already exists elsewhere and should be placed in a known project path, or (b) it never had one—in which case generate it from any available conversation, or ask the user to obtain it from whoever holds the full conversation (or opt out).
3. **Do the User's Task First:** Complete all research, edits, commands, and verification for the user's request before recording anything.
4. **Very Last Step (Record After Everything Finishes):** Only after all work for the current turn is completely finished and verified (skipping trivial greetings/acks or aborted errors), append `Turn N` via `history_tool.py append-turn`:
   - Include `User Input`, `AI Output` (for code: explain what it is meant to do, its architecture, and key files/design—**never** dump raw source code), and **multiple `Priority Points`** (`P1` rules, `P2` architecture/workflow/preferences/mistakes, `P3` verified outcomes/current state, `P4` archive context).
   - Never record secrets, tokens, or passwords.
