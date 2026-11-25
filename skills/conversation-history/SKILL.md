---
name: conversation-history
description: >-
  Persistent, portable, priority-ranked project conversation history stored in a unique
  `conversation_history` file inside each project. Use at the start of every project session
  to check/load history or guide missing-file setup, after every meaningful user input or
  successful AI output to record turns with multi-priority points (P1-P4) and architecture-level
  summaries (never raw code), and whenever catching up or backfilling work done without the skill.
---

# Conversation History Skill

Maintains a single, uniquely marked `conversation_history.md` file (or user-chosen path inside the project) so any AI assistant—on this machine, a new computer, or a teammate's setup—immediately understands the full history and respects rules, architecture, preferences, and past mistakes.

Use the helper script [`history_tool.py`](./scripts/history_tool.py) (checking `.agents/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py` in the workspace first, or `~/.gemini/config/plugins/conversation-history/skills/conversation-history/scripts/history_tool.py` globally).

---

## 1. Startup Discovery Decision Tree

At the start of every session in a project (unless already completed in this conversation):

Run:
```bash
python3 <path-to>/history_tool.py locate --project "<workspace_root>"
```

Handle the returned `status`:

1. **`status == "found"`**:
   - Read the **Priority Index** section (`P1` -> `P2` -> `P3`) of `history_path` first before taking action. Consult the **Turn-by-Turn Log** whenever detailed context from specific turns is needed.
   - If `has_portable_setup` is `false`, offer to install the portable `.agents/` setup (`install-project`) so teammates and new machines get the same workflow automatically.
   - If `drift.has_drift` is `true` (new git commits or unrecorded local Antigravity sessions newer than `last_updated`), tell the user what missed activity was found and offer to backfill it (Section 4).

2. **`status == "opted_out"`**:
   - Do nothing and do not prompt again unless the user explicitly asks to enable history tracking.

3. **`status == "new_project"`** (no history file found, folder is empty/newly initialized):
   - Ask the user:
     1. Would you like to create a history file for this project?
     2. Where inside the project folder should it be placed? (Default: `suggested_filename` from `locate`, e.g. `Collarms_conversation_history.md` at project root.)
   - If yes, run `init --project "<root>" --install-setup` (or pass `--path "<chosen_relpath>"` if customized) and record Turn 1 once the first task completes.
   - If no, ask if they want to mark the project `opted-out` (`opt-out`) so future sessions don't ask again.

4. **`status == "existing_project"`** (no history file found, project already contains files):
   - Present the user with these exact choices:
     - **Case A — A history file already exists elsewhere (unknown location):** Ask the user to place/move it into a known path inside the project folder and tell you where it is; then run `install-project --project "<root>" --history-path "<relpath>"` and read it.
     - **Case B — This project never had a history file:**
       - **B1 — Past conversation is available to the user** (pasted text, exported chat, or local Antigravity transcripts): Use `init --project "<root>" --path "<chosen_relpath>" --install-setup`, then backfill the provided/discovered conversation into sequential `Turn N` entries (Section 4).
       - **B2 — Past conversation is NOT available:** Ask whether the user can obtain the conversation from whoever holds the full history; if not, ask if they want to either start a fresh `conversation_history.md` from today onward or continue without a history file (`opt-out`).

---

## 2. Recording Every Meaningful Turn

After every meaningful user input or successful AI output (skipping trivial greetings like `"ok"`/`"thanks"` or failed/aborted turns with no output):

1. **Extract multi-priority points (`P1`–`P4`)** covering every distinct point in the turn (a single turn commonly produces multiple tags—see [format-and-rubric.md](./references/format-and-rubric.md)):
   - `P1`: Hard rules ("always do...", "never do...")
   - `P2`: Architecture, workflow/approaches, user likes/dislikes, mistakes to avoid repeating
   - `P3`: Verified outcomes, completed changes, files touched & why, current state
   - `P4`: Routine context, minor Q&A, superseded/exploratory chatter
   - Use `[supersedes: Turn N]` when a point replaces an earlier rule or updates `Current State`.
2. **Summarize `AI Output` without raw code:** Describe what the code is meant to do, its architecture, module boundaries, key files/symbols, and design rationale. **Never** include raw source code fenced blocks. Never include secrets, tokens, or passwords.
3. **Append safely via `history_tool.py append-turn`** (using temp files or inline args so the Priority Index stays synced and validated):
   ```bash
   python3 <path-to>/history_tool.py append-turn \
     --file "<history_path>" \
     --input "<user input>" \
     --output "<architecture/intent summary>" \
     --points-json '[{"priority":"P1","text":"..."},{"priority":"P3","text":"..."}]'
   ```

---

## 3. Portable Project Setup

Whenever a history file is created or linked in a project, ensure `.agents/plugins/conversation-history/` and `.agents/conversation-history.json` are installed:

```bash
python3 <path-to>/history_tool.py install-project \
  --project "<workspace_root>" \
  --history-path "<relative_path_to_history_file>"
```

This creates a cross-platform `.agents/` setup (no OS-specific `hooks.json` inside the project) so any machine or teammate opening the project automatically follows this workflow.

---

## 4. Catch-Up & Backfill (Worked Without the Skill)

When a user worked on a project without the skill, obtained the skill mid-project, or `locate` reports `drift.has_drift == true`:

1. Run `backfill-scan` to inspect local Antigravity transcripts (`transcript.jsonl` / `transcript_full.jsonl` matching workspace file paths) and recent git commits:
   ```bash
   python3 <path-to>/history_tool.py backfill-scan --project "<workspace_root>"
   ```
2. Also accept any conversation text or export the user provides/pastes (including conversations requested from a teammate).
3. Distill the unrecorded exchanges (or git commit summary as fallback when no conversation log exists) into chronological `Turn N` entries—each with `User Input`, architecture-level `AI Output` (zero raw code dumps), and multi-priority `Priority Points`—and append them via `append-turn`.
4. Run `validate --file "<history_path>"` to verify sequential numbering, no raw code blocks, and no unredacted secrets.
