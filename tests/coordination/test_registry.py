import registry


def test_load_missing_returns_empty(tmp_path):
    assert registry.load_registry(tmp_path / "nope.json") == {"claims": []}


def test_save_then_load_roundtrips(tmp_path):
    p = tmp_path / "claims.json"
    data = {"claims": [{"session_id": "s1", "kind": "branch", "value": "feat/x"}]}
    registry.save_registry(p, data)
    assert registry.load_registry(p) == data


def test_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "claims.json"
    p.write_text("{ not json", encoding="utf-8")
    assert registry.load_registry(p) == {"claims": []}


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "claims.json"
    registry.save_registry(p, {"claims": []})
    leftovers = [f for f in os.listdir(tmp_path) if ".tmp." in f]
    assert leftovers == []


def test_save_registry_retries_replace_on_permissionerror(tmp_path, monkeypatch):
    # Windows: os.replace fails with PermissionError while a concurrent reader
    # holds claims.json open (CRT opens without FILE_SHARE_DELETE). Readers
    # hold it for a sub-ms json.load, so brief retries must absorb it.
    import pytest as _  # noqa: F401  (parallel import style with file tail)
    p = tmp_path / "claims.json"
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("held open by a reader")
        return real(src, dst)

    monkeypatch.setattr(registry.os, "replace", flaky)
    registry.save_registry(p, {"claims": []})
    assert calls["n"] == 3
    assert registry.load_registry(p) == {"claims": []}


def test_save_registry_final_failure_raises_and_leaves_no_tmp(tmp_path,
                                                              monkeypatch):
    import pytest
    p = tmp_path / "claims.json"

    def always_fails(src, dst):
        raise PermissionError("never released")

    monkeypatch.setattr(registry.os, "replace", always_fails)
    with pytest.raises(PermissionError):
        registry.save_registry(p, {"claims": []})
    # the orphaned .tmp.<pid> must be cleaned up, not littered
    assert [f for f in os.listdir(tmp_path) if ".tmp." in f] == []


import os
from datetime import timedelta


def test_claim_appends_entry(tmp_path):
    p = tmp_path / "c.json"
    entry = registry.claim(p, "s1", "branch", "feat/x", pid=111)
    assert entry["session_id"] == "s1"
    assert entry["kind"] == "branch"
    assert entry["value"] == "feat/x"
    assert entry["pid"] == 111
    assert "heartbeat_at" in entry and "started_at" in entry
    assert registry.list_claims(p) == [entry]


def test_claim_same_resource_refreshes_not_duplicates(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "branch", "feat/x")
    assert len(registry.list_claims(p, include_stale=True)) == 1


def test_is_stale_past_ttl(tmp_path):
    now = registry._now()
    fresh = {"heartbeat_at": registry._iso(now), "ttl_sec": 100}
    old = {"heartbeat_at": registry._iso(now - timedelta(seconds=200)),
           "ttl_sec": 100}
    assert registry.is_stale(fresh, now) is False
    assert registry.is_stale(old, now) is True


def test_list_claims_excludes_stale(tmp_path):
    now = registry._now()
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x", ttl_sec=100, now=now)
    later = now + timedelta(seconds=500)
    assert registry.list_claims(p, now=later) == []
    assert len(registry.list_claims(p, include_stale=True, now=later)) == 1


def test_reap_stale_removes_expired(tmp_path):
    now = registry._now()
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x", ttl_sec=100, now=now)
    later = now + timedelta(seconds=500)
    assert registry.reap_stale(p, now=later) == 1
    assert registry.list_claims(p, include_stale=True) == []


def test_heartbeat_refreshes_only_own_claims(tmp_path):
    now = registry._now()
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x", now=now)
    registry.claim(p, "s2", "branch", "feat/y", now=now)
    later = now + timedelta(seconds=300)
    assert registry.heartbeat(p, "s1", now=later) == 1
    claims = {c["session_id"]: c for c in registry.list_claims(p, include_stale=True)}
    assert claims["s1"]["heartbeat_at"] == registry._iso(later)
    assert claims["s2"]["heartbeat_at"] == registry._iso(now)


def test_release_all_for_session(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "worktree", "/wt/x")
    registry.claim(p, "s2", "branch", "feat/y")
    assert registry.release(p, "s1") == 2
    remaining = registry.list_claims(p, include_stale=True)
    assert len(remaining) == 1 and remaining[0]["session_id"] == "s2"


def test_release_specific_resource(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "worktree", "/wt/x")
    assert registry.release(p, "s1", kind="branch", value="feat/x") == 1
    remaining = registry.list_claims(p, include_stale=True)
    assert len(remaining) == 1 and remaining[0]["kind"] == "worktree"


def test_branch_conflicts_other_session(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    assert registry.branch_conflicts(p, "s2", "feat/x")[0]["session_id"] == "s1"
    assert registry.branch_conflicts(p, "s1", "feat/x") == []   # own claim
    assert registry.branch_conflicts(p, "s2", "feat/other") == []


def test_file_conflicts_glob_match(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "file_glob", "autogis/adapters/cli.py")
    registry.claim(p, "s1", "file_glob", "autogis/core/envmon/*.py")
    assert registry.file_conflicts(p, "s2", "autogis/adapters/cli.py")
    assert registry.file_conflicts(p, "s2", "autogis/core/envmon/normalize.py")
    assert registry.file_conflicts(p, "s2", "tests/test_x.py") == []
    assert registry.file_conflicts(p, "s1", "autogis/adapters/cli.py") == []  # own


# --- canonical registry-root resolution (worktree-safe) ---------------------
import os
import shutil
import subprocess

import pytest


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _norm(p):
    return os.path.normcase(os.path.realpath(str(p)))


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_claims_path_resolves_to_main_root_from_worktree(tmp_path, monkeypatch):
    """The shared registry must live at the MAIN working tree's root, even when
    resolved from inside a linked worktree AND even when CLAUDE_PROJECT_DIR
    points at the worktree (the exact failure that defeated cross-session
    locking). git-common-dir must win over the env var."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", cwd=main)
    _git("config", "user.email", "t@t.test", cwd=main)
    _git("config", "user.name", "t", cwd=main)
    (main / "f.txt").write_text("x", encoding="utf-8")
    _git("add", "-A", cwd=main)
    _git("commit", "-m", "init", cwd=main)
    wt = tmp_path / "wt"
    _git("worktree", "add", "-b", "feat/x", str(wt), cwd=main)

    # Simulate a worktree session: the env var points at the WRONG (worktree) root.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(wt))

    got = registry.claims_path(str(wt))
    root = os.path.dirname(os.path.dirname(os.path.dirname(got)))
    assert _norm(root) == _norm(main)          # git root beat CLAUDE_PROJECT_DIR
    assert _norm(wt) not in _norm(got)         # never the worktree's own copy
    assert got.endswith(os.path.join(".claude", "coordination", "claims.json"))


# --- tree_sharers (concurrent-main-tree nudge primitive) --------------------

def test_tree_sharers_excludes_own_session(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "worktree", "/main/root")
    registry.claim(p, "s2", "worktree", "/main/root")
    registry.claim(p, "s3", "worktree", "/other/root")
    sharers = registry.tree_sharers(p, "s1", "/main/root")
    assert [c["session_id"] for c in sharers] == ["s2"]


def test_tree_sharers_empty_when_alone(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "worktree", "/main/root")
    assert registry.tree_sharers(p, "s1", "/main/root") == []


def test_tree_sharers_ignores_orphan_claims(tmp_path):
    p = tmp_path / "c.json"
    data = registry.load_registry(p)
    data["claims"].append({"kind": "worktree", "value": "/main/root",
                           "heartbeat_at": registry._iso(registry._now()),
                           "ttl_sec": 1800})  # no session_id
    registry.save_registry(p, data)
    assert registry.tree_sharers(p, "s1", "/main/root") == []


def test_claims_path_falls_back_to_cwd_outside_git(tmp_path):
    """Outside any git repo and with no CLAUDE_PROJECT_DIR, resolution must not
    raise — it falls back to the given cwd (fail-soft, never bricks the hook)."""
    import os as _os
    prev = _os.environ.pop("CLAUDE_PROJECT_DIR", None)
    try:
        got = registry.claims_path(str(tmp_path))
        assert got.endswith(os.path.join(".claude", "coordination", "claims.json"))
    finally:
        if prev is not None:
            _os.environ["CLAUDE_PROJECT_DIR"] = prev
