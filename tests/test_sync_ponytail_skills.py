"""Cover the mirror semantics of .claude/scripts/sync-ponytail-skills.sh.

The script vendors the ponytail plugin skills into the repo so cloud/remote
sessions (which don't inherit user-scope plugin installs) get the same set.
A plain `cp -R` overlay would let an upstream deletion linger while the tool
reported "synced"/"clean" (PR #247 review, [P2]). These tests pin the two
reproduced failure modes plus the base mirror, driving the script through its
PONYTAIL_CACHE_ROOT / PONYTAIL_VENDOR_DIR env seams.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".claude" / "scripts" / "sync-ponytail-skills.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash required to run the sync shell script"
)


def _skill(root: Path, name: str, body: str = "x") -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def _run(cache_root: Path, vendor: Path, check: bool):
    args = ["bash", SCRIPT.as_posix()] + (["--check"] if check else [])
    return subprocess.run(
        args,
        env={
            "PONYTAIL_CACHE_ROOT": cache_root.as_posix(),
            "PONYTAIL_VENDOR_DIR": vendor.as_posix(),
            "PATH": __import__("os").environ["PATH"],
        },
        capture_output=True,
        text=True,
    )


@pytest.fixture
def dirs(tmp_path):
    """A plugin cache with one version shipping two ponytail skills, + an empty
    vendor dir."""
    cache = tmp_path / "cache"
    src = cache / "4.8.4" / "skills"
    _skill(src, "ponytail", "core")
    _skill(src, "ponytail-audit", "audit")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    return cache, vendor, src


def test_base_mirror(dirs):
    cache, vendor, _ = dirs
    assert _run(cache, vendor, check=True).returncode == 1  # empty vendor = drift
    assert _run(cache, vendor, check=False).returncode == 0
    assert (vendor / "ponytail" / "SKILL.md").read_text(encoding="utf-8") == "core"
    assert (vendor / "ponytail-audit" / "SKILL.md").read_text(encoding="utf-8") == "audit"
    assert _run(cache, vendor, check=True).returncode == 0  # now clean


def test_prunes_upstream_deleted_file(dirs):
    """Case A: a file removed upstream must not linger in a vendored skill."""
    cache, vendor, _ = dirs
    _run(cache, vendor, check=False)
    stale = vendor / "ponytail" / "EXTRA.md"
    stale.write_text("stale", encoding="utf-8")
    assert _run(cache, vendor, check=True).returncode == 1  # detected
    _run(cache, vendor, check=False)
    assert not stale.exists()                               # and removed
    assert _run(cache, vendor, check=True).returncode == 0


def test_prunes_removed_skill(dirs):
    """Case B: a skill removed upstream (destination-only dir) must be pruned,
    and must register as drift — not a false 'clean'."""
    cache, vendor, _ = dirs
    _run(cache, vendor, check=False)
    _skill(vendor, "ponytail-removed", "gone")
    assert _run(cache, vendor, check=True).returncode == 1  # not a false clean
    _run(cache, vendor, check=False)
    assert not (vendor / "ponytail-removed").exists()       # pruned
    assert _run(cache, vendor, check=True).returncode == 0


def test_leaves_non_ponytail_skills_untouched(dirs):
    """The mirror owns ponytail* only — sibling vendored skills are off-limits."""
    cache, vendor, _ = dirs
    _skill(vendor, "new-adr", "keep")
    _run(cache, vendor, check=False)
    assert (vendor / "new-adr" / "SKILL.md").read_text(encoding="utf-8") == "keep"
    assert _run(cache, vendor, check=True).returncode == 0
