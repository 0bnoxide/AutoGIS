# codebase-memory-mcp

Provides a persistent memory graph of this codebase for Claude Code sessions.
Source: https://github.com/DeusData/codebase-memory-mcp

This server is **local-only and wired at user scope on your own machine**, where
trust is implicit and the graph persists across sessions. It is deliberately NOT
wired into the repo (a committed `.mcp.json`/`settings.json` granting itself the
right to run a binary is not auto-trusted by the harness — see the history note at
the bottom).

---

## Verified working setup (Windows) — confirmed 2026-06-24

This is the canonical reference. If a session can't see the
`mcp__codebase-memory-mcp__*` tools, reconcile against these four facts before
anything else.

| Thing | Correct value |
|---|---|
| Binary | `C:\Users\ichbi\AppData\Roaming\npm\node_modules\codebase-memory-mcp\bin\codebase-memory-mcp.exe` (v0.8.1, npm-global install; on PATH as `codebase-memory-mcp`) |
| Registration | top-level `mcpServers` in `C:\Users\ichbi\.claude.json` |
| Index (persistent) | `C:\Users\ichbi\.cache\codebase-memory-mcp\C-Users-ichbi-AutoGIS.db` |
| When tools load | **Claude Code startup only** — restart after any registration change |

### Register / re-register (the supported command)

```powershell
# `claude` is the bundled CLI, e.g.:
#   C:\Users\ichbi\AppData\Local\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\<ver>\claude.exe
claude mcp add --scope user codebase-memory-mcp `
  "C:\Users\ichbi\AppData\Roaming\npm\node_modules\codebase-memory-mcp\bin\codebase-memory-mcp.exe"
# (the binary is also on PATH, so `claude mcp add --scope user codebase-memory-mcp codebase-memory-mcp` works too)
```

> Do **not** add `mcpServers` to `~/.claude/settings.json` — this Claude Code
> version rejects that key there. User-scope MCP servers belong in `~/.claude.json`,
> which `claude mcp add --scope user` writes for you.

### Verify

```powershell
claude mcp list      # expect: codebase-memory-mcp ... ✔ Connected
```

Then **restart Claude Code** and, in the new session, call
`mcp__codebase-memory-mcp__index_status`. If stale, run `detect_changes` then
`index_repository`. Markdown (`docs/`, ADRs) is not indexed — the indexer scans
Python only.

---

## Known deviations (recognise these fast)

1. **Repo `.mcp.json` → npm 404.** A project `.mcp.json` declared the server as
   `npx @modelcontextprotocol/server-codebase-memory`. That package does not exist
   (registry returns 404), so the server never started; and project-scope `.mcp.json`
   servers aren't auto-trusted anyway (`hasTrustDialogAccepted: false`). Removed.
2. **User-scope registration wiped.** If `~/.claude.json` loses its `mcpServers`
   entry, the tools silently disappear. Re-add with the command above.
3. **UI server ≠ tool wiring.** Running `codebase-memory-mcp --ui=true --port=9749`
   starts a standalone browser UI; it does **not** register tools into the agent
   (only the stdio wiring does). A leftover UI process can linger for hours holding a
   large memory budget. Find/stop it with:
   ```powershell
   Get-Process | Where-Object { $_.Name -like "*codebase*" }   # inspect
   # Stop-Process -Id <pid>   # only if it's a stray manual UI server
   ```
4. **Stale node count after docs-only changes is expected** — markdown isn't indexed.

---

## Setup & Deviation Log

Append a dated entry whenever the MCP wiring or index setup changes, or a deviation
is found and fixed. Newest first.

### 2026-06-30 — third defect: `index_repository(mode:"full")` silently skips cache-poisoned files
- **Symptom:** even after PR #91 fixed root causes 1–2 below, the graph was **still** missing the
  5 PR #95 modules (`export_comparison_excel`, `ingest_reviewer_comments`, `job_queue`,
  `soil_interval_selector`, `well_trend_charts`).
- **Evidence (`~/.cache/codebase-memory-mcp/last-index.log`, timestamped — no interpretation
  needed):** **9 consecutive** SessionStart-triggered `index_repository(mode:"full")` runs from
  22:05–22:29 all returned an **identical 5446 nodes / 15961 edges**, even though `main`
  (`5d1d1ea`, committed 07:16) had contained those modules for **~13 h**. The count only moved to
  **5654 / 16869** at 22:31:43 — a manual `delete_project` + fresh `index_repository` (which has no
  cache to consult).
- **Root cause 4 (distinct from 1–3):** `mode:"full"` means *full scope of edge types* (all files
  \+ similarity/semantic), **not** "rebuild from scratch." It still consults the per-file
  content-hash incremental cache — the very mechanism that *avoids full rebuilds* — and skips any
  file whose hash matches. That cache was **poisoned** for the 5 modules (hash recorded but nodes
  never persisted — most likely a partial/interrupted index during the busy multi-PR merge
  window), so every subsequent "full" reindex skipped them silently. RC1 (dead binary path) and
  RC2 (missing harvest pkg) do not touch this path.
- **Fix / workaround:** `delete_project` then `index_repository` clears the cache and forces a true
  rebuild. **Verified:** `search_graph` now returns real Function/Class nodes for all 5; File-node
  parity `autogis` 126/126, `tests` 127/127, `envmon` 86/86, worktree contamination 0; index stable
  at 5654/16869.
- **Not fixable in-repo:** the cache logic lives in the external compiled binary
  (`bin/codebase-memory-mcp.exe`). Optional in-repo hardening (**not built** — YAGNI unless this
  recurs): a SessionStart *parity guard* comparing `git ls-files '*.py'` count to the indexed `.py`
  File-node count and forcing `delete_project` + rebuild on mismatch.
- **Caveat for future sessions:** do **not** treat unchanged or rising `mode:"full"` node counts as
  proof of freshness — they aren't (this corrects the earlier "full rebuild every session"
  assumption). Verify freshness by **parity** (indexed `.py` File nodes vs `git ls-files '*.py'`) or
  by `search_graph` returning real symbol nodes for recently-merged modules.

### 2026-06-30 — poisoned incremental cache: files permanently un-indexed despite being on disk
- **Symptom:** 5 envmon modules from the PR #95 batch (`export_comparison_excel`,
  `ingest_reviewer_comments`, `job_queue`, `soil_interval_selector`, `well_trend_charts`)
  had **zero graph nodes** in the canonical index even though they were present on disk,
  unchanged, and parsed fine (a clean-room build of identical content produced full
  function/class nodes for all 5). `autogis/core/harvest/` was separately missing —
  see the entry below, a different root cause (no `__init__.py` at index time).
- **Root cause, confirmed by direct reproduction:** the `file_hashes` change-detection
  table has a `sha256` column, but it is **always empty** in v0.8.1 (checked ~90 rows
  across both `fast` and `full` mode) — change detection is **mtime-based**, not
  hash-based. If a file's `mtime_ns` is cached but its nodes are (for any reason) zero,
  every later `index_repository` call — **any mode** — sees "mtime unchanged → already
  indexed" and skips it **permanently**. This is a genuine bug, not simple staleness: a
  competing theory (files were just "latent," not yet re-indexed since the PR #95 merge,
  and a plain re-run would have picked them up) was empirically **refuted** — see repro
  below.
- **Reproduced on a disposable throwaway project** (never on canonical): indexed
  `autogis/core/envmon/` alone (788 nodes), manually deleted just `well_trend_charts.py`'s
  12 nodes via direct sqlite while leaving its `file_hashes` row/mtime untouched (the file
  itself was never touched on disk), then ran a plain incremental
  `index_repository(mode="full")` — no `delete_project`. Result: node count stayed at 776
  (788−12); `search_graph` confirmed zero nodes for that file. A repeated incremental call
  would produce the same result indefinitely.
- **Fix:** `delete_project` then `index_repository(mode="full")` via the MCP tools — a
  full rebuild through the live server. **Do not hand-edit `nodes`/`file_hashes` via
  sqlite against a project you care about** — the server holds the DB open (WAL-mode),
  and out-of-band mutation risks the same class of inconsistency that likely caused the
  poisoning in the first place. (The raw-SQL repro above was only run against a disposable
  scratch project, with explicit user sign-off, specifically because of this risk.) A full
  rebuild also catches any other files poisoned the same way that haven't been noticed yet
  — surgical single-row deletion doesn't. Cost is trivial for this repo's size (~5-10s).
  Canonical index went 4990→5654 nodes, 13492→16869 edges after the rebuild, matching a
  clean-room reference build.
- **Still unknown:** what causes a file to get its mtime cached without nodes in the first
  place (binary is compiled — can't inspect the extraction path). If it recurs, don't
  re-diagnose the mechanism from scratch — go straight to `delete_project` + full reindex.

### 2026-06-30 — stale index + harvest unindexed: SessionStart hook pointed at a dead binary
- **Symptoms (long-standing):** the knowledge graph was chronically stale, and
  `autogis/core/harvest/` (Tool 1, the harvester) had **zero node coverage**.
- **Root cause 1 — stale index:** `.claude/hooks/session-start.sh` hardcoded
  `CBM=.../AppData/Local/Programs/codebase-memory-mcp/...exe`, but the registered binary is
  the **npm-global** install (`.../AppData/Roaming/npm/node_modules/codebase-memory-mcp/bin/...exe`).
  The `[ -x "$CBM" ]` guard failed every session, so the refresh **silently no-op'd** — all
  output went to `/dev/null`. The index only refreshed when an agent manually ran
  `index_repository`. **Fix:** resolve via `command -v codebase-memory-mcp` (PATH) and **log the
  outcome** (status + node/edge counts) to `~/.cache/codebase-memory-mcp/last-index.log` so the
  silent-failure class is gone. Full index measured ~0.5s → stays synchronous.
- **Root cause 2 — harvest unindexed:** `autogis/core/harvest/` had no `__init__.py` (the only
  `core` subpackage missing one). The indexer only walks regular packages, so it skipped the
  harvester source (a PEP 420 namespace package) while still indexing its tests. **Why it was
  missing:** `.gitignore` had an unanchored `harvest/` (intended for the harvester's *output*
  dir) that also matched the *source* package, so a package `__init__.py` was un-committable —
  git silently ignored any attempt to add one. **Fix (two parts):** anchor the ignore to
  `/harvest/` so it only matches a root-level output dir, AND add
  `autogis/core/harvest/__init__.py`. **Verified:** a fresh index went 0 → **48** harvest source
  nodes (the `harvest()` orchestrator alone has in-degree 17). Note: the indexer does **not**
  honor this `.gitignore` rule — `__init__.py` is the sole indexing gate; the ignore fix is only
  about making the package committable.
- **Root cause 3 — "the monitor":** the background git-change watcher was off
  (`auto_index=false`). **Enabled** it (`config set auto_index true`; activates on next server
  start). Note: `detect_changes` is a working-tree diff/impact tool, **not** an index-freshness
  check — don't use it to judge staleness.
- **Verified via** an isolated worktree indexed as a throwaway project (the main working tree was
  claimed by a parallel session at the time). Fixes are on branch
  `worktree-fix-codebase-index-2026-06-30`.

### 2026-06-30 — cloud/web sessions can't get these tools (current platform limit)
- **Question:** can a cloud (`CLAUDE_CODE_REMOTE=true`) Claude Code session — e.g. the
  nightly remote-trigger agent — use the `mcp__codebase-memory-mcp__*` tools? The
  graph-codebase-navigator agent kept reporting it could only fall back to grep.
- **Answer: no, by no repo- or config-side mechanism reachable from here.** Tiered by
  certainty:
  - **Proven dead (firsthand, commit `5624f90`):** a repo `.mcp.json` +
    `enabledMcpjsonServers` is *ignored* by the web harness — it resolved
    `enabledMcpjsonServers=[]` / `hasTrustDialogAccepted=false`, tools never registered.
    The old web wiring (`c64735c`) was deleted *because* of this, not by accident.
  - **Established (transport mismatch):** the supported cloud-MCP channel is the remote
    trigger's `mcp_connections`, which accepts **HTTP-transport servers only**.
    codebase-memory-mcp is **stdio-only** (`--ui --port` is a viz UI, not an MCP
    transport), so it cannot be provisioned there.
  - **Inferred (timing):** a SessionStart-hook `claude mcp add --scope user` can't help
    the session that's currently booting — MCP servers load at **startup**, before the
    hook's registration lands. This only rules out an unsupported hack.
- **Probe note:** a throwaway remote trigger was used to test this empirically. It could
  not be made to clone the repo at all (the code-source attachment is bound to the
  environment/routine via the claude.ai UI, **not** settable through the trigger
  create/update API), so the hook never ran in the probe. Moot, because the hack's
  best case (inferred timing) is unusable anyway. See issue #89 for the raw probe output.
- **Not a permanent law:** would become possible if cloud MCP gains stdio support, or via
  host-level config that can't be set from the repo. Until then, cloud sessions correctly
  fall back to Grep/Glob/Read (graph-codebase-navigator already handles this).
- **Local wiring untouched** — the Windows user-scope setup above still works and was not
  modified by this investigation.

### 2026-06-24 — restored user-scope wiring; removed broken `.mcp.json`
- **Symptom:** `mcp__codebase-memory-mcp__*` tools absent; `index_status` errored
  "No such tool available".
- **Root cause:** user-scope `mcpServers` in `~/.claude.json` had been wiped; the
  repo `.mcp.json` pointed at a non-existent npm package (404); a prior session had
  conflated a manual `--ui=true --port=9749` UI server (PID still running ~6h, from
  the Haiku handoff) with the agent's stdio tool wiring.
- **Fix:** `claude mcp add --scope user codebase-memory-mcp <exe>` →
  `claude mcp list` shows `✔ Connected`. Deleted the tracked `.mcp.json`. Corrected
  CLAUDE.md and this doc (the old version wrongly told you to put `mcpServers` in
  `~/.claude/settings.json`, and gave macOS-only `/usr/local/bin` instructions).
- **Binary v0.8.1; index DB present at `~/.cache/...` (last indexed 2026-06-23, refresh after restart).**
- **Action left to user:** restart Claude Code to load the server; commit the
  `.mcp.json` deletion and these doc/CLAUDE.md edits.
