"""coord — manual inspection/override CLI for the coordination registry.

Usage:
  python coord_cli.py list
  python coord_cli.py claim --session SID --kind branch|worktree|file_glob --value V
  python coord_cli.py release --session SID [--kind K] [--value V]
  python coord_cli.py whoami [--session SID]
  python coord_cli.py release-mine [--session SID]
  python coord_cli.py resync [--session SID]

whoami/release-mine/resync resolve the session id via resolve_sid(): explicit
--session wins, then $AUTOGIS_SESSION_ID (set by session-start.sh), then a
cwd->claim fallback that only works from an already-claimed worktree in
steady state. resync in particular needs --session or the env var — it is run
immediately after EnterWorktree, before the new worktree has a claim, so the
cwd fallback cannot resolve it.

resync releases only this session's branch/worktree claims before reclaiming
the new ones -- unlike release-mine, it does NOT drop file_glob claims. A
worktree move is not an abandonment of in-flight file locks (#159).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_UNRESOLVED = ("could not resolve session id "
              "(set AUTOGIS_SESSION_ID or pass --session)")


def resolve_sid(reg_path, cwd, env, explicit=None):
    if explicit:
        return explicit                          # caller knows its sid
    sid = env.get("AUTOGIS_SESSION_ID")
    if sid:
        return sid                               # set by session-start.sh (3a)
    # Last-resort fallback: the live `worktree` claim whose value == abspath(cwd).
    # Unique to one session ONLY in a steady-state, already-claimed worktree.
    import registry
    root = os.path.abspath(cwd)
    matches = [c["session_id"] for c in registry.list_claims(reg_path)
               if c.get("kind") == "worktree"
               and c.get("session_id")
               and registry.samepath(c.get("value", ""), root)]
    return matches[0] if len(matches) == 1 else None


def run(argv, reg_path, cwd=None, env=None, branch_func=None):
    import registry
    cwd = os.getcwd() if cwd is None else cwd
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="coord")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pc = sub.add_parser("claim")
    pc.add_argument("--session", required=True)
    pc.add_argument("--kind", required=True,
                    choices=["branch", "worktree", "file_glob"])
    pc.add_argument("--value", required=True)
    pr = sub.add_parser("release")
    pr.add_argument("--session", required=True)
    pr.add_argument("--kind")
    pr.add_argument("--value")
    sub.add_parser("whoami").add_argument("--session")
    sub.add_parser("release-mine").add_argument("--session")
    sub.add_parser("resync").add_argument("--session")
    sub.add_parser("reserve-adr").add_argument("--session")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for c in registry.list_claims(reg_path, include_stale=True):
            stale = " (stale)" if registry.is_stale(c) else ""
            print("%-10s %-10s %s%s" % (c.get("session_id", "")[:10],
                                        c.get("kind"), c.get("value"), stale))
        return 0
    if args.cmd == "claim":
        registry.claim(reg_path, args.session, args.kind, args.value)
        return 0
    if args.cmd == "release":
        n = registry.release(reg_path, args.session, args.kind, args.value)
        print("released %d" % n)
        return 0

    if args.cmd == "whoami":
        sid = resolve_sid(reg_path, cwd, env, args.session)
        if not sid:
            print(_UNRESOLVED, file=sys.stderr)
            return 1
        print(sid)
        return 0

    if args.cmd == "release-mine":
        sid = resolve_sid(reg_path, cwd, env, args.session)
        if not sid:
            print(_UNRESOLVED, file=sys.stderr)
            return 1
        n = registry.release(reg_path, sid)
        print("released %d" % n)
        return 0

    if args.cmd == "resync":
        sid = resolve_sid(reg_path, cwd, env, args.session)
        if not sid:
            print(_UNRESOLVED, file=sys.stderr)
            return 1
        # Scoped to branch/worktree only -- resync moves a session between
        # worktrees, it doesn't abandon in-flight file_glob claims (#159).
        registry.release(reg_path, sid, "branch")
        registry.release(reg_path, sid, "worktree")
        import session_start
        bf = branch_func or session_start._git_branch
        branch = bf(cwd)
        if branch:
            registry.claim(reg_path, sid, "branch", branch)
        registry.claim(reg_path, sid, "worktree", os.path.abspath(cwd))
        print("resynced %s -> branch=%s worktree=%s"
              % (sid, branch or "(detached)", os.path.abspath(cwd)))
        return 0

    if args.cmd == "reserve-adr":
        sid = resolve_sid(reg_path, cwd, env, args.session)
        if not sid:
            print(_UNRESOLVED, file=sys.stderr)
            return 1
        # base = highest ADR in local files + open PRs (the skill owns that
        # scan); reserve_number atomically lifts it above any live reservation.
        n = registry.reserve_number(reg_path, sid, "adr", _adr_scan_base(cwd))
        print("%04d" % n)
        return 0

    return 1


def _own_tree():
    """The checkout coord_cli.py itself lives in. For a pinned/worktree session
    invoking the shared script, this is the *main* tree, not the caller's."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _git_toplevel(cwd):
    """Working-tree root of `cwd` (the *worktree*, not the main tree). "" if
    git is unavailable — callers fall back to coord_cli's own tree."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _adr_scan_base(cwd):
    """Max ADR number already used by local files + open PRs, via the new-adr
    skill's own scanner. 0 if it can't be imported (keeps reserve-adr working
    off reservations alone).

    Scan BOTH trees, because either can be ahead of the other:

    * coord_cli's own checkout — which is where the skill script lives, and for
      a pinned/worktree session is the shared *main* tree; and
    * the caller's worktree, resolved from `cwd`.

    Scanning only coord_cli's tree handed out a number the caller's worktree had
    already used, whenever main was behind the branch being reserved for (#425).
    """
    tree = _own_tree()
    sys.path.insert(0, os.path.join(tree, ".claude", "skills", "new-adr"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import next_adr_number
        from pathlib import Path
        base = next_adr_number._scan_max(Path(tree))
    except Exception:
        return 0
    # Widen to the caller's worktree in its OWN try: a failure here must not
    # discard the floor we already computed. Folding both into one try made a
    # git or registry hiccup return 0 — strictly less safe for reservation
    # than before the #425 fix.
    try:
        import registry
        caller = _git_toplevel(cwd)
        if caller and not registry.samepath(caller, tree):
            base = max(base, next_adr_number._local_max(
                Path(caller) / "docs" / "adr"))
    except Exception:
        pass
    return base


def _reg_path():
    # See hook_check._reg_path: import registry relative to __file__, but locate
    # the shared claims.json at the canonical main-tree root (worktree-safe).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry
    return registry.claims_path()


def main():
    sys.exit(run(sys.argv[1:], _reg_path()))


if __name__ == "__main__":
    main()
