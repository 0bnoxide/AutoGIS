# AutoGIS — Claude Code session guide

## Codebase memory

The codebase-memory MCP server is **wired at USER scope** (stdio), not via a repo
file. The binary lives at
`C:\Users\ichbi\AppData\Local\Programs\codebase-memory-mcp\codebase-memory-mcp.exe`
and is registered in `~/.claude.json` (`claude mcp add --scope user`). There is no
project `.mcp.json` — a previous one pointed at a non-existent npm package and was
removed. The persistent index lives at
`~/.cache/codebase-memory-mcp/C-Users-ichbi-AutoGIS.db`.

> **If the `mcp__codebase-memory-mcp__*` tools are missing this session:** the
> registration was likely wiped, or you just (re)registered and haven't restarted —
> MCP servers load at **startup only**. See `docs/codebase-memory-mcp.md` for the
> verified fix and the running deviation log. Until restarted, fall back to
> Grep/Glob/Read.

**At the start of every session (when the tools are present):**
1. Call `mcp__codebase-memory-mcp__index_status` (project `C-Users-ichbi-AutoGIS`).
2. If `status` is not `"ready"` or `nodes` looks stale (e.g. missing recent files),
   run `mcp__codebase-memory-mcp__detect_changes` then
   `mcp__codebase-memory-mcp__index_repository` before querying. (Markdown/ADRs are
   not indexed — the indexer scans Python only, so a docs-only change won't move the
   node count.)

Use the `/graph` skill to query the index. Key tools:

| Question type | Tool |
|---|---|
| Find a symbol / module / concept | `search_graph` |
| Find code by keyword or pattern | `search_code` |
| How does A call / depend on B? | `trace_path` |
| Layer / module overview | `get_architecture` |
| Fetch a specific snippet | `get_code_snippet` |

Fall back to Grep / Glob / Read / the Explore subagent when tools are absent
(web/cloud sessions) or when the index hasn't caught a very recent change.

---

## Project layout (quick reference)

| Path | Purpose |
|------|---------|
| `autogis/core/harvest/` | Attachment harvester — arcpy-free |
| `autogis/core/envmon/` | Environmental monitoring tools (23 modules) |
| `autogis/core/common/` | Shared config, QA, logging, seen-index |
| `autogis/adapters/` | CLI (`cli.py`), `.pyt` toolbox, toolbox_core seam |
| `autogis/runtime/` | ArcGIS Pro session providers + capability guard |
| `autogis/config/` | Site configs, parser profiles, screening levels, figure specs |
| `tests/` | 151 arcpy-free tests; run with `python -m pytest -q` |

## Key invariants

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present.
- Tools 1, 9, 10 are headless (openpyxl only). Tools 2-8 are LOCAL (arcpy) — CLI
  commands for 2-8 guard then redirect to the `.pyt` toolbox.
- `HarvestConfig` is canonical in `core/common/config.py`; re-exported from
  `core/harvest/models.py` for back-compat.
- Screening levels and the H281 parser profile are pre-production stubs — do not
  remove DRAFT banners or `_TODO` markers until verified against real data.

## Worktrees & session coordination

- **Worktrees live under `.claude/worktrees/`** (gitignored), not the
  `superpowers:using-git-worktrees` default `.worktrees/`. Prefer the native
  `EnterWorktree` tool (Step 1a); if you ever fall back to `git worktree add`,
  target `.claude/worktrees/<branch>`.
- **One shared claim registry.** The session-coordination registry
  (`.claude/coordination/claims.json`, gitignored) always lives at the **main**
  working tree's root. `registry.claims_path()` resolves it via
  `git rev-parse --git-common-dir`, so a worktree session and the main checkout
  share one registry — never a per-worktree copy.
- **`EnterWorktree` mid-session doesn't fire `SessionStart`.** The auto-claim
  only runs at session start, so after switching into a worktree mid-session the
  session still holds its *old* branch/worktree claims (the PreToolUse heartbeat
  keeps refreshing them) and has *not* claimed the new branch. Left as-is this
  both (a) falsely locks the old branch against other sessions and (b) can make
  the hook deny you committing to the branch you just moved to (if another
  session claimed it). After `EnterWorktree`, **release the old claims, then
  claim the new** — using the canonical coordination dir at the main root:

  ```bash
  COORD="$(git rev-parse --git-common-dir)/.."   # main tree root
  python "$COORD/.claude/coordination/coord_cli.py" release --session "$SESSION_ID" --kind branch   --value <old-branch>
  python "$COORD/.claude/coordination/coord_cli.py" release --session "$SESSION_ID" --kind worktree --value <old-worktree-abspath>
  python "$COORD/.claude/coordination/coord_cli.py" claim   --session "$SESSION_ID" --kind branch   --value <new-branch>
  python "$COORD/.claude/coordination/coord_cli.py" claim   --session "$SESSION_ID" --kind worktree --value <new-worktree-abspath>
  ```
