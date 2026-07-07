# ADR-0067: Coordination hook covers every git write in a command, push-to-main refspecs, history-writing porcelain, links, and NotebookEdit

> **Numbering note:** placeholder `0067` — number at merge time. Parallel
> sessions have collided on ADR numbers three times (0030/0034/0061); check
> every open PR's files, not just `ls docs/adr/`.

**Status:** Accepted

**Date:** 2026-07-06

## Context

An adversarial correctness audit of the session-coordination framework
(`.claude/coordination/`, ADR-0058) probed the PreToolUse hook for
false-ALLOWs (writes to `main` that slip through) and false-DENYs (legitimate
writes blocked). Every finding below was **reproduced against the real
`decide()`** before being fixed, and each fix carries a test that failed
before and passes after.

Confirmed false-ALLOWs (worst first):

1. **Only the first git write in a compound command was checked.**
   `git -C <wt> commit && git commit` resolved the worktree for the first
   write and returned — the second commit, running in cwd (`main`), was never
   examined.
2. **Push refspecs targeting `main` were invisible.** The deny keyed only on
   the *checked-out* branch, so `git push origin main`, `feat:main`,
   `HEAD:refs/heads/main`, and the deletion `:main` all updated remote `main`
   from any feature branch — bypassing PR review entirely.
3. **`_GIT_WRITE_SUBCMDS` was only `{commit, push}`.** `git checkout main &&
   git merge feat/x` — the single most plausible agent way to land work on
   main without a PR — was allowed, as were `rebase`, `cherry-pick`, and
   `revert` on main.
4. **A single `&` was not a separator.** `cd <wt> & git commit` (an `&&`
   typo) backgrounds the `cd`; the commit runs in cwd (main), but the hook
   resolved the worktree and allowed it.
5. **`--work-tree=`/`--git-dir=` were skipped as generic options**, so a
   write landing in another tree fell back to cwd — the *unsafe* direction
   when cwd is a feature worktree.
6. **A junction/symlink from outside the repo into it defeated the
   `in_repo` check** (string `relpath` on the link-spelled path escapes with
   `../`), making main writable through a link. Reproduced with an
   unprivileged Windows junction.
7. **NotebookEdit was not in the hook matcher at all** — `.ipynb` writes to
   repo files on main bypassed everything.

Confirmed false-DENY:

8. **A commit in an unrelated repo whose branch is named `main`** (e.g. a
   scratch clone in the temp dir — git's default init branch) was denied with
   a misleading message about *our* read-only main.

Registry integrity:

9. **`os.replace` in `save_registry` fails with `PermissionError` on Windows
   while any concurrent process holds `claims.json` open for reading**
   (CRT opens lack `FILE_SHARE_DELETE`; reproduced). The hook reads the
   registry on every tool call of every session, so collisions are routine;
   a failed save also littered the orphan `.tmp.<pid>` file.

## Decision

All changes confined to `.claude/coordination/` session tooling, its tests,
and the hook matcher — no product code.

1. **One parser, every write:** `_git_subcommands` + `_git_cmd_dir` are
   unified into `_git_writes(cmd)`, yielding `(subcmd, dir, args)` for
   **every** git write in the command. `decide()` branch-checks each write's
   own target dir (deduped), so no write hides behind another's.
2. **`_pushes_to_main(args)`:** a push whose refspec updates remote `main`
   (`main`, `+feat:main`, `HEAD:refs/heads/main`, `:main`) is denied from
   *any* branch. `main:feat` (main as source) stays allowed. A remote
   literally named `main` can false-match — accepted rarity, FORCE recourse.
3. **Write set widened to `{commit, push, merge, rebase, cherry-pick,
   revert}`** — the commit-creating porcelain agents actually use. `pull` is
   deliberately excluded: an ff-pull is the sanctioned way to update main
   (it is what the SessionStart hook itself does).
4. **`&` added to the separator split**, resetting the carried `cd` like
   `|`/`||` (a backgrounded `cd` never affects the next command's cwd).
5. **`--work-tree` / `--git-dir` (both `=` and space forms) resolve the
   write's dir** (`--git-dir`'s parent), same as `-C`.
6. **`realpath` before the repo-relative classification** in the
   Edit/Write path and in `_foreign_repo`'s prefix check, so junctions and
   symlinks classify by where the write physically lands.
7. **`NotebookEdit` added** to the PreToolUse matcher
   (`.claude/settings.json`) and to `decide()` (`notebook_path` treated like
   `file_path`).
8. **`_foreign_repo(target, root)`:** a target that *provably* belongs to a
   different git repo (its `--git-common-dir` root ≠ the coordination root)
   is exempt from the main/branch-claim checks. Conservative: paths under
   the root, non-repo dirs, and git failures all still count as ours.
9. **`save_registry` retries `os.replace`** (5 × 20 ms) on `PermissionError`
   and removes the orphan `.tmp` before re-raising on final failure
   (callers fail open, unchanged).

## Consequences

### Positive

- The read-only-`main` invariant now holds for compound commands, push
  refspecs, merge-class porcelain, linked paths, and notebook edits — each
  previously a reproduced bypass.
- Scratch-repo work in the temp dir no longer trips a misleading deny.
- Registry saves no longer fail (or litter `.tmp` files) under routine
  cross-session read/write collisions on Windows.
- Verified three ways: 26 new unit tests (each red before the fix), the
  full suite (1757 passed, 1 skipped), and a real-git subprocess dry-run
  against the live main tree + a linked worktree (9/9 correct, #136
  pinned-cwd protections intact, real `claims.json` untouched).

### Negative / accepted trade-offs

- `git merge --ff-only origin/main` *on main* is now denied (previously
  allowed). The sanctioned update paths — `git pull` and the SessionStart
  ff-pull — remain open; FORCE covers the rest.
- A remote named `main`, or `push -o main`, false-denies. Accepted rarity.
- Still best-effort parsing (unchanged ceiling, ADR-0058): `sh -c "git
  commit"`, `$var` indirection, command substitution, `GIT_DIR=… git commit`
  env prefixes, redirection file-writes (`echo > file`), and plumbing ref
  writers (`update-ref`, `branch -f`, forced fetch refspecs) are not parsed.
  The hook is a guardrail against common agent mistakes, not a security
  boundary; full shell emulation is the rejected bug farm.

## Alternatives considered

1. **Recursing into `sh -c '…'` strings.** Rejected (YAGNI): agents run Bash
   directly; blind recursion into quoted tokens re-creates the
   `git log --grep="git commit"` false-positive class ADR-0058 fixed.
2. **Parsing redirections to catch `echo x > file.py` on main.** Rejected as
   over-build — same reasoning as ADR-0058 alternative 3; agents are steered
   to Edit/Write, which are covered.
3. **Replacing the lock-file mutex with OS-level advisory locks**
   (`msvcrt.locking`/`fcntl.flock`) to close the stale-lock steal race in
   `registry._acquire_lock` (mtime-check + unlink is not atomic → two
   processes can both "own" the lock → lost update). Out of the autonomous
   bucket: a locking redesign, proposed separately in the audit deliverable;
   consequence today is a benign lost heartbeat/claim update that TTL +
   next-heartbeat self-heal.

## Related decisions

- [ADR-0058](0058-coord-hook-target-resolution.md) — target-based
  branch/tree resolution; this ADR extends its write coverage and keeps its
  resolution model and documented parsing ceiling.
- [ADR-0002](0002-arcpy-free-core-invariant.md) — untouched; pure-stdlib
  session tooling under `.claude/`.

## Issues/PRs

- Also fixes issue #169 (non-hermetic `test_edit_claimed_file_warns` — the
  one-line `branch_func` override every sibling test already had).
- Implementation: `.claude/coordination/hook_check.py`,
  `.claude/coordination/registry.py`, `.claude/settings.json`,
  `tests/coordination/test_hook_check.py`,
  `tests/coordination/test_registry.py`.
