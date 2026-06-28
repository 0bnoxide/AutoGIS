"""coord — manual inspection/override CLI for the coordination registry.

Usage:
  python coord_cli.py list
  python coord_cli.py claim --session SID --kind branch|worktree|file_glob --value V
  python coord_cli.py release --session SID [--kind K] [--value V]
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def run(argv, reg_path):
    import registry
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
    return 1


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
