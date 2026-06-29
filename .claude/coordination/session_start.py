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
    "one-off: AUTOGIS_COORD_FORCE=1."
)


def main():
    try:
        payload = json.load(sys.stdin)
        claim_session(payload, _reg_path(payload))
    except Exception:
        pass
    # State the read-only-main policy as session context (main session only;
    # subagents are covered by the hook itself).
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": _POLICY}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
