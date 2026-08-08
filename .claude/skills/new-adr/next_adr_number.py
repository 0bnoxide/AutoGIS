#!/usr/bin/env python3
"""Pick the next free ADR number — checking local files AND open PRs.

Local `docs/adr/NNNN-*.md` only shows what's *merged*. Concurrent sessions
routinely pick the same NNNN and collide at merge (the 0099->0105 renumber is a
real example). This also scans open PR diffs for added `docs/adr/NNNN-*.md`.

Scope, honestly: this REDUCES collisions, it does not eliminate them. Two live
sessions that both grab NNNN *before either opens a PR* are invisible to a PR
scan — and that is exactly the recurring case. Fails soft: if `gh` is offline,
unauthed, or (cloud/web sessions) not installed at all, it degrades to the
local-only scan and says so on stderr — the degraded answer is still printed,
but the caller can now tell it apart from a guarded one (#454).

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


_NO_GH_WARNING = (
    "warning: open-PR ADR scan did not run (no usable `gh` CLI: {why}). "
    "The number below is guarded by local files and live reservations ONLY — "
    "an ADR added by an already-open PR will NOT be seen. Verify against open "
    "PRs before use."
)


def _open_pr_max() -> int:
    """Max ADR number in files added by any open PR. 0 if gh is unavailable.

    Failing soft is right — the local scan still ran — but failing *silently*
    is not: the caller gets a confidently wrong number and cannot tell the
    degraded answer from the guarded one. Cloud/web sessions have no `gh` at
    all (GitHub is reached through MCP there), so this half of the scan is dark
    for a whole class of session; #454 is a live instance where it handed out a
    number an open PR already used. Warn on stderr so the degradation is
    visible to every caller, in-process or via subprocess, without changing the
    number printed on stdout.
    """
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "200",
             "--json", "files"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        prs = json.loads(out)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(_NO_GH_WARNING.format(why=type(exc).__name__), file=sys.stderr)
        return 0  # fail soft — local-only scan still ran
    best = 0
    for pr in prs:
        for f in pr.get("files", []):
            n = _num(Path(f.get("path", "")).name)
            if n is not None:
                best = max(best, n)
    return best


def _scan_max(root: Path) -> int:
    """Highest ADR number in local files + open PRs — no reservations, no +1."""
    return max(_local_max(root / "docs" / "adr"), _open_pr_max())


def _reserved_max() -> int:
    """Highest live ADR number reserved in the coordination registry (0 if the
    registry isn't reachable — e.g. a cloud checkout with no coordination dir).
    """
    try:
        coord = Path(__file__).resolve().parents[2] / "coordination"
        sys.path.insert(0, str(coord))
        import registry  # type: ignore
        vals = registry.live_values(registry.claims_path(), "adr")
    except Exception:
        return 0  # fail soft, same as gh being unavailable
    best = 0
    for v in vals:
        try:
            best = max(best, int(v))
        except (TypeError, ValueError):
            pass
    return best


def next_adr_number(repo_root: Path | None = None) -> int:
    # This file lives at <root>/.claude/skills/new-adr/ OR
    # <root>/.agents/skills/new-adr/ — both put root at parents[3].
    root = repo_root or Path(__file__).resolve().parents[3]
    return max(_scan_max(root), _reserved_max()) + 1


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

    # #454: gh absent must warn, not just quietly return 0.
    import contextlib
    import io
    real_run, err = subprocess.run, io.StringIO()
    try:
        def _boom(*_a, **_k):
            raise FileNotFoundError("gh")
        subprocess.run = _boom
        with contextlib.redirect_stderr(err):
            assert _open_pr_max() == 0
    finally:
        subprocess.run = real_run
    assert "open-PR ADR scan did not run" in err.getvalue()

    print("next_adr_number self-check OK")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
    elif "--base" in sys.argv:
        # Scan floor only (local + open PRs, no reservations, no +1) — the input
        # `coord reserve-adr` layers its atomic reservation on top of.
        print(_scan_max(Path(__file__).resolve().parents[3]))
    else:
        print(f"{next_adr_number():04d}")
