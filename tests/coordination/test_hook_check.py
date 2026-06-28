import json
import registry
import hook_check


def _payload(tool, ti, sid="me", cwd="/repo"):
    return {"session_id": sid, "cwd": cwd, "tool_name": tool, "tool_input": ti}


def test_commit_to_main_is_denied(tmp_path):
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": "git commit -m x"}),
                            p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "main" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_commit_to_other_sessions_branch_denied(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "other", "branch", "feat/x")
    out = hook_check.decide(_payload("Bash", {"command": "git commit -m x"}),
                            p, branch_func=lambda cwd: "feat/x")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_commit_to_own_branch_allowed(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "me", "branch", "feat/x")
    out = hook_check.decide(_payload("Bash", {"command": "git commit -m x"}),
                            p, branch_func=lambda cwd: "feat/x")
    assert out is None


def test_non_git_bash_allowed(tmp_path):
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": "ls -la"}),
                            p, branch_func=lambda cwd: "main")
    assert out is None


def test_edit_claimed_file_warns(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "other", "file_glob", "autogis/adapters/cli.py")
    out = hook_check.decide(
        _payload("Edit", {"file_path": "autogis/adapters/cli.py"}), p)
    assert "additionalContext" in out["hookSpecificOutput"]
    assert "permissionDecision" not in out["hookSpecificOutput"]


def test_force_env_bypasses(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGIS_COORD_FORCE", "1")
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": "git commit -m x"}),
                            p, branch_func=lambda cwd: "main")
    assert out is None
