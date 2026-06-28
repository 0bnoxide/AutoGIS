# Session Coordination & Shared Knowledge — Design

**Date:** 2026-06-28
**Status:** Approved (design); pending implementation plans
**Motivation:** Repeated branch / worktree / file collisions when running parallel
Claude Code sessions (multiple VS Code windows, terminals, subagents, `/remote`
control) plus a nightly autonomous cloud agent — all against the same repo.

## Problem

Parallel sessions step on each other. Two failure modes observed in practice:

1. **Wrong-branch commits.** Subagents committed Survey123 work to
   `feat/gdb-schema-upgrade` (the main checkout's branch) instead of the isolated
   `feat/survey123-field-impl` worktree branch they were assigned. Silent until a
   PR conflict surfaced it.
2. **Stale-base divergence.** A long-running branch fell 35 commits behind `main`
   (advanced by other sessions and the nightly agent) and conflicted on merge.

Neither is a *memory* failure — both are *coordination* failures. A shared notes
store would not have prevented either. What prevents them is (a) a live record of
who owns which branch/worktree/files right now, enforced before a git/edit op, and
(b) awareness of what other sessions — including the cloud agent — already have in
flight.

### Key constraint: two coordination boundaries with different substrates

- **Local ↔ local** (VS Code windows, terminals, subagents, `/remote` — all on one
  Windows machine): a fast local file is visible to all and can be enforced by a
  hook.
- **Local ↔ cloud** (the nightly `AutoGIS Autonomous Feature Agent`, cron
  `0 9 * * *`, which implements features + opens PRs + writes `docs/adr/logs/`):
  runs **without the MCP and without access to local files**. The only surface it
  shares with local sessions is **git/GitHub**.

A single mechanism cannot span both. The design is therefore explicitly tiered.

## What already exists (and is reused, not reinvented)

- **Append-only, one-file-per-entry directories** (`memory/`, `docs/adr/logs/`):
  conflict-free by construction — two sessions never touch the same line, so they
  never merge-conflict. This is the substrate for anything git-synced.
- **`manage_adr`** (codebase-memory MCP): a *single* project-charter blob with six
  fixed sections (PURPOSE/STACK/ARCHITECTURE/PATTERNS/TRADEOFFS/PHILOSOPHY), stored
  in the MCP's local SQLite. CRUD-only — **no list/search/enumerate**, not graph-
  indexed, invisible to the cloud agent. Useful as a local session-start "current
  truth" surface; **cannot** be a per-decision searchable log.
- **The code graph** (codebase-memory MCP): indexes Python only. Has `CALLS`,
  `IMPORTS`, `USAGE` edges and hotspot fan-in — good for blast-radius analysis.
  **Markdown/ADRs are not indexed**, so `search_graph` cannot retrieve decisions.
  Absent entirely in cloud sessions.

## Architecture — "brain + reflexes," tiered by visibility

| Tier | Mechanism | Visible to | Role |
|---|---|---|---|
| 1 — Reflexes | Local registry + PreToolUse hook | Local sessions | The live lock (hard enforcement) |
| 2 — Brain | Code graph pre-flight | Local (MCP present) | Advisory blast-radius warnings |
| 3 — Cross-boundary | Append-only git-synced claims | Local **and** cloud | Cloud-reachable in-flight ledger |
| K — Knowledge | `manage_adr` (local) + `docs/adr/logs/` & `memory/` (git) | Local / both | Shared situational awareness |

### Tier 1 — Reflexes (local live lock) — *first implementation plan*

**Registry file:** `.claude/coordination/claims.json` (gitignored; local-only;
never committed). Holds a list of active claims:

```json
{
  "claims": [
    {
      "session_id": "c3ffe0ff-…",
      "kind": "branch | worktree | file_glob",
      "value": "feat/survey123-field-impl",
      "pid": 45516,
      "host": "DESKTOP-…",
      "started_at": "2026-06-28T07:30:00Z",
      "heartbeat_at": "2026-06-28T07:42:00Z",
      "ttl_sec": 1800
    }
  ]
}
```

**Registry module** (pure Python, arcpy-free): `claim()`, `release()`, `list()`,
`heartbeat()`, `reap_stale()`.

- **Atomic writes:** temp-file + `os.replace` rename; an OS-level lock file
  (`claims.json.lock`) serializes concurrent writers.
- **Stale reaping:** a claim whose `heartbeat_at` is older than `ttl_sec` is
  ignored and reaped — a crashed session auto-expires, so locks never wedge.
- **Race resolution:** writer takes the lock, re-reads, appends, releases; on a
  contested resource the second writer sees the existing live claim and backs off.

**Helper / CLI:** thin wrapper exposing `claim`/`release`/`list`/`heartbeat` so a
session (or a session-start hook) registers ownership before touching a
branch/worktree/file-set and releases on completion. Heartbeat refreshes the TTL.

**PreToolUse hook (the enforcement point):** runs on Bash git operations
(`git commit`, `git checkout -b`, `git push`) and on `Edit`/`Write`:

- **Hard-BLOCK** when:
  - committing to `main`, **or**
  - committing to a branch / editing a file matching a `file_glob` that another
    **live** session (fresh heartbeat) claims.
- **Advisory WARN** (Tier 2, best-effort) when graph blast-radius is high — e.g.
  the function about to change has large fan-in, or a module another session
  claims imports it.
- **Escape hatch:** an env var / flag (e.g. `AUTOGIS_COORD_FORCE=1`) overrides a
  block; every override is logged.
- **Performance & safety:** the block decision is a **pure local-registry read** —
  it never calls the MCP on the hot path. On registry read/parse failure the hook
  **fails open** with a loud warning; it must never brick the user's git.

### Tier 2 — Brain (advisory pre-flight) — *follow-on plan*

Before claiming, an optional `claim --check` consults the code graph
(`trace_path` / `get_architecture`) for the blast radius of the files about to be
edited and surfaces warnings ("`SiteConfig.get` has 47 inbound callers"; "a module
another session claims imports this file"). **Advisory only** — never blocks.
MCP-present only; silently skipped when the MCP is absent (e.g. cloud sessions).

> Note: the graph catches *semantic* collisions (changing a hotspot breaks
> callers). It does **not** catch *textual co-edit* collisions (two sessions
> appending to the same region of `cli.py` — today's actual failure). Those are
> caught only by the Tier-1 `file_glob` lock. The two tiers are complementary.

### Tier 3 — Cross-boundary ledger (git-synced) — *follow-on plan*

For work that could collide with the nightly cloud agent. An append-only,
one-file-per-session claim in a git-synced directory (e.g.
`.coordination/<session_id>.json`, committed) — conflict-free by construction.

- **Local sessions** write a cross-boundary claim here *only* when their work is
  cloud-collision-prone (touching features the nightly agent might pick).
- **The nightly cloud agent** reads this directory (plus open PRs / branches) at
  startup before choosing features, and writes its own claims + judgment calls
  here. This is its sole coordination surface — it has neither the local registry
  nor the MCP.

### Knowledge layer

- **Local:** `manage_adr` charter blob = a session-start "current architecture
  truth" fetch.
- **Cross/cloud:** the existing append-only `docs/adr/logs/` + `memory/` files,
  read via grep / `gh` (**not** `search_graph`). The nightly agent already writes
  here; this is the durable, git-synced log both sides share.

## Data flow — a local session starting work

1. **Startup:** read `manage_adr` charter + recent `docs/adr/logs/` + the
   git-synced cross-boundary claims → situational awareness.
2. **Before editing:** `claim` the branch/worktree/file-globs → local registry; if
   cloud-collision-prone, also write a Tier-3 git-synced claim.
3. **Pre-flight:** optional graph blast-radius check (advisory).
4. **During work:** heartbeat refreshes the TTL.
5. **Every git/edit op:** the PreToolUse hook gates against the registry.
6. **On finish:** `release` (local) + remove the Tier-3 claim; log noteworthy
   findings to `docs/adr/logs/`.

## Error handling & edge cases

- **Crashed session** → stale heartbeat → claim auto-reaped after TTL.
- **MCP absent** → Tier-2 warnings skipped; Tier-1 reflexes unaffected (pure local
  file).
- **Registry corruption** → hook fails open with a loud warning (never blocks git
  on a parse error).
- **Legit conflict / override** → escape hatch, always logged.
- **Write race** → lock file + re-read; loser backs off.

## Testing

All Tier-1 logic is pure-Python and arcpy-free (honors the `core/` invariant):

- registry `claim` / `release` / `list` round-trip
- stale-claim reaping past TTL
- concurrent-write race (loser backs off)
- hook decision matrix: block on `main`, block on another session's claimed
  branch/file, allow on own claim, warn (not block) on blast-radius
- fail-open on corrupted registry
- override escape hatch is honored and logged

## Delivery strategy

**One design (this document), three implementation plans / PRs:**

- **Plan 1 — Tier 1 Reflexes (MVP):** registry module + CLI helper + PreToolUse
  hook with tiered enforcement. This alone stops both observed failure modes.
- **Plan 2 — Tier 2 Brain:** graph blast-radius pre-flight + advisory hook
  warnings.
- **Plan 3 — Tier 3 Cross-boundary + cloud-agent integration:** git-synced claim
  ledger + nightly-agent read/write convention + `manage_adr` startup fetch.

Build order is coordination-first (Plan 1), per the design discussion.

## Non-goals (YAGNI)

- **No long-running coordinator daemon / service.** Rejected: a service to build,
  run, and keep alive is over-engineered for one machine + one nightly agent. The
  local file + OS lock provides sufficient locking semantics.
- **No `ingest_traces` as a session activity ledger.** Rejected: that tool ingests
  *runtime* traces to enrich the call graph; there is no session/activity node
  type, so the data would not be queryable. A plain append-only file does this
  better.
- **No reliance on `search_graph` for decisions.** The graph indexes Python only;
  decisions live in committed markdown read via grep / `gh`.
