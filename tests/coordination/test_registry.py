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
