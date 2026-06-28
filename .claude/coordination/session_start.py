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
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
    sys.path.insert(0, os.path.join(root, ".claude", "coordination"))
    return os.path.join(root, ".claude", "coordination", "claims.json")


def main():
    try:
        payload = json.load(sys.stdin)
        claim_session(payload, _reg_path(payload))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
