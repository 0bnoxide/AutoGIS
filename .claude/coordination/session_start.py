"""SessionStart coordination hook — auto-claim the current branch + worktree
for this session so other sessions' PreToolUse checks can see it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def _git_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except Exception:
        return ""


def claim_session(payload, reg_path, branch_func=None):
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    if not sid:
        return []
    made = []
    bf = branch_func or _git_branch
    branch = bf(cwd)
    if branch:
        made.append(registry.claim(reg_path, sid, "branch", branch))
    made.append(registry.claim(reg_path, sid, "worktree", os.path.abspath(cwd)))
    try:
        registry.reap_stale(reg_path)
    except Exception:
        pass
    return made


def _reg_path(payload):
    # See hook_check._reg_path: import registry relative to __file__, but locate
    # the shared claims.json at the canonical main-tree root (worktree-safe).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry
    return registry.claims_path(payload.get("cwd"))


_POLICY = (
    "[coord] BRANCH POLICY — 'main' is READ-ONLY. On main only reading is "
    "allowed; any write (Edit/Write/MultiEdit to a repo file, git commit/push) "
    "is blocked by the PreToolUse hook. Before doing any work: check out a "
    "feature branch and claim it + your files via the session-coordination "
    "framework (see CLAUDE.md > Worktrees & session coordination). This applies "
    "to subagents too — the hook enforces it for every tool call regardless of "
    "who makes it, so pass this rule along when you dispatch one. Override for a "
    "one-off: AUTOGIS_COORD_FORCE=1, exported before the session/hook launches "
    "(an inline per-command prefix cannot reach the hook process). Pinned-cwd "
    "subagents: use 'coord_cli.py whoami|release-mine|resync' instead."
)


def additional_context(payload, reg_path):
    """The SessionStart additionalContext: the standing policy, plus a one-time
    nudge to isolate into a worktree when another live session already shares
    this main working tree (the gotcha-#1 contention condition)."""
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    sharers = registry.tree_sharers(reg_path, sid, registry.repo_root(cwd)) \
        if sid else []
    if not sharers:
        return _POLICY
    nudge = (
        "[coord] %d other session(s) share this main working tree. Concurrent "
        "checkouts here will move your HEAD. Isolate now: EnterWorktree, then "
        "run 'python .claude/coordination/coord_cli.py resync'."
        % len(sharers))
    return _POLICY + "\n\n" + nudge


def main():
    context = _POLICY
    try:
        payload = json.load(sys.stdin)
        reg_path = _reg_path(payload)
        claim_session(payload, reg_path)
        context = additional_context(payload, reg_path)
    except Exception:
        pass
    # State the read-only-main policy (+ nudge, if contended) as session
    # context (main session only; subagents are covered by the hook itself).
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
