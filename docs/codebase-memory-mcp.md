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
| Binary | `C:\Users\ichbi\AppData\Local\Programs\codebase-memory-mcp\codebase-memory-mcp.exe` (v0.8.1, on PATH) |
| Registration | top-level `mcpServers` in `C:\Users\ichbi\.claude.json` |
| Index (persistent) | `C:\Users\ichbi\.cache\codebase-memory-mcp\C-Users-ichbi-AutoGIS.db` |
| When tools load | **Claude Code startup only** — restart after any registration change |

### Register / re-register (the supported command)

```powershell
# `claude` is the bundled CLI, e.g.:
#   C:\Users\ichbi\AppData\Local\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\<ver>\claude.exe
claude mcp add --scope user codebase-memory-mcp `
  "C:\Users\ichbi\AppData\Local\Programs\codebase-memory-mcp\codebase-memory-mcp.exe"
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
