# Conversation History Protocol

At the start of every session in a project, ensure you follow the `conversation-history` skill:

1. **Locate & Read First:** Run or check `conversation-history` startup discovery (`history_tool.py locate --project "<workspace>"`, or inspect `.agents/conversation-history.json` and scan for `<!-- AGY-CONVERSATION-HISTORY:v1 -->`).
   - If found: Read the **Priority Index** (`P1` -> `P2` -> `P3`) before making edits or decisions, and check for unrecorded drift/missed sessions.
   - If `opted_out`: Proceed normally without nagging.
   - If missing in a **new project**: Ask whether to create `<Workspace>_conversation_history.md` (e.g., `Collarms_conversation_history.md`) and where inside the project folder to place it.
   - If missing in an **existing project**: Ask whether (a) a history file already exists elsewhere and should be placed in a known project path, or (b) it never had one—in which case generate it from any available conversation, or ask the user to obtain it from whoever holds the full conversation (or opt out).
2. **Record Every Substantive Turn:** After every meaningful user input or successful AI output (skipping trivial greetings/acks or aborted errors), append the next sequential `Turn N` via `history_tool.py append-turn`:
   - Include `User Input`, `AI Output` (for code: explain what it is meant to do, its architecture, and key files/design—**never** dump raw source code), and **multiple `Priority Points`** (`P1` rules, `P2` architecture/workflow/preferences/mistakes, `P3` verified outcomes/current state, `P4` archive context).
   - Never record secrets, tokens, or passwords.
