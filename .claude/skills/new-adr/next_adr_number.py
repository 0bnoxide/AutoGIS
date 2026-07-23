#!/usr/bin/env python3
"""Pick the next free ADR number — checking local files AND open PRs.

Local `docs/adr/NNNN-*.md` only shows what's *merged*. Concurrent sessions
routinely pick the same NNNN and collide at merge (the 0099->0105 renumber is a
real example). This also scans open PR diffs for added `docs/adr/NNNN-*.md`.

Scope, honestly: this REDUCES collisions, it does not eliminate them. Two live
sessions that both grab NNNN *before either opens a PR* are invisible to a PR
scan — and that is exactly the recurring case. Fails soft: if `gh` is offline or
unauthed, it degrades to the local-only scan (still correct, just less
protective).

Usage:
    python next_adr_number.py          # prints next number, zero-padded (e.g. 0106)
    python next_adr_number.py --check   # run the self-check
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Legacy audit logs are dated `YYYY-MM-DD-*.md` — NOT sequential ADRs. A real
# ADR is `NNNN-<slug>.md` where <slug> does not start with `MM-DD`.
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NNNN = re.compile(r"^(\d{4})-")


def _num(name: str) -> int | None:
    """ADR number from a bare filename, or None if it isn't a numbered ADR."""
    if _DATED.match(name):
        return None
    m = _NNNN.match(name)
    return int(m.group(1)) if m else None


def _local_max(adr_dir: Path) -> int:
    return max(
        (n for p in adr_dir.glob("*.md") if (n := _num(p.name)) is not None),
        default=0,
    )


def _open_pr_max() -> int:
    """Max ADR number in files added by any open PR. 0 if gh is unavailable."""
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "200",
             "--json", "files"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        prs = json.loads(out)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return 0  # fail soft — local-only scan still ran
    best = 0
    for pr in prs:
        for f in pr.get("files", []):
            n = _num(Path(f.get("path", "")).name)
            if n is not None:
                best = max(best, n)
    return best


def next_adr_number(repo_root: Path | None = None) -> int:
    # This file lives at <root>/.claude/skills/new-adr/ OR
    # <root>/.agents/skills/new-adr/ — both put root at parents[3].
    root = repo_root or Path(__file__).resolve().parents[3]
    adr_dir = root / "docs" / "adr"
    return max(_local_max(adr_dir), _open_pr_max()) + 1


def _check() -> None:
    # ponytail: the parse / max / zero-pad is the only non-trivial logic — assert it.
    assert _num("0099-foo.md") == 99
    assert _num("0105-phase4-review.md") == 105
    assert _num("0088-3d-analyst-tools.md") == 88          # slug starting w/ digit
    assert _num("README.md") is None
    assert _num("TEMPLATE.md") is None
    assert _num("2026-06-18-agent-decisions.md") is None   # dated legacy, not ADR
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        adr = Path(d) / "docs" / "adr"
        adr.mkdir(parents=True)
        for n in ("0001-a.md", "0007-b.md", "README.md", "2026-01-01-x.md"):
            (adr / n).write_text("")
        assert _local_max(adr) == 7
        assert _local_max(Path(d) / "docs" / "missing") == 0   # absent dir -> 0
    print("next_adr_number self-check OK")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
    else:
        print(f"{next_adr_number():04d}")
