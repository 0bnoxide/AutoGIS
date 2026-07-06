"""PreToolUse coordination hook — deny wrong-branch/main commits, warn on
claimed-file edits. Pure decision logic in decide(); main() handles I/O.
Fails open: any error → allow (exit 0, no output).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

# git global options that consume a following token as their argument, so the
# real subcommand is the token *after* the argument (e.g. `git -C /repo commit`).
_GLOBAL_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree",
                         "--namespace", "--exec-path", "--super-prefix"}
_GIT_WRITE_SUBCMDS = {"commit", "push"}


def _git_subcommands(cmd):
    """Yield the git subcommand for each `git ...` invocation in a shell command.

    Splits on shell separators and tokenizes, so the operative subcommand is
    identified by position (first non-option token after `git`), not by mere
    presence of the word. `git log --grep=commit` yields 'log', not 'commit'.
    """
    for seg in re.split(r"&&|\|\||;|\||\n", cmd):
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        if "git" not in toks:
            continue
        i = toks.index("git") + 1
        while i < len(toks):
            t = toks[i]
            if t.startswith("-"):
                i += 2 if t in _GLOBAL_OPTS_WITH_ARG else 1
                continue
            yield t
            break


def _is_git_write(cmd):
    return any(s in _GIT_WRITE_SUBCMDS for s in _git_subcommands(cmd))


def _deny(reason):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}


def _warn(msg):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": msg}}


def _git_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except Exception:
        return ""


def _first_existing(d):
    """Nearest existing ancestor of directory d (d itself if it exists), so a
    new file in a not-yet-created package still resolves via its worktree
    instead of failing `git -C` to ''."""
    d = os.path.abspath(d)
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return d


def _git_cmd_dir(cmd):
    """Effective directory the git *write* runs in, parsed from a Bash command:
    the write's `git -C <path>` argument, or a leading `cd <path>` carried across
    &&/;/newline segments, else '' (caller falls back to cwd). A *read* git
    (log/diff/...) does not count — its `-C` must not leak to the write, and its
    presence must not stop the scan (matches _is_git_write, which keys on the
    write subcommand too). Only sequential separators carry the cd. Best-effort —
    subshells, $vars, and command substitution fall through to cwd."""
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
                    dashC = toks[i + 1]          # this invocation's -C
                    i += 2
                    continue
                if t.startswith("-"):            # skip option (+ arg), same rule
                    i += 2 if t in _GLOBAL_OPTS_WITH_ARG else 1  # as _git_subcommands
                    continue
                sub = t                          # first non-option token = subcmd
                break
            if sub in _GIT_WRITE_SUBCMDS:
                return dashC or cur              # only the WRITE's dir counts
            # read git — its -C doesn't count; keep scanning later segments
    return cur


def _target_dir(tool, ti, cwd):
    """Directory the write actually lands in — not payload cwd, which is stale
    for pinned-cwd subagents. Edit/Write: the edited file's own dir (structured,
    exact). Bash: the dir the git command runs in (parsed cd/-C, else cwd)."""
    if tool in ("Edit", "Write", "MultiEdit"):
        fp = ti.get("file_path", "")
        d = os.path.dirname(os.path.abspath(fp)) if fp else cwd
    elif tool == "Bash":
        parsed = _git_cmd_dir(ti.get("command", ""))
        d = os.path.join(cwd, parsed) if parsed else cwd   # abs parsed wins
    else:
        d = cwd
    return _first_existing(d)


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
    # (e.g. '../.git' from a subdir), so resolve both against d before compare.
    # One subprocess returns both lines; a git error → '' → [] → False (fail-open).
    out = _rev_parse(d, "--git-dir", "--git-common-dir").splitlines()
    if len(out) != 2:
        return False

    def _abs(p):
        p = p.strip()
        return os.path.normcase(os.path.abspath(
            p if os.path.isabs(p) else os.path.join(d, p)))

    return _abs(out[0]) == _abs(out[1])


def _shared_tree_warn(reg_path, sid, target, cwd, main_tree_func=None):
    """Soft (non-blocking) nudge when another live session shares this main
    working tree AND the write targets it — the gotcha-#1 HEAD-churn condition.
    Registry read FIRST (cheap); git only under real contention."""
    import registry
    sharers = registry.tree_sharers(reg_path, sid, registry.repo_root(cwd))
    if not sharers:
        return None
    if not (main_tree_func or _in_main_tree)(target):
        return None
    return _warn(
        "[coord] %d other session(s) share this main working tree and this write "
        "targets it — concurrent checkouts here can move your HEAD onto the wrong "
        "branch. Isolate: EnterWorktree, then "
        "'python .claude/coordination/coord_cli.py resync'." % len(sharers))


def decide(payload, reg_path, branch_func=None, main_tree_func=None):
    if os.environ.get("AUTOGIS_COORD_FORCE") == "1":
        return None
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}

    # Best-effort: refresh this session's own heartbeat on any tool call.
    try:
        registry.heartbeat(reg_path, sid)
    except Exception:
        pass

    if tool in ("Edit", "Write", "MultiEdit"):
        fp = ti.get("file_path", "")
        if fp:
            # Edit/Write send absolute paths in production, but file_glob claims
            # are repo-relative — make the path relative to the repo root
            # (reg_path is <root>/.claude/coordination/claims.json) before match.
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(reg_path))))
            rel = fp
            if os.path.isabs(fp):
                try:
                    rel = os.path.relpath(fp, root)
                except ValueError:
                    rel = fp
            rel = rel.replace("\\", "/")
            # 'main' is read-only: block writes to files INSIDE the repo. Paths
            # outside the repo (memory dir, scratchpad — rel escapes with ../ or
            # stays absolute on a cross-drive relpath) are always allowed.
            in_repo = not rel.startswith("../") and not os.path.isabs(rel)
            if in_repo:
                bf = branch_func or _git_branch
                target = _target_dir(tool, ti, cwd)
                if (bf(target) or bf(cwd)) == "main":   # target, not stale cwd
                    return _deny(
                        "[coord] 'main' is read-only — writing %s is blocked. "
                        "Only reading is allowed on main. Check out a feature "
                        "branch and claim your files via the session-coordination "
                        "framework before writing (see CLAUDE.md > Worktrees & "
                        "session coordination). Override: AUTOGIS_COORD_FORCE=1."
                        % fp)
                warn = _shared_tree_warn(reg_path, sid, target, cwd,
                                         main_tree_func)
                if warn:
                    return warn
            conflicts = registry.file_conflicts(reg_path, sid, rel)
            if conflicts:
                c = conflicts[0]
                return _warn(
                    "[coord] %s is claimed by session %s (pattern %s). "
                    "Coordinate before editing." % (fp, c["session_id"][:8],
                                                     c.get("value")))
        return None

    if tool == "Bash":
        cmd = ti.get("command", "")
        if _is_git_write(cmd):
            bf = branch_func or _git_branch
            target = _target_dir(tool, ti, cwd)
            branch = bf(target) or bf(cwd)          # target, not stale cwd
            if branch == "main":
                return _deny(
                    "[coord] Direct commit/push to 'main' is blocked. Use a "
                    "feature branch + PR. Override: AUTOGIS_COORD_FORCE=1.")
            conflicts = registry.branch_conflicts(reg_path, sid, branch)
            if conflicts:
                c = conflicts[0]
                return _deny(
                    "[coord] Branch '%s' is claimed by session %s (pid %s). "
                    "You may be on the wrong branch. "
                    "Override: AUTOGIS_COORD_FORCE=1."
                    % (branch, c["session_id"][:8], c.get("pid")))
            warn = _shared_tree_warn(reg_path, sid, target, cwd, main_tree_func)
            if warn:
                return warn
        return None

    return None


def _reg_path(payload):
    # registry.py is always a sibling of this hook; import it relative to
    # __file__ (robust regardless of cwd / worktree). The shared registry FILE,
    # however, lives at the canonical MAIN-tree root so all worktree sessions
    # share one claims.json — registry.claims_path resolves that via git.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry
    return registry.claims_path(payload.get("cwd"))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        out = decide(payload, _reg_path(payload))
    except Exception:
        sys.exit(0)
    if out:
        print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
