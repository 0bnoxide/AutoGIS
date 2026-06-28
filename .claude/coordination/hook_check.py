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


def decide(payload, reg_path, branch_func=None):
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
            branch = bf(cwd)
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
