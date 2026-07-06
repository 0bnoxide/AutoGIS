import os

import registry
import coord_cli


def test_claim_then_list(tmp_path, capsys):
    p = tmp_path / "c.json"
    assert coord_cli.run(
        ["claim", "--session", "s1", "--kind", "file_glob",
         "--value", "autogis/adapters/cli.py"], p) == 0
    coord_cli.run(["list"], p)
    out = capsys.readouterr().out
    assert "s1" in out and "autogis/adapters/cli.py" in out


def test_release(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    assert coord_cli.run(["release", "--session", "s1"], p) == 0
    assert registry.list_claims(p, include_stale=True) == []


# --- resolve_sid (explicit > env > cwd-claim fallback) -----------------------

def test_resolve_sid_explicit_wins(tmp_path):
    assert coord_cli.resolve_sid(tmp_path / "c.json", "/wt", {}, explicit="s1") == "s1"


def test_resolve_sid_env_var(tmp_path):
    assert coord_cli.resolve_sid(tmp_path / "c.json", "/wt",
                                 {"AUTOGIS_SESSION_ID": "s2"}) == "s2"


def test_resolve_sid_cwd_fallback_single_match(tmp_path):
    p = tmp_path / "c.json"
    wt = str(tmp_path / "wt")
    registry.claim(p, "s3", "worktree", wt)
    assert coord_cli.resolve_sid(p, wt, {}) == "s3"


def test_resolve_sid_cwd_fallback_ambiguous_returns_none(tmp_path):
    p = tmp_path / "c.json"
    wt = str(tmp_path / "wt")
    registry.claim(p, "s3", "worktree", wt)
    registry.claim(p, "s4", "worktree", wt)
    assert coord_cli.resolve_sid(p, wt, {}) is None


def test_resolve_sid_ignores_orphan_claims(tmp_path):
    p = tmp_path / "c.json"
    wt = str(tmp_path / "wt")
    data = registry.load_registry(p)
    data["claims"].append({"kind": "worktree", "value": wt,
                           "heartbeat_at": registry._iso(registry._now()),
                           "ttl_sec": 1800})  # no session_id
    registry.save_registry(p, data)
    assert coord_cli.resolve_sid(p, wt, {}) is None


# --- whoami / release-mine / resync subcommands ------------------------------

def test_whoami_prints_resolved_sid(tmp_path, capsys):
    p = tmp_path / "c.json"
    assert coord_cli.run(["whoami", "--session", "s1"], p) == 0
    assert capsys.readouterr().out.strip() == "s1"


def test_whoami_unresolved_exits_nonzero(tmp_path, capsys):
    p = tmp_path / "c.json"
    rc = coord_cli.run(["whoami"], p, cwd=str(tmp_path), env={})
    assert rc == 1
    assert "could not resolve" in capsys.readouterr().err


def test_release_mine_releases_resolved_sessions_claims(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "worktree", "/wt/x")
    registry.claim(p, "s2", "branch", "feat/y")
    assert coord_cli.run(["release-mine", "--session", "s1"], p) == 0
    remaining = registry.list_claims(p, include_stale=True)
    assert len(remaining) == 1 and remaining[0]["session_id"] == "s2"


def test_resync_replaces_claims_with_current_cwd_and_branch(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "old/branch")
    registry.claim(p, "s1", "worktree", "/old/wt")
    new_wt = str(tmp_path / "new-wt")
    rc = coord_cli.run(["resync", "--session", "s1"], p,
                       cwd=new_wt, branch_func=lambda cwd: "new/branch")
    assert rc == 0
    claims = {c["kind"]: c["value"] for c in registry.list_claims(p)}
    assert claims == {"branch": "new/branch", "worktree": os.path.abspath(new_wt)}


def test_resync_detached_head_claims_only_worktree(tmp_path):
    p = tmp_path / "c.json"
    new_wt = str(tmp_path / "new-wt")
    rc = coord_cli.run(["resync", "--session", "s1"], p,
                       cwd=new_wt, branch_func=lambda cwd: "")
    assert rc == 0
    claims = {c["kind"]: c["value"] for c in registry.list_claims(p)}
    assert claims == {"worktree": os.path.abspath(new_wt)}
