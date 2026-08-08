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


def test_resync_preserves_file_glob_claims(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "old/branch")
    registry.claim(p, "s1", "worktree", "/old/wt")
    registry.claim(p, "s1", "file_glob", "autogis/adapters/cli.py")
    new_wt = str(tmp_path / "new-wt")
    rc = coord_cli.run(["resync", "--session", "s1"], p,
                       cwd=new_wt, branch_func=lambda cwd: "new/branch")
    assert rc == 0
    claims = {(c["kind"], c["value"]) for c in registry.list_claims(p)}
    assert ("file_glob", "autogis/adapters/cli.py") in claims
    assert ("branch", "new/branch") in claims
    assert ("worktree", os.path.abspath(new_wt)) in claims


def test_resync_detached_head_claims_only_worktree(tmp_path):
    p = tmp_path / "c.json"
    new_wt = str(tmp_path / "new-wt")
    rc = coord_cli.run(["resync", "--session", "s1"], p,
                       cwd=new_wt, branch_func=lambda cwd: "")
    assert rc == 0
    claims = {c["kind"]: c["value"] for c in registry.list_claims(p)}
    assert claims == {"worktree": os.path.abspath(new_wt)}


# --- reserve-adr -------------------------------------------------------------

def test_reserve_adr_reserves_and_increments(tmp_path, capsys, monkeypatch):
    # Stub the file/PR scan so the test is offline and deterministic; the scan
    # itself is exercised by the new-adr skill's own self-check.
    monkeypatch.setattr(coord_cli, "_adr_scan_base", lambda cwd: 106)
    p = tmp_path / "c.json"
    assert coord_cli.run(["reserve-adr", "--session", "s1"], p) == 0
    assert capsys.readouterr().out.strip() == "0107"
    assert coord_cli.run(["reserve-adr", "--session", "s2"], p) == 0
    assert capsys.readouterr().out.strip() == "0108"   # steps over s1's reservation
    assert sorted(registry.live_values(p, "adr")) == ["107", "108"]


def test_reserve_adr_needs_resolvable_session(tmp_path):
    assert coord_cli.run(["reserve-adr"], tmp_path / "c.json", cwd="/nowhere",
                         env={}) == 1


# --- #425: the scan must see the CALLER's worktree, not just coord_cli's -----
#
# A pinned/worktree session invokes the shared main-tree coord_cli.py. The scan
# resolved docs/adr from coord_cli's __file__, so when main was behind the
# branch being reserved for, it handed back a number the caller's worktree had
# already used (observed: returned 0121 with 0121-*.md sitting in the worktree).

def _fake_tree(root, adr_numbers):
    adr = root / "docs" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    for n in adr_numbers:
        (adr / f"{n:04d}-x.md").write_text("", encoding="utf-8")
    return root


def test_adr_scan_base_includes_the_callers_worktree(tmp_path, monkeypatch):
    """coord_cli's own tree is behind; the caller's worktree has ADR-0121."""
    import next_adr_number
    own = _fake_tree(tmp_path / "main", [118])
    caller = _fake_tree(tmp_path / "wt", [121])
    monkeypatch.setattr(coord_cli, "_git_toplevel", lambda cwd: str(caller))
    monkeypatch.setattr(next_adr_number, "_open_pr_max", lambda: 0)
    monkeypatch.setattr(coord_cli, "_own_tree", lambda: str(own))

    assert coord_cli._adr_scan_base(str(caller)) == 121


def test_adr_scan_base_keeps_its_own_tree_when_that_one_is_ahead(
        tmp_path, monkeypatch):
    """Symmetric: either tree can be ahead, so the floor is the max of both."""
    import next_adr_number
    own = _fake_tree(tmp_path / "main", [130])
    caller = _fake_tree(tmp_path / "wt", [121])
    monkeypatch.setattr(coord_cli, "_git_toplevel", lambda cwd: str(caller))
    monkeypatch.setattr(next_adr_number, "_open_pr_max", lambda: 0)
    monkeypatch.setattr(coord_cli, "_own_tree", lambda: str(own))

    assert coord_cli._adr_scan_base(str(caller)) == 130


def test_adr_scan_base_survives_a_non_git_cwd(tmp_path, monkeypatch):
    """git unavailable -> "" toplevel -> fall back to coord_cli's own tree,
    never crash (reserve-adr must keep working off reservations alone)."""
    import next_adr_number
    own = _fake_tree(tmp_path / "main", [118])
    monkeypatch.setattr(coord_cli, "_git_toplevel", lambda cwd: "")
    monkeypatch.setattr(next_adr_number, "_open_pr_max", lambda: 0)
    monkeypatch.setattr(coord_cli, "_own_tree", lambda: str(own))

    assert coord_cli._adr_scan_base(str(tmp_path / "nowhere")) == 118


# --- #454: a skipped open-PR scan must be visible, not silent ---------------
#
# _open_pr_max() shells out to `gh`. Cloud/web sessions have no gh at all
# (GitHub is reached via MCP there), so FileNotFoundError was swallowed, the
# open-PR half of the scan went dark, and reserve-adr printed a confidently
# wrong number -- it handed out 0124 while open PR #440 already added
# docs/adr/0124-*.md. Failing soft is right; failing silently is not.

def _no_gh(monkeypatch):
    import subprocess
    import next_adr_number

    def _boom(*a, **k):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(next_adr_number.subprocess, "run", _boom)
    return subprocess


def test_open_pr_max_warns_on_stderr_when_gh_is_absent(monkeypatch, capsys):
    import next_adr_number
    _no_gh(monkeypatch)

    assert next_adr_number._open_pr_max() == 0        # still fails soft
    err = capsys.readouterr().err
    assert "open-PR ADR scan did not run" in err
    assert "FileNotFoundError" in err                 # names why


def test_reserve_adr_still_prints_a_number_when_gh_is_absent(
        tmp_path, monkeypatch, capsys):
    """The warning goes to stderr so stdout stays machine-readable: callers
    that parse the number are unaffected by the added visibility."""
    import next_adr_number
    _no_gh(monkeypatch)
    monkeypatch.setattr(coord_cli, "_own_tree", lambda: str(tmp_path / "t"))
    monkeypatch.setattr(coord_cli, "_git_toplevel", lambda cwd: "")
    (tmp_path / "t" / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "t" / "docs" / "adr" / "0124-x.md").write_text("")

    assert coord_cli.run(["reserve-adr", "--session", "s1"],
                         tmp_path / "c.json") == 0
    out = capsys.readouterr()
    assert out.out.strip() == "0125"
    assert "open-PR ADR scan did not run" in out.err
