# Concurrent-Session Coordination Remediation — Design

**Date:** 2026-06-30
**Status:** Approved (design); pending implementation plan
**Scope chosen by user:** Full bundle **+ hard guard**
**Source:** Hand-off "Operational gotchas" + memory
`worktree-isolation-parallel-sessions.md`. All root causes empirically verified
this session (see each section).

## Goal

Remediate three operational gotchas that repeatedly cost time when many Claude
sessions run in the **same** `C:\Users\ichbi\AutoGIS` main working tree:

1. **Shared-HEAD checkouts** — another session's `git checkout` moves *your*
   HEAD, landing your commits on the wrong branch.
2. **PostToolUse pytest runs in the main tree**, so its failures are often other
   sessions' half-finished work, not yours.
3. **Commit denied when the branch is claimed by a different `session_id`**, and
   you cannot self-identify to release the conflicting claim (session_id is not
   in the Bash environment; inline `AUTOGIS_COORD_FORCE=1` cannot reach the hook).

Everything in this design lives under `.claude/` **session tooling** — no product
code. `core/`/`adapters/` are untouched; the arcpy-free invariant (ADR-002) is
unaffected. The `.claude/coordination/` modules are pure-stdlib and already unit
tested under `tests/coordination/`; every change preserves that.

## Verified root causes (do not re-derive)

| # | Verified this session |
|---|---|
| 2 | `CLAUDE_PROJECT_DIR` is the **project root** (= main tree); a worktree session's cwd differs. `post-edit-pytest.sh` does `cd "$CLAUDE_PROJECT_DIR"` → tests main, not the worktree. |
| 3 | `CLAUDE_SESSION_ID` / `AUTOGIS_SESSION_ID` are **UNSET** in the Bash tool. `session_id` lives only in the hook payload. The `$CLAUDE_ENV_FILE` → persistent-env mechanism **works** (HEADROOM vars written that way at SessionStart are present in later Bash calls), so exporting the id there is viable. |
| 1 | Right now 5 other sessions are live; 4 are already isolated in their own worktrees; only this session occupies the main root. Confirms the precise gating below: count only sessions whose `worktree` claim **equals this main root**. |

**Ceiling on #1 (accept, don't fight):** no hook or script can move the agent
into a worktree — only the `EnterWorktree` *tool* can. So #1 is **detect + nudge +
streamline + guard**, never full automation.

---

## Fix #2 — make the pytest hook worktree-aware

**File:** `.claude/hooks/post-edit-pytest.sh`

The script already parses the hook payload (for `file_path`). Parse `cwd` from the
**same** payload and `cd` there; fall back to `$CLAUDE_PROJECT_DIR` when `cwd` is
absent.

```sh
# after extracting fp from $payload, also:
cwd=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('cwd',''))" \
  2>/dev/null || true)
cd "${cwd:-${CLAUDE_PROJECT_DIR:-.}}"
```

In a non-worktree session `cwd == CLAUDE_PROJECT_DIR`, so behaviour is unchanged
there. In a worktree session, pytest now runs against the worktree's own tree —
its pass/fail reflects only this session's work. Lowest-risk fix; ship first.

---

## Fix #3 — session self-identification + one-command resync

### 3a. Export the session id (so Bash / `coord_cli` can self-identify)

**File:** `.claude/coordination/session_start.py`

`main()` already holds the payload (with `session_id`) and runs at SessionStart.
Add a guarded write of `export AUTOGIS_SESSION_ID=<sid>` to `$CLAUDE_ENV_FILE`
(append, only when both the env var and sid are present). Extract the body to a
pure helper for unit testing:

```python
def export_session_id(sid, env_file):       # pure; testable with a tmp file
    if sid and env_file:
        with open(env_file, "a", encoding="utf-8") as fh:
            fh.write('export AUTOGIS_SESSION_ID=%s\n' % sid)
```

`main()` calls `export_session_id(payload.get("session_id"), os.environ.get("CLAUDE_ENV_FILE"))`
inside the existing try/except (fail-soft; never aborts SessionStart).

### 3b. `coord_cli` subcommands: `whoami`, `release-mine`, `resync`

**File:** `.claude/coordination/coord_cli.py`

A shared resolver picks the session id with no guessing:

```python
def resolve_sid(reg_path, cwd, env):
    sid = env.get("AUTOGIS_SESSION_ID")
    if sid:
        return sid
    # Fallback: the live `worktree` claim whose value == abspath(cwd) is unique
    # to one session *inside an isolated worktree*. (In the shared main tree the
    # path is shared — but there you have gotcha #1 anyway; documented limit.)
    root = os.path.abspath(cwd)
    matches = [c["session_id"] for c in registry.list_claims(reg_path)
               if c.get("kind") == "worktree"
               and _samepath(c.get("value"), root)]
    return matches[0] if len(matches) == 1 else None
```

New subcommands:

- **`whoami`** — print the resolved sid (or a clear "could not resolve" message,
  exit non-zero), so a human/agent can see their identity.
- **`release-mine`** — `registry.release(reg_path, resolve_sid(...))`; releases
  **only your own** claims. This replaces the collateral "release the *other*
  session's claim" unblock from the memory note.
- **`resync`** — release-mine, then re-claim the **current** branch
  (`git branch --show-current` in cwd) + the **current** worktree
  (`abspath(cwd)`). Collapses the 4-command post-`EnterWorktree` dance in
  CLAUDE.md into one command (the bonus on #1's friction).

`_samepath` normalises with `os.path.normcase(os.path.normpath(...))` for
Windows backslash/case-insensitive comparison. `resolve_sid` takes `env` and
`cwd` as args (default `os.environ`, `os.getcwd()`) so tests inject both.

If resolution fails, `release-mine`/`resync` print the reason and exit non-zero
**without touching the registry** — never release an unknown session's claims.

---

## Fix #1 — detect, nudge, and hard-guard the shared main tree

Two complementary pieces plus the `resync` streamliner from 3b.

### Shared primitive (in `registry.py`, reused by both)

```python
def tree_sharers(path, session_id, root, now=None):
    """Live `worktree` claims (excluding session_id) whose value == root."""
    r = _norm(root)
    return [c for c in list_claims(path, now=now)
            if c.get("session_id") != session_id
            and c.get("kind") == "worktree"
            and _norm(c.get("value", "")) == r]
```

Path normalisation lives **once** in `registry.py`:
`_norm(p) = os.path.normcase(os.path.normpath(p))` and
`samepath(a, b) = _norm(a) == _norm(b)`. `hook_check` and `coord_cli` import
`registry.samepath` rather than redefining it (the `_samepath` references
elsewhere in this doc mean exactly this one helper). `list_claims` already filters
stale by TTL, so dead sessions past TTL do not count.

### 1a. One-time SessionStart nudge (informational)

**File:** `.claude/coordination/session_start.py`

After `reap_stale`, compute `tree_sharers(reg_path, sid, repo_root(cwd))`. If
non-empty, append to the existing `additionalContext` policy string:

> `[coord] N other session(s) share this main working tree. Concurrent checkouts
> here will move your HEAD. Isolate now: EnterWorktree, then run
> 'python .claude/coordination/coord_cli.py resync'.`

Fires **once**, at session start, exactly when isolation is cheapest and only when
there is real contention. Sessions already in their own worktree (cwd ≠ main root,
so their own claim is excluded and others' worktree claims ≠ this root) see
nothing.

### 1b. Hard guard (enforcement) — the user-chosen addition

**File:** `.claude/coordination/hook_check.py`

Deny in-repo writes (`Edit`/`Write`/`MultiEdit`) and `git commit`/`push` when **both**:

1. ≥1 **other** live session claims this main root as its worktree
   (`tree_sharers` non-empty), **and**
2. this session is physically **in the main tree** (not a linked worktree).

Computed once near the top of `decide()` and applied in both the Edit/Write
(in-repo only) and Bash-git-write branches:

```python
def _in_main_tree(cwd):
    # main tree: git-dir == git-common-dir; linked worktree: they differ.
    a = _rev_parse(cwd, "--git-dir"); b = _rev_parse(cwd, "--git-common-dir")
    return bool(a) and _samepath(a, b)          # "" on git error → False → fail open

def _shared_main_tree(reg_path, sid, cwd, in_main_tree=None):
    if not registry.tree_sharers(reg_path, sid, registry.repo_root(cwd)):
        return False                             # cheap registry read first
    return (in_main_tree or _in_main_tree)(cwd)  # git only when contention exists
```

`_in_main_tree` is **injectable** (param `main_tree_func`, default `_in_main_tree`)
mirroring the existing `branch_func`, so unit tests pass a lambda and never shell
out. Ordering matters: **sharers first** (registry), git **only** when sharers
exist — so empty-registry feature-branch tests stay green and pay no subprocess
cost.

Deny message (actionable + escape hatch):

> `[coord] N other session(s) share this main working tree — writing/committing
> here risks landing on the wrong branch. Isolate first: EnterWorktree, then
> 'python .claude/coordination/coord_cli.py resync'. One-off override:
> AUTOGIS_COORD_FORCE=1.`

`AUTOGIS_COORD_FORCE == "1"` already short-circuits `decide()` at the top, so the
guard inherits the force bypass for free.

**Interaction with the existing read-only-main rule:** if `branch == "main"` the
existing more-specific deny fires first (unchanged). The hard guard adds teeth on
a *feature* branch that is being edited from the *shared main tree* with
contention — the exact gotcha-#1 condition.

**Known limitation (documented, not engineered around):** a session that crashed
within the TTL window (default 1800 s) leaves a `worktree` claim that still counts
until reaped, so the guard can false-positive for up to one TTL. Mitigations are
one step each: `coord_cli release --session <stale-sid> --kind worktree` (now easy
to target via `list`/`whoami`), or `AUTOGIS_COORD_FORCE=1` for a single
unblock. We deliberately do **not** shorten the TTL (would risk reaping live-but-
quiet sessions) — YAGNI until the window proves painful.

---

## Documentation

**File:** `CLAUDE.md` (Worktrees & session coordination section)

- Replace the 4-command post-`EnterWorktree` block with a single
  `python .claude/coordination/coord_cli.py resync`.
- Note the pytest hook is now worktree-aware (trust its result inside a worktree).
- Document the hard guard and its `EnterWorktree` + `resync` / `FORCE` unblock.

## Testing (extends `tests/coordination/`, all stdlib, no arcpy)

- **`test_registry.py`** — `tree_sharers`: counts another session's matching-root
  claim; excludes own; excludes non-matching paths; path-normalises
  backslash/case; ignores stale claims.
- **`test_hook_check.py`** — guard denies Edit and `git commit` when sharers exist
  **and** `main_tree_func` → True; allows when sharers exist but
  `main_tree_func` → False (isolated worktree); allows when no sharers (existing
  feature-branch tests must stay green — assert no subprocess via injected func);
  `AUTOGIS_COORD_FORCE=1` bypasses the guard.
- **`test_session_start.py`** — `export_session_id` writes the line to a tmp file
  and is a no-op when sid or env_file is missing; nudge text appears when a
  sharer exists and is absent otherwise.
- **`test_coord_cli.py`** — `resolve_sid` prefers env, falls back to the unique
  worktree claim, returns `None` on ambiguity/none; `release-mine` releases only
  the resolved session's claims and refuses (non-zero, no mutation) when
  unresolved; `resync` releases then re-claims branch+worktree (branch/cwd
  injected).

`post-edit-pytest.sh` is shell; covered by manual verification (run a worktree
edit, confirm pytest runs against the worktree) rather than a unit test, matching
how the other hook shell wrappers are handled.

## Explicit YAGNI / scope boundaries

- **No** attempt to auto-move the agent into a worktree (impossible from a hook).
- **No** TTL tuning / new config knobs.
- **No** changes to product code, `core/`, `adapters/`, or the `.pyt` toolbox.
- **No** new dependencies — pure stdlib throughout.
- Hard guard gates **only** on genuine contention (≥1 other session in *this*
  main root) so solo-in-main work is never blocked.

## Open items for implementation planning

- Confirm `coord_cli`'s `resync` branch read matches `session_start._git_branch`
  (reuse, don't duplicate the helper).
- Confirm the deny-message wording is within any practical length the hook UI
  renders cleanly.
- Decide subcommand names finally (`release-mine` vs `unclaim`, `resync` vs
  `rebind`) — current names chosen for clarity.
