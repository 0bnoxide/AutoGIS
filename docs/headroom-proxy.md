# headroom — removed 2026-07-09 (postmortem)

`headroom-ai` (context-compression proxy + memory layer, https://headroom-docs.vercel.app/docs/)
was trialed on this machine and **removed**. This is the "why, and what we
learned" record so nobody re-attempts it blindly. It is no longer installed,
wired, or referenced by the repo.

## Why removed — it failed both things it was kept for

Tested `headroom-ai` 0.31.0 (latest) in an isolated venv against a running
0.27.0 service on 2026-07-09:

1. **Always-on routing breaks `/remote`.** The proxy only forwards `/v1/*`
   paths — it returns **404 on every `/api/*` path** (Claude Code remote
   control/comms ride on `/api/*`). Confirmed identical in 0.27.0 **and**
   0.31.0: `/v1/organizations` → 401 (forwarded to upstream), `/api/*` → 404
   (dropped). This is architectural, not a version bug — no upgrade fixes it, so
   `ANTHROPIC_BASE_URL`-based always-on routing can't coexist with `/remote`.
2. **`cache` mode saves ~0 tokens by design.** Across 1122 real requests the
   ledger showed `requests_compressed: 0`, `total_tokens_removed: 0`,
   `prefix_frozen: 1004`. Reversible CCR (`--mode cache`) only prefix-freezes
   context for provider prompt-cache *cost* benefit; it does **not** reduce the
   token count the model sees. Token reduction requires `--mode token` (lossy
   Kompress) — which we declined for reversibility.

Net: always-on cache-mode headroom broke `/remote` and reduced zero tokens.

## Root cause of the install churn (fix if you ever re-add it)

The SessionStart hook `pip install`ed headroom on **every** session start. With
5+ concurrent sessions their hooks raced the same `site-packages`, corrupting
the install (deleted `headroom.exe`, three stacked `dist-info` dirs). Any repair
got re-corrupted until the hook line was removed. **Lesson: never put an
unpinned `pip install` of a heavy package in a hook that many concurrent
sessions run** — install once, out-of-band, or guard with a marker.

## Gotchas that cost real time (recognise these fast if reviving)

- **`headroom install apply` is broken on Windows.** `persistent-service` builds
  a malformed `sc.exe` command (unquoted `binPath=` with spaces → exit **1639**)
  and rolls back completely; `persistent-task` needs admin. We used NSSM instead
  (`nssm install HeadroomProxy … proxy --mode cache …`).
- **A SYSTEM-run service needs profile overrides** or `--learn` scans SYSTEM's
  empty `~/.claude/projects`: `AppEnvironmentExtra USERPROFILE=…`,
  `HEADROOM_MEMORY_DB_PATH=…`, `HEADROOM_LOG_FILE=…` — or run the service as your
  user via `nssm edit` → *Log on*.
- **#1072 — `--learn` writes `CLAUDE.local.md`, not tracked `CLAUDE.md`** (issue
  #1072). That file isn't gitignored by default, so `?? CLAUDE.local.md` dirties
  the main tree and silently blocks SessionStart's clean-only ff-pull → main
  drift. The `CLAUDE.local.md` `.gitignore` line (PR #206) is **kept** even after
  removal — it's good generic Claude Code hygiene.
- **Never paste `<!-- headroom:learn -->` markers into tracked `CLAUDE.md`** —
  `writer.py:_migrate_legacy_block` will rewrite/`unlink()` it out-of-band,
  bypassing the read-only-main hook.

## What removal did (2026-07-09)

- Stripped the headroom `pip install`, model pre-warm, `~/.headroom` mkdir, and
  `HEADROOM_*` env exports from `.claude/hooks/session-start.sh` (kept the
  codebase-memory refresh, main ff-pull, project-dep install, and the
  `AUTOGIS_SESSION_ID` coordination export).
- Dropped the headroom-specific `.gitignore` lines (`.headroom/`,
  `headroom_memory.db`, `HEADROOM_MEMORY.md`); kept `CLAUDE.local.md`.
- Unregistered the `headroom` MCP server from `~/.claude.json`.
- Removed the NSSM `HeadroomProxy` service, uninstalled the package, deleted
  `~/.headroom` (out-of-band admin steps — not repo changes).
