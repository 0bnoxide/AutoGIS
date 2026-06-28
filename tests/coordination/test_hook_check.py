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


# --- _is_git_write tokenizer: real subcommand, not mere word presence ---

def test_git_log_grep_commit_not_denied(tmp_path):
    # 'commit' appears as a --grep argument; subcommand is 'log' → allow.
    p = tmp_path / "c.json"
    out = hook_check.decide(
        _payload("Bash", {"command": "git log --grep=commit"}),
        p, branch_func=lambda cwd: "main")
    assert out is None


def test_git_diff_push_pathspec_not_denied(tmp_path):
    p = tmp_path / "c.json"
    out = hook_check.decide(
        _payload("Bash", {"command": "git diff -- push.py"}),
        p, branch_func=lambda cwd: "main")
    assert out is None


def test_git_C_global_option_commit_denied(tmp_path):
    # `git -C <path> commit` — global option with arg before the subcommand.
    p = tmp_path / "c.json"
    out = hook_check.decide(
        _payload("Bash", {"command": "git -C /repo commit -m x"}),
        p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_git_commit_in_compound_command_denied(tmp_path):
    p = tmp_path / "c.json"
    out = hook_check.decide(
        _payload("Bash", {"command": "ls && git commit -m 'fix push bug'"}),
        p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_git_push_denied(tmp_path):
    p = tmp_path / "c.json"
    out = hook_check.decide(
        _payload("Bash", {"command": "git push origin main"}),
        p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- absolute file path is made repo-relative before glob match ---

def test_absolute_edit_path_matches_relative_glob(tmp_path):
    # reg_path must sit at <root>/.claude/coordination/claims.json so the hook
    # can derive the repo root and relativize the absolute file_path.
    coord = tmp_path / ".claude" / "coordination"
    coord.mkdir(parents=True)
    p = coord / "claims.json"
    registry.claim(p, "other", "file_glob", "autogis/adapters/cli.py")
    abs_fp = str(tmp_path / "autogis" / "adapters" / "cli.py")
    out = hook_check.decide(_payload("Edit", {"file_path": abs_fp}), p)
    assert "additionalContext" in out["hookSpecificOutput"]
