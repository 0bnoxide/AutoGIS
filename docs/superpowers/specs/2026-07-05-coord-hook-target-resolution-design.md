# Coordination-Hook Target-Based Resolution + Soft Contention Warn — Design

**Date:** 2026-07-05
**Status:** Implemented 2026-07-05 (commits `915e1dd`, `a0eccb9` on
`worktree-coord-hook-target-resolution`). The shipped code in
`.claude/coordination/hook_check.py` is authoritative; the sketches below are
illustrative and were corrected post-implementation where they diverged (the
`_first_existing`/`_git_cmd_dir`/`_in_main_tree` notes flag what changed).
**Scope chosen by user:** Option **C** — fix bug 1a (target-based resolution) **+**
a *soft* (warn, not deny) contention guard. The hard-*deny* guard from
`2026-06-30-coord-remediation-design.md` (§1b) is **not** built.
**Supersedes:** the deferred "hard guard (#1b)" follow-up noted in the status
block of `docs/superpowers/specs/2026-06-30-coord-remediation-design.md`.
**Tracks:** issue #136 (bug 1a) and issue #135 (the guard — reshaped to a warn).

## Problem

`hook_check.py`'s `decide()` — the PreToolUse coordination hook, run on **every
tool call for every concurrent session** — resolves "what branch/tree is this
write targeting" from `payload["cwd"]`. For a **pinned-cwd subagent** that
signal is wrong: cwd is fixed at dispatch (usually the main root) and does not
track a `cd` / `git worktree add` inside the subagent's own Bash commands. Only
the `EnterWorktree` *tool* moves it. So every tool call from such a subagent
reports the same stale main-root cwd, `_git_branch(cwd)` resolves to the main
tree's branch (often `main`), and the hook **wrongly denies** a write that is
actually, correctly, targeting a claimed worktree (issue #136, "bug 1a").

The same stale-cwd flaw is why the originally-specced hard guard (§1b of the
2026-06-30 design) was deferred: it resolved "am I in the main tree?" from the
same `payload.cwd`, so building it as written would have made the pinned-cwd
failure *worse* — a hard deny keyed off a signal that is broken for exactly the
session type that most needs to write to a worktree.

## Root cause (verified previous session — issue #136, do not re-derive)

`decide()` trusts `payload["cwd"]` as "where this write is happening." For a
normal (non-subagent) session Claude Code's own cwd tracking keeps this accurate
across `cd` / `EnterWorktree`. For a pinned-cwd subagent it is frozen at
dispatch. The bug is **target resolution**, not identity resolution — `decide()`
already knows *who* it is (`sid = payload["session_id"]` is present in every hook
payload; the heartbeat and the SessionStart auto-claim already depend on it).
The handoff's alternative "call `coord_cli.resolve_sid()` inside the hook to
learn which session this is" answers a question the hook never had: `resolve_sid`
exists for a *Bash* caller (`coord_cli`) that has **no payload** and must
self-identify. It is not needed here and is **not** used by this design.

## Decision

Resolve branch/tree from the **actual write target**, not `payload.cwd`. The
payload already carries a more precise signal than cwd:

- **Edit / Write / MultiEdit** — the target is `file_path` (absolute in
  production). Its directory is the exact tree the write lands in. This is
  *structured data, not command text* — zero parsing, exact.
- **Bash `git commit` / `git push`** — the target is the directory the git
  process runs in: a `git -C <path>` argument, or a leading `cd <path>` carried
  across `&&` / `;`, else `cwd`. Best-effort; falls back to cwd (= today's
  behavior) when it cannot parse.

### Why not resolve from the claim (handoff "direction 2")

A claim records a session's *intent* ("I am working on `feat/x`"), not where a
given operation *physically lands*. A session that claimed `feat/x` but drifted
its HEAD to `main` — literally gotcha #1 — and then commits would be **wrongly
allowed** by claim-based resolution, defeating the read-only-`main` protection
the system exists to provide. Both protections (read-only-`main`, wrong-branch)
care about where the operation actually lands, so target-based resolution is the
correct signal and claim-based resolution is rejected.

### Why a soft warn, not a hard deny (option C)

The 2026-06-30 design's own adversarial review (#6) judged the hard *deny* guard
"high-risk / low-marginal-value": the once-at-start nudge (shipped in PR #156)
already captures most of gotcha #1's value, while a deny carries a TTL-window
false-block risk and a self-lockout risk (editing the coordination files
themselves under contention). Fixing bug 1a independently makes the existing
read-only-`main` and wrong-branch denials reliable for subagents. The remaining
increment — detecting feature↔feature HEAD churn in a *shared* main tree — is
delivered as a **warning on the write** (non-blocking `additionalContext`),
which keeps the detection value (and adds a case the once-at-start nudge misses:
a session that starts solo and becomes contended mid-session) with **none** of
the deny's lockout/false-block risk.

All changes live in `.claude/coordination/hook_check.py` — pure stdlib, no
product code. `core/` / `adapters/` and the arcpy-free invariant (ADR-002) are
untouched.

---

## Component 1 — resolve from the target, not cwd (bug 1a)

Three helpers added to `hook_check.py`, then the two `bf(cwd)` call sites in
`decide()` switch to the resolved target.

```python
def _first_existing(d):                          # (shipped name; operates on a DIR)
    """Nearest existing ancestor of directory d (d itself if it exists), so a
    new file in a not-yet-created package still resolves via its worktree
    instead of failing `git -C` to ''. NB: this takes a directory — the caller
    does dirname(file) for the Edit case (an earlier sketch folded the dirname
    in here, which off-by-one'd the Bash path whose base is already a dir)."""
    d = os.path.abspath(d)
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return d


def _git_cmd_dir(cmd):
    """Effective directory the git *WRITE* runs in, parsed from a Bash command:
    the write's `git -C <path>`, or a leading `cd <path>` carried across
    `&&`/`;`/newline segments, else '' (caller falls back to cwd). A *read* git
    (log/diff/...) does NOT count — its `-C` must not leak to the write and its
    presence must not stop the scan (keys on the write subcommand, matching
    `_is_git_write`). Only sequential separators carry the `cd`. Best-effort —
    subshells, $vars, command substitution fall through to cwd."""
    cur = ""
    for seg in re.split(r"&&|;|\n", cmd):
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        if not toks:
            continue
        if toks[0] == "cd" and len(toks) >= 2:
            cur = toks[1]
            continue
        if "git" in toks:
            i = toks.index("git") + 1
            dashC = ""
            sub = ""
            while i < len(toks):
                t = toks[i]
                if t == "-C" and i + 1 < len(toks):
                    dashC = toks[i + 1]
                    i += 2
                    continue
                if t.startswith("-"):            # skip option (+ arg), same rule
                    i += 2 if t in _GLOBAL_OPTS_WITH_ARG else 1  # as _git_subcommands
                    continue
                sub = t
                break
            if sub in _GIT_WRITE_SUBCMDS:
                return dashC or cur              # only the WRITE's dir counts
            # read git — its -C doesn't count; keep scanning later segments
    return cur


def _target_dir(tool, ti, cwd):
    """The directory the write actually lands in — not payload cwd, which is
    stale for pinned-cwd subagents."""
    if tool in ("Edit", "Write", "MultiEdit"):
        fp = ti.get("file_path", "")
        d = os.path.dirname(os.path.abspath(fp)) if fp else cwd  # file → its dir
    elif tool == "Bash":
        parsed = _git_cmd_dir(ti.get("command", ""))
        d = os.path.join(cwd, parsed) if parsed else cwd   # abs parsed wins, rel joins
    else:
        d = cwd
    return _first_existing(d)
```

Branch resolution in `decide()` becomes:

```python
branch = bf(target) or bf(cwd)   # empty (detached HEAD) → cwd floor = today's behavior
```

Key correctness points:

- **cwd is still the right *base* for a relative `cd`.** The real Bash subprocess
  also starts in cwd before it `cd`s, so `os.path.join(cwd, "relative/path")` is
  exactly where the commit lands — even when cwd is the stale main root, the
  relative `cd` is relative to that same root.
- **A linked worktree can never be on `main`** (git forbids the same branch
  checked out in two trees), so worktree edits resolve to their feature branch
  and are correctly *allowed*; only a genuine main-tree-on-`main` write is denied.
- **Empty resolution** (detached HEAD, or — defensively — an unresolvable target)
  falls back to `bf(cwd)`, restoring today's floor. Without this, `"" != "main"`
  would silently let a write slip the read-only-`main` guard. The `_first_existing`
  walk means a new-file-in-new-dir does **not** hit this path (it resolves to the
  nearest real ancestor's branch), so the fallback fires only for true detached
  HEAD, where "not `main`" → allowed matches today.
- **`_git_cmd_dir` resolves the *write*'s dir, not the first git's.** `git -C <x>
  log && git commit` must resolve the commit (cwd), not the read's `-C <x>` —
  otherwise a commit to `main` behind a read `git -C <feature-wt> …` would
  false-*allow*. The parser keys on the write subcommand, matching
  `_is_git_write`.

## Component 2 — soft contention warn (option C)

Same detection the hard guard would use, emitted as non-blocking
`additionalContext`. Fires when **both**:

1. `registry.tree_sharers(reg_path, sid, repo_root(cwd))` is non-empty — another
   *identified* live session claims this main root as its worktree, **and**
2. the **target** is physically in the main tree.

```python
def _rev_parse(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", *args],
                           capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _in_main_tree(d):
    # main tree: git-dir and git-common-dir point at the SAME .git; a linked
    # worktree: they differ. git prints either absolute OR cwd-relative paths
    # (e.g. git-dir absolute but common-dir '../.git' from a SUBDIR), so resolve
    # both against d before comparing — a plain samepath(out[0], out[1]) on the
    # raw lines false-negatives from a subdirectory. git error → '' → [] → False.
    out = _rev_parse(d, "--git-dir", "--git-common-dir").splitlines()
    if len(out) != 2:
        return False

    def _abs(p):
        p = p.strip()
        return os.path.normcase(os.path.abspath(
            p if os.path.isabs(p) else os.path.join(d, p)))

    return _abs(out[0]) == _abs(out[1])


def _shared_tree_warn(reg_path, sid, target, cwd, main_tree_func=None):
    sharers = registry.tree_sharers(reg_path, sid, registry.repo_root(cwd))
    if not sharers:                                    # cheap registry read FIRST
        return None
    if not (main_tree_func or _in_main_tree)(target):  # git ONLY under contention
        return None
    return _warn(
        "[coord] %d other session(s) share this main working tree and this write "
        "targets it — concurrent checkouts here can move your HEAD onto the wrong "
        "branch. Isolate: EnterWorktree, then "
        "'python .claude/coordination/coord_cli.py resync'." % len(sharers))
```

- **`main_tree_func` is injectable** (mirrors the existing `branch_func`) so unit
  tests pass a lambda and never shell out.
- **Ordering is deliberate: registry read first, git only under contention** — so
  the no-contention path (the overwhelming common case) pays zero subprocess cost,
  and existing empty-registry tests stay green.
- **Keying `_in_main_tree` off `target` is what makes it subagent-safe.** A
  worktree file reports git-dir ≠ common-dir → not-in-main → no false warn, even
  when cwd is the stale main root. (`repo_root` already relies on this same
  git-dir/common-dir property.)
- **`repo_root(cwd)`** resolves to the one canonical main root from anywhere in
  the repo, so the stale cwd still yields the correct root here.

## `decide()` final shape

Force-bypass and heartbeat unchanged at the top. `target` is computed once for
write tools; `branch` and the warn reuse it. Precedence — **deny beats warn**:

```
Edit/Write/MultiEdit, in-repo:
    resolved branch == 'main'      -> DENY  (read-only main; unchanged)
    shared-tree warn applies       -> WARN  (new)
    file_conflicts                 -> WARN  (existing)

Bash git write:
    resolved branch == 'main'      -> DENY  (unchanged)
    branch_conflicts               -> DENY  (unchanged; now target-resolved)
    shared-tree warn applies       -> WARN  (new)
```

`decide()` gains one optional parameter, `main_tree_func=None`, alongside the
existing `branch_func=None`. `branch_conflicts` and the read-only-`main` check
now use the target-resolved `branch` — a strict improvement (they check the
branch the operation actually lands on).

---

## Testing (extends `tests/coordination/test_hook_check.py`, all stdlib)

Per the live-gating constraint, **write these before touching `decide()`'s
enforcement branches.** Use the injected `branch_func` / `main_tree_func`; never
shell out.

Bug 1a (target resolution):

- Worktree Edit no longer false-denied: `branch_func=lambda d: "main" if d ==
  <main-subdir> else "feat/x"`, `file_path` under the worktree → `out is None`.
- Main-tree Edit still denied (target resolves `main`).
- Bash `cd <wt> && git commit` and `git -C <wt> commit` resolve to the worktree's
  branch → allowed; bare `git commit` with cwd = main (on `main`) → denied.
- Empty-resolution fallback: `branch_func` returns `""` for target, non-empty for
  cwd → uses cwd branch.
- `_git_cmd_dir` unit cases: `git -C /wt commit` → `/wt`; `cd /wt && git commit`
  → `/wt`; `git commit` → `""`; `cd a && cd b && git commit` → `b`;
  `git -C /bar` inside `cd /foo && … && git -C /bar commit` → `/bar`;
  **`git -C /wt log && git commit` → `""`** (a *read*'s `-C` must not leak).
- No-false-allow at `decide()` level: `git -C <wt> log && git commit` with cwd on
  `main` → **denied** (the commit runs in cwd, not the read's `-C`).

Soft warn:

- Sharer present **and** `main_tree_func` → True → `additionalContext` present,
  **no** `permissionDecision` (assert it is a warn, not a deny).
- **No** sharers → no warn **and** `main_tree_func` never consulted (assert via a
  lambda that records/raises if called — proves the registry-first ordering and
  the zero-subprocess no-contention path).
- Sharers present but `main_tree_func` → False (isolated worktree target) → no
  warn.
- `AUTOGIS_COORD_FORCE=1` bypasses everything (existing pattern).
- `_in_main_tree` normalization: injected `_rev_parse` returning an absolute
  git-dir + relative `../.git` common-dir → `True`; differing gitdirs → `False`;
  **plus a real-git test** (skipif no git) building a repo + linked worktree so
  the subdir absolute/relative format regression can't silently return.

Regression: the existing tests use `lambda cwd: …` lambdas that ignore their arg,
so they keep passing unchanged.

**Manual / integration verify** (recursion-safe) — **done:** dry-ran `decide()`
against the **real** `.claude/coordination/claims.json` at the main root with the
live registry (13 stale main-root claims + this session's live worktree claim),
confirming (a) a worktree write with stale `cwd=main` now allowed (target →
`worktree-…` branch, not `main`), (b) the warn firing on a synthetic live sharer
(temp registry copy — the shared file was never mutated), and (c) the stale
main-root claims correctly ignored (`tree_sharers` → 0, no false warn).

## Documentation & records

- **`CLAUDE.md`** (Worktrees & session coordination): note that branch/tree
  resolution is now target-based (pinned-cwd subagents committing via
  `git -C <worktree>` or `cd <worktree> && …` are resolved correctly), and that a
  soft contention re-nudge fires on writes when another session shares the main
  tree.
- **`2026-06-30-coord-remediation-design.md`** status block: update from "hard
  guard (#1b) deferred" to "resolved via this design (option C)"; resolve the
  #135-vs-#136 "bug 1b" numbering collision noted in the handoff while touching it.
- **New ADR** (structural change to a hook that gates every concurrent session):
  record target-based resolution + the soft-warn decision. Check the next-free
  ADR number against **open PRs' files**, not just `ls docs/adr/`, per the
  collision history (memory: ADR-0034 collision, PR #127).

## Sequencing / prerequisites

- **Resolved:** PR #156 merged to `main` (`006e921`) before this work started, so
  `registry.tree_sharers` / `registry.samepath` are present. This branch is based
  on the merged `main`; the 1a fix touches only `hook_check.py` (which #156 never
  touched), so the change is conflict-free.

## Explicit YAGNI / scope boundaries

- **No** claim-based resolution (records intent, not landing site — defeats
  read-only-`main`).
- **No** hard deny; the guard is warn-only.
- **No** TTL tuning, no new config knobs.
- **No** parsing of exotic Bash constructs (subshells, `$vars`, command
  substitution) — documented ceiling; they fall back to cwd.
- **Windows / Git-Bash path ceiling (safe direction).** On this box the Bash tool
  is Git Bash, so `cd`/`-C` paths are POSIX. Only **relative** paths
  (`cd .claude/worktrees/x`) and **drive-letter-forward-slash** (`C:/…`) resolve
  cleanly. An MSYS absolute (`cd /c/Users/…`) mis-joins via `os.path.join` and a
  backslash path is mangled by POSIX `shlex` — **both fall back to cwd** (→ a
  false-*deny*, the safe direction; recourse is the `git -C C:/…` form or
  `AUTOGIS_COORD_FORCE=1`). Relative is the common case, so no code is added.
- **No** product-code / `core/` / `adapters/` / `.pyt` changes; pure stdlib.
- **No** new dependencies.

## Open items for implementation planning

- Confirm the deny/warn precedence renders cleanly in the hook UI (a warn's
  `additionalContext` is advisory; a deny's reason blocks).
- Confirm `_rev_parse`'s two-line output parsing is stable across the git
  versions in use (Windows + any CI) — `--git-dir --git-common-dir` prints two
  lines; a one-line/empty result must degrade to `False` (already handled).
- Decide whether the shared-tree warn should also fire on non-git Bash writes
  (currently only Edit/Write in-repo and Bash git-write) — default **no**
  (YAGNI: only real writes to the tree matter).
