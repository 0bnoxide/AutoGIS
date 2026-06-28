"""Process-level integration tests for the PreToolUse hook.

Runs hook_check.py as a real subprocess (as Claude Code would) to verify it
reads stdin, resolves the registry, and ALWAYS exits 0 — the fail-open
guarantee that must hold so the hook can never brick git.
"""
import json
import os
import subprocess
import sys

_HOOK = os.path.join(os.path.dirname(__file__), "..", "..",
                     ".claude", "coordination", "hook_check.py")


def _run_hook(payload, env):
    proc = subprocess.run([sys.executable, _HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout.strip()


def _project(tmp_path):
    os.makedirs(tmp_path / ".claude" / "coordination", exist_ok=True)
    os.makedirs(tmp_path / ".git", exist_ok=True)
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))


def test_hook_exits_zero_and_silent_for_safe_command(tmp_path):
    env = _project(tmp_path)
    payload = {"session_id": "me", "cwd": str(tmp_path), "tool_name": "Bash",
               "tool_input": {"command": "ls"}}
    code, out = _run_hook(payload, env)
    assert code == 0
    assert out == ""


def test_hook_fails_open_on_corrupt_registry(tmp_path):
    env = _project(tmp_path)
    reg = tmp_path / ".claude" / "coordination" / "claims.json"
    reg.write_text("{ not valid json", encoding="utf-8")
    payload = {"session_id": "me", "cwd": str(tmp_path), "tool_name": "Edit",
               "tool_input": {"file_path": str(tmp_path / "x.py")}}
    code, out = _run_hook(payload, env)
    # Corrupt registry must never block: exit 0, no deny emitted.
    assert code == 0
    assert "deny" not in out


def test_hook_handles_malformed_stdin(tmp_path):
    env = _project(tmp_path)
    proc = subprocess.run([sys.executable, _HOOK], input="not json at all",
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
