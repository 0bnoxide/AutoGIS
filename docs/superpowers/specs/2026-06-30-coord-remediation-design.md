# Concurrent-Session Coordination Remediation — Design

**Date:** 2026-06-30
**Status:** Partially implemented 2026-07-05 (issue #135) — fixes #1a (nudge),
#2 (worktree-scoped pytest), and #3 (`resolve_sid`/`whoami`/`release-mine`/
`resync`) are shipped and tested (`tests/coordination/`). The **hard guard**
(#1b, in `hook_check.py`) is deliberately NOT built: issue #136 found that
resolving branch/tree identity from payload `cwd` (this design's approach)
breaks for pinned-cwd subagents the same way the FORCE-override escape hatch
does — building #1b as specced here would add a hard deny with a broken
bypass for exactly that session type. #1b needs a redesign together with
#136, resolving identity from the target path or the claim itself, not
payload `cwd`. Tracked as a follow-up, not silently dropped.
**Scope chosen by user:** Full bundle **+ hard guard**
**Source:** Hand-off "Operational gotchas" + memory
`worktree-isolation-parallel-sessions.md`. All root causes empirically verified
this session (see each section).

## Goal

Remediate three operational gotchas that repeatedly cost time when many Claude
sessions run in the **same** main working tree (repo root, i.e.
`$CLAUDE_PROJECT_DIR`):

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
cd "${cwd:-${CLAUDE_PROJECT_DIR:-.}}" || exit 0   # stale/removed cwd: skip, don't abort
```

In a non-worktree session `cwd == CLAUDE_PROJECT_DIR`, so behaviour is unchanged
there. In a worktree session, pytest now runs against the worktree's own tree —
its pass/fail reflects only this session's work. Lowest-risk fix; ship first.

Three hardening notes (from adversarial review):

- **`cwd` in the PostToolUse payload is not separately verified** (PreToolUse was).
  It does not matter: if `cwd` is absent the `${cwd:-…}` fallback yields *today's
  exact behaviour* (main tree), so the change is strictly safe.
- **The `|| exit 0` guard** stops `set -euo pipefail` from aborting the hook (and
  silently running no tests) when `cwd` points at a stale/removed directory.
- **Editable-install ordering:** `pip install -e` points at the *main* tree, but
  `python -m pytest` inserts cwd at `sys.path[0]`, so `import autogis` resolves to
  the worktree ahead of the main editable install. This is the intended behaviour;
  noted as a documented assumption (if it ever regresses, the hook would test
  main's code — detectable, not silently wrong).

---

## Fix #3 — session self-identification + one-command resync

### 3a. Export the session id (so Bash / `coord_cli` can self-identify)

**File:** `.claude/hooks/session-start.sh` — **not** `session_start.py`.

The export must go where `$CLAUDE_ENV_FILE` is **provably present**. This session
verified the var only for `session-start.sh` (its HEADROOM exports persisted into
later Bash calls); `session_start.py`'s access is **unverified**, and even
`session-start.sh` guards it as `${CLAUDE_ENV_FILE:-}` (sometimes absent). So write
the export from the shell hook, inside the existing `if [ -n "${CLAUDE_ENV_FILE:-}" ]`
block that already writes the HEADROOM vars — one cohesive place for every
`$CLAUDE_ENV_FILE` write.

`session-start.sh` does not currently read its stdin payload; add a stdin read +
session_id extract — the same unconditional `payload=$(cat)` pattern
`post-edit-pytest.sh` already uses. No extra guard around the read itself: Claude
Code always supplies a payload on stdin for both hook events, so `post-edit-pytest.sh`
relies on that guarantee today and this reuses it verbatim. Then export
**idempotently** — append only if absent, so resume/compact re-fires don't
accumulate duplicate `export` lines (review finding #4):

```sh
payload=$(cat)                                   # SessionStart payload on stdin
sid=$(printf '%s' "$payload" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('session_id',''))" \
  2>/dev/null || true)
# ...inside the existing `if [ -n "${CLAUDE_ENV_FILE:-}" ]` block:
if [ -n "$sid" ] && ! grep -q '^export AUTOGIS_SESSION_ID=' "$CLAUDE_ENV_FILE" 2>/dev/null
then
  echo "export AUTOGIS_SESSION_ID=$sid" >> "$CLAUDE_ENV_FILE"
fi
```

Best-effort: when `$CLAUDE_ENV_FILE` is genuinely absent the export no-ops and
`AUTOGIS_SESSION_ID` stays unset — callers then use the explicit `--session`
override (3b). **The env var is the convenience path; `--session` is the guaranteed
one.** `session_start.py` is unchanged by 3a (it still owns claims + the 1a nudge).
Each SessionStart hook receives its own copy of stdin, so `session-start.sh`
consuming the payload does not starve `session_start.py`.

### 3b. `coord_cli` subcommands: `whoami`, `release-mine`, `resync`

**File:** `.claude/coordination/coord_cli.py`

All three resolve the session id through one helper, in strict precedence —
**explicit `--session` > `AUTOGIS_SESSION_ID` env > cwd→claim fallback**:

```python
def resolve_sid(reg_path, cwd, env, explicit=None):
    if explicit:
        return explicit                          # caller knows its sid
    sid = env.get("AUTOGIS_SESSION_ID")
    if sid:
        return sid                               # set by session-start.sh (3a)
    # Last-resort fallback: the live `worktree` claim whose value == abspath(cwd).
    # Unique to one session ONLY in a steady-state, already-claimed worktree.
    root = os.path.abspath(cwd)
    matches = [c.get("session_id") for c in registry.list_claims(reg_path)
               if c.get("session_id") and c.get("kind") == "worktree"
               and registry.samepath(c.get("value", ""), root)]
    return matches[0] if len(matches) == 1 else None
```

Each new subcommand takes an optional `--session SID` (consistent with the
existing `claim`/`release` commands). `resolve_sid` takes `env`/`cwd` as args
(default `os.environ`, `os.getcwd()`) so tests inject both.

- **`whoami`** — print the resolved sid, or a clear "could not resolve (set
  AUTOGIS_SESSION_ID or pass --session)" message and exit non-zero.
- **`release-mine`** — release **only the resolved session's** claims. Replaces the
  collateral "release the *other* session's claim" unblock from the memory note.
- **`resync`** — release-mine, then re-claim the **current** branch
  (`session_start._git_branch(cwd)`, reused — not a duplicate helper) + the
  **current** worktree (`abspath(cwd)`). Collapses the 4-command
  post-`EnterWorktree` dance into one.

**Resolver scope — corrected after review (blocker #1):** the cwd→claim fallback
**cannot** resolve `resync`'s primary use case. You run `resync` *immediately after*
`EnterWorktree`, when the new worktree is **not yet claimed** (creating that claim is
resync's job) and your only remaining claim still points at the *old* tree — so the
cwd lookup matches nothing. Therefore **`resync` requires `AUTOGIS_SESSION_ID`
(set by 3a in normal sessions) or an explicit `--session`.** The cwd-fallback is
real only for `whoami`/`release-mine` from inside an already-claimed worktree
(steady state). The CLAUDE.md update (below) states this requirement plainly.

If resolution fails, `release-mine`/`resync` print the reason and exit non-zero
**without touching the registry** — never release an unknown session's claims.

---

## Fix #1 — detect, nudge, and hard-guard the shared main tree

Two complementary pieces plus the `resync` streamliner from 3b.

### Shared primitive (in `registry.py`, reused by both)

```python
def tree_sharers(path, session_id, root, now=None):
    """Live `worktree` claims by *another identified* session whose value == root.
    Empty/missing session_id (orphan claims — the live `scratch-0630` is one) are
    ignored: they cannot meaningfully be 'another session' and would otherwise make
    the hard guard false-block."""
    r = _norm(root)
    return [c for c in list_claims(path, now=now)
            if c.get("session_id") and c.get("session_id") != session_id
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
    # ONE subprocess returns both lines (review #5 — halves the overhead).
    out = _rev_parse(cwd, "--git-dir", "--git-common-dir").splitlines()
    return len(out) == 2 and registry.samepath(out[0], out[1])  # git error → [] → False

def _shared_main_tree(reg_path, sid, cwd, main_tree_func=None):
    if not registry.tree_sharers(reg_path, sid, registry.repo_root(cwd)):
        return False                                  # cheap registry read first
    return (main_tree_func or _in_main_tree)(cwd)      # git only when contention exists
```

`_in_main_tree` is **injectable** (param `main_tree_func`, default `_in_main_tree`)
mirroring the existing `branch_func`, so unit tests pass a lambda and never shell
out. Ordering matters: **sharers first** (registry), git **only** when sharers
exist — so empty-registry feature-branch tests stay green and pay no subprocess
cost. Under genuine contention the added cost is **one** `git rev-parse` (both dirs
in a single call) plus the registry read already performed — bounded and only on
the contended path.

**Fail-open is the deliberate posture (review #5).** When the registry is degraded
(sharer claims stale/reaped) `_shared_main_tree` returns `False` and the write is
allowed. We choose under-block over lock-everyone-out on a bad registry: a missed
guard costs at most the original gotcha-#1 friction, whereas a hard-failing guard on
a degraded registry would brick every session's writes.

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

**Risk framing (review #6) — the hard guard is the high-risk / low-marginal-value
piece.** The reality check (4 of 5 live sessions already isolated; the failure
happened once) says the **SessionStart nudge (1a) captures most of #1's value**,
while the guard carries nearly all the new risk: the TTL false-block window, the
per-write overhead, and the chance of self-lockout while editing the coordination
files themselves. You explicitly chose it, so it ships — but it is the **first
piece to drop or disable** if it misbehaves. Disable path: it is gated entirely
behind `tree_sharers`, and `AUTOGIS_COORD_FORCE=1` set in the harness env
neutralises it globally without touching the nudge, `resync`, or the pytest fix.

---

## Documentation

**File:** `CLAUDE.md` (Worktrees & session coordination section)

- Replace the 4-command post-`EnterWorktree` block with a single
  `python .claude/coordination/coord_cli.py resync` — stating it relies on
  `AUTOGIS_SESSION_ID` (auto-set by `session-start.sh`) or an explicit
  `--session <sid>` (blocker #1; the cwd-fallback does not cover the just-switched
  worktree).
- Note the pytest hook is now worktree-aware (trust its result inside a worktree).
- Document the hard guard and its `EnterWorktree` + `resync` / `FORCE` unblock.

## Testing (extends `tests/coordination/`, all stdlib, no arcpy)

- **`test_registry.py`** — `tree_sharers`: counts another session's matching-root
  claim; excludes own; excludes non-matching paths; path-normalises
  backslash/case; ignores stale claims; **ignores empty/missing-sid orphan
  claims** (review #5). `samepath` table cases.
- **`test_hook_check.py`** — guard denies Edit and `git commit` when sharers exist
  **and** `main_tree_func` → True; allows when sharers exist but
  `main_tree_func` → False (isolated worktree); allows when no sharers (existing
  feature-branch tests must stay green — assert via injected func that git is
  never shelled out when the registry has no sharers); `AUTOGIS_COORD_FORCE=1`
  bypasses the guard.
- **`test_session_start.py`** — nudge text appears in `additionalContext` when a
  sharer exists and is absent otherwise. (Session-id export moved to the shell
  hook — see below.)
- **`test_coord_cli.py`** — `resolve_sid` precedence: **explicit `--session` wins
  over env wins over the cwd fallback**; cwd fallback returns the unique worktree
  claim and `None` on ambiguity/none; `release-mine` releases only the resolved
  session's claims and refuses (non-zero, **no mutation**) when unresolved;
  `resync` releases then re-claims branch+worktree (branch/cwd injected); **resync
  with no env and no `--session` errors without mutating** (blocker-#1 guard).

**Shell hooks.** `post-edit-pytest.sh` stays **manual-verify** (run a worktree
edit, confirm pytest runs against the worktree) — a unit test would recurse into
pytest. The **session-id export idempotency** in `session-start.sh`, however, is
recursion-free and error-prone (the `grep` dedup guard), so it gets a tiny scripted
check (review #7): pipe a synthetic `{"session_id":...}` payload through the export
snippet **twice** against a tmp `CLAUDE_ENV_FILE` and assert exactly **one**
`AUTOGIS_SESSION_ID` line. Lives under `tests/coordination/` as a subprocess-driven
test, skipped when `bash` is unavailable.

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
