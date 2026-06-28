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
