# Format & Priority Rubric Reference

## Multi-Priority Classification Rubric

Each turn (`User Input` + `AI Output`) should be broken down into **every distinct point discussed**, with each point tagged independently as `P1`, `P2`, `P3`, or `P4`:

| Tag | Category | When to Use | Example |
| :--- | :--- | :--- | :--- |
| `P1` | **Hard Rules** | Explicit "always do X", "never do Y", non-negotiable constraints | `- [P1] Never store raw source code blocks in conversation_history.md; summarize intent and architecture only.` |
| `P2` | **Architecture, Workflow, Preferences & Mistakes** | System design, chosen patterns/workflows, what the user loved/hated/disliked, and mistakes to avoid repeating | `- [P2] **Architecture:** Split backend into FastAPI service layer and Qt QML client communicating via WebSockets.`<br>`- [P2] **Mistake to Avoid:** Do not poll ros2_control at 100Hz on the GUI thread; it caused slider stutter.`<br>`- [P2] **Loved:** User liked the compact two-lane timeline UI.` |
| `P3` | **Verified Outcomes & Current State** | Completed tasks, passing tests, verified decisions, files created/modified and why, current project status | `- [P3] **Completed:** Implemented JWT auth middleware in app/auth.py and verified unit tests pass.`<br>`- [P3] **Current State:** Ready to wire login screen to /api/token.` |
| `P4` | **Archive Context** | Minor clarifications, rejected brainstorm branches, routine status checks, general Q&A | `- [P4] Explained difference between REST and gRPC before user chose WebSockets.` |

### Updating / Retiring Old Index Items (`[supersedes: Turn N]`)
When a later turn changes an earlier rule, architecture decision, or current state, tag the new point with `[supersedes: Turn <N>]` (or `[supersedes: Turn <N> all]` to retire all `P1`–`P3` points from Turn N):

```markdown
- `[P1]` [supersedes: Turn 2] Always use WebSockets instead of HTTP polling for live telemetry.
- `[P3]` [supersedes: Turn 4] **Current State:** Migration to SQLite WAL mode is complete and verified.
```

`history_tool.py sync-index` automatically removes superseded items from the top **Priority Index** while keeping the original Turn intact in the **Turn-by-Turn Log**.

---

## Writing Good `AI Output` Entries (No Raw Code Rule)

`AI Output` must explain **what was done, what the code is meant to do, its architecture, and affected files/symbols**—never paste raw source code blocks.

### Good Example
> Implemented persistent token refresh in `app/auth/session.py` (`SessionManager.refresh_if_needed`). The flow intercepts HTTP 401 responses once, acquires a per-user asyncio lock so concurrent requests share a single refresh call, updates the encrypted keyring store, and retries the original request. Added unit coverage in `tests/test_session.py` covering concurrent refresh races and expired refresh tokens.

### Bad Example (Rejected by `history_tool.py`)
> Added the following code to `app/auth/session.py`:
> ```python
> async def refresh_if_needed(self):
>     ...
> ```
