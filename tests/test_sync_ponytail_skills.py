"""Cover the mirror semantics of .claude/scripts/sync-ponytail-skills.sh.

The script vendors the ponytail plugin skills into the Claude Code and Codex
repo locations so cloud/remote sessions get the same set.
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


def _bash_works() -> bool:
    """A *functional* POSIX bash, not just any `bash` on PATH.

    windows-latest resolves bare `bash` to the WSL launcher
    (C:\\Windows\\System32\\bash.exe), which has no distro installed and exits
    nonzero on every call — present, so `which` finds it, but unusable. Probe it
    with a trivial command so these tests skip there instead of failing.
    """
    exe = shutil.which("bash")
    if exe is None:
        return False
    try:
        return subprocess.run(
            [exe, "-c", "exit 0"], capture_output=True, timeout=30
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(
    not _bash_works(),
    reason="a functional POSIX bash is required (windows-latest exposes only the WSL stub)",
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


def test_default_mirrors_claude_and_codex_locations(tmp_path):
    """Without the test override, both supported repo skill locations stay equal."""
    cache = tmp_path / "cache"
    _skill(cache / "4.8.4" / "skills", "ponytail", "core")
    repo = tmp_path / "repo"
    script = repo / ".claude" / "scripts" / SCRIPT.name
    script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script)

    args = ["bash", script.as_posix()]
    env = {
        "PONYTAIL_CACHE_ROOT": cache.as_posix(),
        "PATH": __import__("os").environ["PATH"],
    }
    assert subprocess.run(args, env=env, capture_output=True, text=True).returncode == 0
    for vendor in (repo / ".claude" / "skills", repo / ".agents" / "skills"):
        assert (vendor / "ponytail" / "SKILL.md").read_text(encoding="utf-8") == "core"

    assert subprocess.run(
        args + ["--check"], env=env, capture_output=True, text=True
    ).returncode == 0


def test_committed_claude_and_codex_skills_match():
    """The two checked-in copies cannot drift when the upstream plugin is absent."""
    repo = SCRIPT.parent.parent.parent

    def files(root):
        return {
            path.relative_to(root): path.read_bytes()
            for path in root.glob("ponytail*/**/*")
            if path.is_file()
        }

    assert files(repo / ".claude" / "skills") == files(repo / ".agents" / "skills")


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
