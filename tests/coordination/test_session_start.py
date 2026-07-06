import registry
import session_start


def test_claims_branch_and_worktree(tmp_path):
    p = tmp_path / "c.json"
    payload = {"session_id": "s1", "cwd": "/wt/x"}
    made = session_start.claim_session(payload, p,
                                       branch_func=lambda cwd: "feat/x")
    kinds = sorted(c["kind"] for c in made)
    assert kinds == ["branch", "worktree"]
    live = registry.list_claims(p, include_stale=True)
    assert {c["kind"]: c["value"] for c in live}["branch"] == "feat/x"


def test_detached_head_claims_only_worktree(tmp_path):
    p = tmp_path / "c.json"
    payload = {"session_id": "s1", "cwd": "/wt/x"}
    made = session_start.claim_session(payload, p, branch_func=lambda cwd: "")
    assert [c["kind"] for c in made] == ["worktree"]


def test_no_session_id_is_noop(tmp_path):
    p = tmp_path / "c.json"
    made = session_start.claim_session({"cwd": "/wt/x"}, p,
                                       branch_func=lambda cwd: "feat/x")
    assert made == []


# --- additional_context nudge when the main tree is shared -------------------

def test_additional_context_nudges_when_tree_shared(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    monkeypatch.setattr(registry, "repo_root", lambda cwd=None: str(tmp_path))
    registry.claim(p, "s2", "worktree", str(tmp_path))
    ctx = session_start.additional_context(
        {"session_id": "s1", "cwd": str(tmp_path)}, p)
    assert "share this main working tree" in ctx
    assert ctx.startswith(session_start._POLICY)


def test_additional_context_no_nudge_when_alone(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    monkeypatch.setattr(registry, "repo_root", lambda cwd=None: str(tmp_path))
    ctx = session_start.additional_context(
        {"session_id": "s1", "cwd": str(tmp_path)}, p)
    assert ctx == session_start._POLICY
