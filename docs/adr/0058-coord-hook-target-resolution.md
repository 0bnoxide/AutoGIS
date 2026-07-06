# ADR-0058: Coordination hook resolves branch/tree from the write target, not payload cwd; soft contention warn instead of a hard deny

**Status:** Accepted

**Date:** 2026-07-05

## Context

`.claude/coordination/hook_check.py`'s `decide()` — the PreToolUse hook that
runs on **every tool call for every concurrent session** — decided "what
branch/tree is this write targeting" from `payload["cwd"]`. For a **pinned-cwd
subagent** that signal is wrong: cwd is frozen at dispatch (usually the main
root) and does not track a `cd` / `git worktree add` inside the subagent's own
Bash commands; only the `EnterWorktree` *tool* moves it. So a legitimate write
to a claimed worktree resolved the *main* tree's branch (often `main`) and was
**false-denied** by the read-only-`main` rule (issue #136 "bug 1a").

The same flaw is why the "hard guard" proposed in
`docs/superpowers/specs/2026-06-30-coord-remediation-design.md` (§1b, issue
#135) was deferred: it resolved "am I in the main tree?" from the same
`payload.cwd`, so shipping it as specced would have made the pinned-cwd failure
*worse* — a hard deny keyed off a broken signal, with a bypass
(`AUTOGIS_COORD_FORCE=1`) that pinned-cwd subagents cannot set. Both #135 and
#136 needed one combined redesign. Design doc:
`docs/superpowers/specs/2026-07-05-coord-hook-target-resolution-design.md`.

## Decision

1. **Resolve from the write *target*, not `payload.cwd`.** The payload already
   carries a more precise signal than cwd:
   - **Edit / Write / MultiEdit** — the target is `file_path`; its directory is
     the exact tree the write lands in. Structured data, zero parsing, exact.
   - **Bash `git commit` / `git push`** — the target is the directory the git
     *write* runs in: the write's `git -C <path>`, or a leading `cd <path>`
     carried across `&&`/`;`/newline segments, else `cwd`.

   Branch resolution becomes `bf(target) or bf(cwd)` — the `or bf(cwd)` restores
   today's floor when the target resolves empty (detached HEAD). A new file in a
   not-yet-created package walks up to its nearest existing ancestor
   (`_first_existing`) so it still resolves via its worktree rather than failing
   `git -C` to `''`.

2. **The Bash parser keys on the *write* subcommand, matching `_is_git_write`.**
   `git -C <x> log && git commit` resolves the *commit* (cwd), not the read's
   `-C <x>` — a read git's `-C` must not leak, and its presence must not stop the
   scan. Otherwise a commit to `main` behind a read `git -C <feature-wt> …` would
   false-*allow* (defeating read-only-`main`), and the mirror would false-*deny*
   a legitimate feature commit.

3. **The #135 guard ships as a *soft warn*, not a hard deny (user-chosen option
   C).** A non-blocking `additionalContext` nudge fires on an in-repo write when
   (a) another *identified* live session claims this main root as its worktree
   (`registry.tree_sharers`, stale claims excluded), **and** (b) the **target**
   is physically in the main tree (`git-dir == git-common-dir`, resolved against
   the query dir since git prints one absolute and one relative from a subdir).
   Registry read happens first; git runs only under real contention. Keying (b)
   off the target — not cwd — is what makes the guard subagent-safe.

4. **All changes are confined to `.claude/coordination/hook_check.py`** — pure
   stdlib, no product code. The arcpy-free invariant (ADR-002) is untouched.

## Consequences

### Positive

- A pinned-cwd subagent's legitimate worktree write/commit is no longer
  false-denied — the hook judges where the write actually lands.
- The read-only-`main` and wrong-branch denials now check the branch the
  operation *lands on*, closing both a false-deny (worktree write) and a
  false-allow (`git -C <read> && git commit`) that the cwd-based version had.
- The contention guard's original blocker (worse for pinned-cwd) is gone, and by
  shipping it as a warn it carries none of a hard deny's TTL-window false-block
  or self-lockout risk (review #6 of the 2026-06-30 design) while adding a case
  the once-at-start nudge misses: a session that becomes contended mid-session.
- Verified against the **real** shared `claims.json` + real git: worktree write
  allowed, warn fires on a live sharer, 13 stale main-root claims ignored, shared
  file never mutated. A skipif-no-git test pins the real subdir git-dir format so
  the regression can't silently return.

### Negative / accepted trade-offs

- **Bash command-text parsing is best-effort.** Subshells, `$vars`, command
  substitution, MSYS-absolute (`/c/…`) and backslash Windows paths are not
  parsed and fall back to `cwd` — a false-*deny* (the safe direction); recourse
  is the `git -C C:/…` form or `AUTOGIS_COORD_FORCE=1`. Documented ceiling, no
  code added (YAGNI; relative `cd` and drive-letter `C:/…` are the common cases).
- **The warn can false-fire for up to one TTL** if a sharer session crashed
  within the window (its worktree claim still counts until reaped) — but it only
  *warns*, so the cost is a stray nudge, not a block.

## Alternatives considered

1. **Resolve identity from the session's *claim*** (the handoff's "direction 2":
   call `resolve_sid()` inside the hook, check the target against that session's
   claimed branch). Rejected: a claim records *intent*, not where an operation
   physically lands. A session that claimed `feat/x` but drifted HEAD to `main`
   (literally gotcha #1) and commits would be wrongly *allowed*, defeating
   read-only-`main`. Also, `decide()` already knows *who* it is
   (`payload["session_id"]`); the bug was never identity resolution — it was
   *target* resolution. `resolve_sid` exists for a Bash caller (`coord_cli`) with
   no payload, not for the hook.
2. **Ship the #135 guard as a hard *deny*** (the original §1b). Rejected by the
   user in favor of option C: review #6 judged the deny high-risk/low-marginal-
   value; the 1a fix already makes read-only-`main` reliable for subagents, so
   the incremental deny carried nearly all the risk (TTL false-block, self-
   lockout while editing the coordination files) for little added value.
3. **More aggressive command-text parsing** (subshells, variable expansion).
   Rejected as over-build: the failure direction is a safe false-deny with a
   trivial `git -C` recourse, and full shell emulation in a hook is a bug farm.

## Related decisions

- [ADR-0002](0002-arcpy-free-core-invariant.md) — the arcpy-free
  `core`/`adapters` invariant, unaffected (this is `.claude/` session tooling,
  pure stdlib).
- `docs/superpowers/specs/2026-06-30-coord-remediation-design.md` — the prior
  coordination remediation; its §1b hard-guard proposal is superseded here.
- `docs/superpowers/specs/2026-07-05-coord-hook-target-resolution-design.md` —
  the design this ADR records.

## Issues/PRs

- Resolves issue #136 (bug 1a) and #135 (guard, reshaped to a warn).
- This decision + implementation: `.claude/coordination/hook_check.py`,
  `tests/coordination/test_hook_check.py`.
