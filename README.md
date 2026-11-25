# Antigravity Conversation History Plugin

Persistent, portable, priority-ranked conversation history for **Antigravity** projects. Stores every turn inside the project itself (`<Workspace>_conversation_history.md`, e.g., `Collarms_conversation_history.md`, or a custom project path) so any AI assistant—on your machine, a new computer, or a teammate's setup—immediately understands the full history without drowning in unimportant chatter.

## Features

- **Unique Project Detection:** Uses `<!-- AGY-CONVERSATION-HISTORY:v1 -->` and `.agents/conversation-history.json` so the skill finds the history file anywhere in the project.
- **Smart Startup Tree:**
  - **Found:** Reads the **Priority Index** (`P1` -> `P2` -> `P3`) first and checks for drift (new git commits or unrecorded local sessions).
  - **Missing (New Project):** Asks whether to create `<Workspace>_conversation_history.md` (e.g., `Collarms_conversation_history.md`) and where in the project folder to place it.
  - **Missing (Existing Project):** Asks whether a file exists elsewhere to place in a known path, or if the project never had one (generate from available conversation, ask owner, or opt out).
- **Multi-Priority Remembering (`P1`–`P4`):**
  - `P1` — Hard rules (`always` / `never`)
  - `P2` — Architecture, workflow, user likes/dislikes, mistakes to avoid
  - `P3` — Verified outcomes, files changed, current state
  - `P4` — Full turn-by-turn archive context
  - Supports `[supersedes: Turn N]` to retire outdated rules/state from the top index while keeping every turn in the log.
- **No Raw Code Dumps & Secret Redaction:** Summarizes what code is meant to do and its architecture in `AI Output`, rejects raw code blocks, and redacts API keys/tokens/passwords in both `User Input` and `AI Output`.
- **Portable Across Machines:** Installs a self-contained `.agents/plugins/conversation-history/` copy into each opted-in project.
- **Catch-Up / Backfill:** Recovers missed history from local Antigravity `transcript.jsonl` / `transcript_full.jsonl` logs, git history, or pasted conversations.

---

## Install on Any Device

### Option 1: Direct Clone (Recommended — Linux / macOS)
```bash
git clone https://github.com/m7mod22/agy-conversation-history.git ~/.gemini/config/plugins/conversation-history
```

### Option 2: Clone Anywhere & Run Installer
```bash
git clone https://github.com/m7mod22/agy-conversation-history.git
cd agy-conversation-history
bash install.sh
```

### Option 3: Windows (PowerShell)
```powershell
git clone https://github.com/m7mod22/agy-conversation-history.git "$env:USERPROFILE\.gemini\config\plugins\conversation-history"
```
*(Note: On Windows, the portable project setup and `rules/AGENTS.md` + `history_tool.py` work out of the box; the optional `hooks.json` `sh -c` lifecycle hooks are Unix-oriented.)*

---

## Verify Installation

```bash
python3 -m unittest discover -s ~/.gemini/config/plugins/conversation-history/tests -v
```

---

## CLI Reference (`history_tool.py`)

```bash
TOOL=~/.gemini/config/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py

python3 "$TOOL" locate --project "."
python3 "$TOOL" init --project "." --path "conversation_history.md" --install-setup
python3 "$TOOL" install-project --project "." --history-path "conversation_history.md"
python3 "$TOOL" opt-out --project "."
python3 "$TOOL" append-turn --file "conversation_history.md" --input "..." --output "..." --points-json '[{"priority":"P1","text":"..."}]'
python3 "$TOOL" sync-index --file "conversation_history.md"
python3 "$TOOL" validate --file "conversation_history.md"
python3 "$TOOL" backfill-scan --project "."
```
