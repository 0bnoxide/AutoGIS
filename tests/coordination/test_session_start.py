import io
import json
import sys

import pytest
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


def test_additional_context_appends_mnemoverse_retrieval(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    monkeypatch.setattr(registry, "repo_root", lambda cwd=None: str(tmp_path))
    ctx = session_start.additional_context(
        {"session_id": "s1", "cwd": str(tmp_path)}, p, "memory context")
    assert ctx.endswith("memory context")


def test_mnemoverse_context_batches_three_queries_and_deduplicates():
    calls = {}

    def open_url(request, timeout):
        calls["request"] = request
        calls["timeout"] = timeout
        response = {
            "results": [
                {"items": [{"atom_id": "a1", "content": "handoff"}]},
                {"items": [{"atom_id": "a2", "content": "blocker"}]},
                {"items": [{"atom_id": "a1", "content": "handoff"}]},
            ]
        }
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    ctx = session_start.mnemoverse_context(
        {"MNEMOVERSE_API_KEY": "test-key",
         "MNEMOVERSE_API_URL": "https://memory.test/v1/"},
        open_url,
    )

    request = calls["request"]
    body = json.loads(request.data)
    assert request.full_url == "https://memory.test/v1/memory/read-batch"
    assert request.get_header("X-api-key") == "test-key"
    assert request.get_header("User-agent") == "AutoGIS-SessionStart/1.0"
    assert calls["timeout"] == 5
    assert [query["query"] for query in body["queries"]] == [
        "STATUS handoff", "BLOCKER", "DECISION"]
    assert all(query["domain"] == "collab:autogis"
               for query in body["queries"])
    assert all(query["include_associations"] is True
               for query in body["queries"])
    assert ctx.count("atom_id=a1") == 1
    assert "[STATUS handoff, DECISION]" in ctx
    assert "atom_id=a2" in ctx


def test_mnemoverse_context_fails_open_without_key_or_network():
    fallback = session_start.mnemoverse_context({})
    assert "retrieval unavailable" in fallback
    assert "run the ADR-0095 reads manually" in fallback

    def unavailable(request, timeout):
        raise OSError("offline")

    assert session_start.mnemoverse_context(
        {"MNEMOVERSE_API_KEY": "test-key"}, unavailable) == fallback


def test_mnemoverse_context_fails_open_on_invalid_response():
    def invalid(request, timeout):
        response = {"results": [{"items": []}, None, {"items": []}]}
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    ctx = session_start.mnemoverse_context(
        {"MNEMOVERSE_API_KEY": "test-key"}, invalid)
    assert "retrieval unavailable" in ctx


def test_main_emits_session_start_additional_context(
        tmp_path, monkeypatch, capsys):
    payload = {"cwd": str(tmp_path), "hook_event_name": "SessionStart"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(
        session_start, "mnemoverse_context", lambda: "memory context")

    with pytest.raises(SystemExit) as stopped:
        session_start.main()

    assert stopped.value.code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert output["hookSpecificOutput"]["additionalContext"].endswith(
        "memory context")
