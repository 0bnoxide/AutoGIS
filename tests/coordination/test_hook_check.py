import json
import os
import shutil
import subprocess

import pytest

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
    # branch_func override keeps the test hermetic: without it the real
    # _git_branch resolves the checkout pytest runs from (issue #169 — the
    # test failed when run from a real 'main' checkout).
    out = hook_check.decide(
        _payload("Edit", {"file_path": "autogis/adapters/cli.py"}), p,
        branch_func=lambda cwd: "feat/x")
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


# --- 'main' is read-only: writes to in-repo files are denied ---

def _repo_payload(tmp_path, tool, fp, sid="me"):
    coord = tmp_path / ".claude" / "coordination"
    coord.mkdir(parents=True, exist_ok=True)
    p = coord / "claims.json"
    return _payload(tool, {"file_path": fp}, sid=sid), p


def test_edit_in_repo_on_main_is_denied(tmp_path):
    payload, p = _repo_payload(tmp_path, "Edit",
                               str(tmp_path / "autogis" / "core" / "x.py"))
    out = hook_check.decide(payload, p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "read-only" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_edit_outside_repo_on_main_is_allowed(tmp_path):
    # memory dir / scratchpad live outside the repo → never blocked on main.
    outside = str(tmp_path.parent / "memory" / "note.md")
    payload, p = _repo_payload(tmp_path, "Write", outside)
    out = hook_check.decide(payload, p, branch_func=lambda cwd: "main")
    assert out is None


def test_edit_in_repo_on_feature_branch_is_allowed(tmp_path):
    payload, p = _repo_payload(tmp_path, "Edit",
                               str(tmp_path / "autogis" / "core" / "x.py"))
    out = hook_check.decide(payload, p, branch_func=lambda cwd: "feat/x")
    assert out is None


def test_main_write_block_respects_force(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGIS_COORD_FORCE", "1")
    payload, p = _repo_payload(tmp_path, "Edit",
                               str(tmp_path / "autogis" / "core" / "x.py"))
    out = hook_check.decide(payload, p, branch_func=lambda cwd: "main")
    assert out is None


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


# --- bug 1a: resolve branch from the write TARGET, not stale payload cwd ------

def test_edit_worktree_file_resolves_target_not_cwd(tmp_path):
    # Pinned-cwd subagent: cwd resolves to 'main', but the file being edited is
    # in a worktree on a feature branch. Resolve from the target dir, not cwd.
    target = tmp_path / "autogis" / "core"
    target.mkdir(parents=True)
    payload, p = _repo_payload(tmp_path, "Edit", str(target / "x.py"))
    bf = lambda d: "feat/x" if "core" in d.replace("\\", "/") else "main"
    out = hook_check.decide(payload, p, branch_func=bf)
    assert out is None


def test_edit_main_tree_denied_even_when_cwd_is_feature(tmp_path):
    # Inverse: cwd looks like a feature branch, but the file targets the main
    # tree on 'main'. Target drives resolution → still denied.
    target = tmp_path / "autogis" / "core"
    target.mkdir(parents=True)
    payload, p = _repo_payload(tmp_path, "Edit", str(target / "x.py"))
    bf = lambda d: "main" if "core" in d.replace("\\", "/") else "feat/x"
    out = hook_check.decide(payload, p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_cd_worktree_commit_resolves_target(tmp_path):
    # `cd <wt> && git commit` — resolve the branch from the cd target, not cwd
    # (which is the stale main root for a pinned-cwd subagent).
    wt = tmp_path / "wt"
    wt.mkdir()
    p = tmp_path / "c.json"
    cmd = "cd %s && git commit -m x" % wt.as_posix()
    bf = lambda d: "feat/x" if d.replace("\\", "/").endswith("/wt") else "main"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out is None


def test_bash_git_dashC_worktree_commit_resolves_target(tmp_path):
    # `git -C <wt> commit` — the -C path is the target, not cwd.
    wt = tmp_path / "wt"
    wt.mkdir()
    p = tmp_path / "c.json"
    cmd = "git -C %s commit -m x" % wt.as_posix()
    bf = lambda d: "feat/x" if d.replace("\\", "/").endswith("/wt") else "main"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out is None


def test_empty_target_resolution_falls_back_to_cwd(tmp_path):
    # Detached HEAD at the target resolves to '' — fall back to cwd's branch so
    # the read-only-main floor is preserved ('' != 'main' would slip the guard).
    target = tmp_path / "autogis" / "core"
    target.mkdir(parents=True)
    payload, p = _repo_payload(tmp_path, "Edit", str(target / "x.py"))
    bf = lambda d: "" if "core" in d.replace("\\", "/") else "main"
    out = hook_check.decide(payload, p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_git_writes_parses_paths():
    f = lambda cmd: [d for _s, d, _a in hook_check._git_writes(cmd)]
    assert f("git -C /wt commit -m x") == ["/wt"]
    assert f("cd /wt && git commit") == ["/wt"]
    assert f("git commit -m x") == [""]
    assert f("cd a && cd b && git commit") == ["b"]          # last cd wins
    assert f("cd /foo && ls && git -C /bar commit") == ["/bar"]  # -C overrides cd
    assert f("git -c user.name=x -C /wt commit") == ["/wt"]  # -C after arg-taking opt
    assert f("git -C /wt log && git commit") == [""]  # read git's -C must not leak
    assert f("git -C /a diff && cd /b && git commit") == ["/b"]  # write's cd wins
    assert f("cd /wt | git commit") == [""]     # pipe resets the carried cd
    assert f("cd /wt || git commit") == [""]    # or-else resets the carried cd too
    assert f("git log --grep=commit") == []     # read git yields nothing
    # EVERY write is yielded, not just the first (multi-target commands):
    assert f("git -C /a commit && git commit") == ["/a", ""]
    assert f("cd /wt & git commit") == [""]     # background & resets like a pipe
    # --work-tree / --git-dir place the write too (both = and space forms):
    assert f("git --work-tree=/main commit") == ["/main"]
    assert f("git --work-tree /main commit") == ["/main"]
    assert f("git --git-dir=/main/.git commit") == ["/main"]
    assert f("git --git-dir /main/.git commit") == ["/main"]


# --- false-allow: EVERY git write in a compound command must be checked -------

def test_second_write_on_main_in_compound_command_denied(tmp_path):
    # `git -C <wt> commit && git commit` — the first write resolves the feature
    # worktree, but the SECOND runs in cwd (main). Checking only the first
    # write's dir false-allowed the main commit.
    wt = tmp_path / "wt"
    wt.mkdir()
    p = tmp_path / "c.json"
    cmd = "git -C %s commit -m x && git commit -m y" % wt.as_posix()
    bf = lambda d: "feat/x" if d.replace("\\", "/").endswith("/wt") else "main"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_single_ampersand_resets_carried_cd(tmp_path):
    # `cd <wt> & git commit` — the cd is backgrounded into a subshell; the
    # commit runs in cwd (main). The carried cd must reset on `&` like `|`.
    wt = tmp_path / "wt"
    wt.mkdir()
    p = tmp_path / "c.json"
    cmd = "cd %s & git commit -m x" % wt.as_posix()
    bf = lambda d: "feat/x" if d.replace("\\", "/").endswith("/wt") else "main"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_work_tree_option_resolves_target(tmp_path):
    # `git --work-tree=<main> commit` from a feature cwd lands the write on
    # main; falling back to cwd false-allowed it.
    mainroot = tmp_path / "mainroot"
    mainroot.mkdir()
    p = tmp_path / "c.json"
    cmd = "git --work-tree=%s commit -m x" % mainroot.as_posix()
    bf = lambda d: "main" if d.replace("\\", "/").endswith("/mainroot") \
        else "feat/x"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- false-allow: commit-creating porcelain beyond commit/push ----------------

@pytest.mark.parametrize("cmd", [
    "git merge feat/x",
    "git rebase feat/x",
    "git cherry-pick abc123",
    "git revert HEAD",
])
def test_history_writing_porcelain_on_main_denied(tmp_path, cmd):
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": cmd}),
                            p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("cmd", [
    "git merge main",            # updating a feature branch FROM main
    "git rebase main",
    "git pull",                  # the legit ff-update path stays open
    "git pull --ff-only",
])
def test_history_writing_porcelain_on_feature_allowed(tmp_path, cmd):
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": cmd}),
                            p, branch_func=lambda cwd: "feat/x")
    assert out is None


# --- false-allow: push refspec targeting remote 'main' from any branch --------

@pytest.mark.parametrize("cmd", [
    "git push origin main",              # pushes local main ref
    "git push origin feat/x:main",       # explicit refspec to main
    "git push origin +feat/x:main",      # forced refspec
    "git push origin HEAD:refs/heads/main",
    "git push origin :main",             # deletes remote main
    "git push -u origin main",           # option before refspec
])
def test_push_targeting_remote_main_denied_from_feature(tmp_path, cmd):
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": cmd}),
                            p, branch_func=lambda cwd: "feat/x")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("cmd", [
    "git push origin feat/x",
    "git push -u origin feat/main-window",   # 'main' as substring only
    "git push origin main:feat/backup",      # main as SOURCE is fine
    "git push",
])
def test_push_not_targeting_main_allowed(tmp_path, cmd):
    p = tmp_path / "c.json"
    out = hook_check.decide(_payload("Bash", {"command": cmd}),
                            p, branch_func=lambda cwd: "feat/x")
    assert out is None


# --- false-allow: symlink/junction from outside the repo into it --------------

def _dirlink(src, dst):
    try:
        os.symlink(src, dst, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":   # junction needs no privilege on Windows
        r = subprocess.run(["cmd", "/c", "mklink", "/J", dst, src],
                           capture_output=True)
        return r.returncode == 0
    return False


def test_edit_via_link_into_repo_denied_on_main(tmp_path):
    # A junction/symlink from OUTSIDE the repo into it must not defeat the
    # read-only-main rule: the write physically lands in the repo, so classify
    # by its REAL path.
    repo = tmp_path / "repo"
    (repo / ".claude" / "coordination").mkdir(parents=True)
    (repo / "autogis").mkdir()
    p = repo / ".claude" / "coordination" / "claims.json"
    link = tmp_path / "link"
    if not _dirlink(str(repo / "autogis"), str(link)):
        pytest.skip("cannot create a directory link on this platform")
    out = hook_check.decide(
        _payload("Edit", {"file_path": str(link / "x.py")}), p,
        branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- false-allow: NotebookEdit writes repo files but bypassed the hook --------

def test_notebook_edit_in_repo_on_main_is_denied(tmp_path):
    coord = tmp_path / ".claude" / "coordination"
    coord.mkdir(parents=True)
    p = coord / "claims.json"
    out = hook_check.decide(
        _payload("NotebookEdit", {"notebook_path": str(tmp_path / "nb.ipynb")}),
        p, branch_func=lambda cwd: "main")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- false-deny: an unrelated repo's 'main' is not OUR main -------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_commit_in_unrelated_repo_on_its_main_allowed(tmp_path):
    # A scratch repo outside the coordination root whose branch happens to be
    # named 'main' is that repo's business — denying it (with a message about
    # OUR read-only main) is a false-deny. No branch_func: real git resolves
    # the scratch repo's branch to 'main'.
    coordroot = tmp_path / "proj"
    (coordroot / ".claude" / "coordination").mkdir(parents=True)
    p = coordroot / ".claude" / "coordination" / "claims.json"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(scratch),
                   check=True, capture_output=True)
    cmd = "git -C %s commit -m x" % scratch.as_posix()
    out = hook_check.decide(
        _payload("Bash", {"command": cmd}, cwd=str(coordroot)), p)
    assert out is None


def test_bash_cd_piped_to_commit_resolves_cwd_not_cd(tmp_path):
    # `cd <wt> | git commit` — the cd is a concurrent subshell; the commit runs
    # in cwd, so it must NOT resolve to the cd target. cwd=main → still denied.
    wt = tmp_path / "wt"
    wt.mkdir()
    p = tmp_path / "c.json"
    cmd = "cd %s | git commit -m x" % wt.as_posix()
    bf = lambda d: "feat/x" if d.replace("\\", "/").endswith("/wt") else "main"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_read_git_dashC_before_commit_resolves_cwd_not_read(tmp_path):
    # `git -C <wt> log && git commit` — the READ git's -C must NOT resolve the
    # write. The commit runs in cwd (main here) → still denied, no false-allow.
    wt = tmp_path / "wt"
    wt.mkdir()
    p = tmp_path / "c.json"
    cmd = "git -C %s log && git commit -m x" % wt.as_posix()
    bf = lambda d: "feat/x" if d.replace("\\", "/").endswith("/wt") else "main"
    out = hook_check.decide(_payload("Bash", {"command": cmd}, cwd="/repo"),
                            p, branch_func=bf)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- soft contention warn (option C): warn, never deny -----------------------

def _sharer_payload(tmp_path, monkeypatch, tool, ti, sid="me"):
    # repo_root(cwd) must resolve to tmp_path so the sharer claim (value=tmp_path)
    # matches: tmp_path is not a git repo, so repo_root falls back to cwd — but
    # only if CLAUDE_PROJECT_DIR is unset (else it wins). Clear it.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    coord = tmp_path / ".claude" / "coordination"
    coord.mkdir(parents=True, exist_ok=True)
    p = coord / "claims.json"
    registry.claim(p, "other", "worktree", str(tmp_path))   # another session, this root
    return _payload(tool, ti, sid=sid, cwd=str(tmp_path)), p


def test_shared_tree_warns_on_edit_when_contended(tmp_path, monkeypatch):
    target = tmp_path / "autogis" / "core"
    target.mkdir(parents=True)
    payload, p = _sharer_payload(
        tmp_path, monkeypatch, "Edit", {"file_path": str(target / "x.py")})
    out = hook_check.decide(payload, p, branch_func=lambda d: "feat/x",
                            main_tree_func=lambda d: True)
    assert "additionalContext" in out["hookSpecificOutput"]
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert "share this main working tree" in \
        out["hookSpecificOutput"]["additionalContext"]


def test_shared_tree_warns_on_bash_commit_when_contended(tmp_path, monkeypatch):
    payload, p = _sharer_payload(
        tmp_path, monkeypatch, "Bash", {"command": "git commit -m x"})
    out = hook_check.decide(payload, p, branch_func=lambda d: "feat/x",
                            main_tree_func=lambda d: True)
    assert "additionalContext" in out["hookSpecificOutput"]
    assert "permissionDecision" not in out["hookSpecificOutput"]


def test_no_sharers_no_warn_and_no_git_call(tmp_path, monkeypatch):
    # No sharer → registry check empty → main_tree_func must NOT be consulted
    # (proves registry-first ordering: zero git subprocess under no contention).
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    target = tmp_path / "autogis" / "core"
    target.mkdir(parents=True)
    payload, p = _repo_payload(tmp_path, "Edit", str(target / "x.py"))

    def boom(d):
        raise AssertionError("main_tree_func consulted with no sharers")

    out = hook_check.decide(payload, p, branch_func=lambda d: "feat/x",
                            main_tree_func=boom)
    assert out is None


def test_sharers_but_worktree_target_no_warn(tmp_path, monkeypatch):
    # Sharer exists, but the write targets a linked worktree (not the main tree)
    # → main_tree_func → False → no warn.
    target = tmp_path / "autogis" / "core"
    target.mkdir(parents=True)
    payload, p = _sharer_payload(
        tmp_path, monkeypatch, "Edit", {"file_path": str(target / "x.py")})
    out = hook_check.decide(payload, p, branch_func=lambda d: "feat/x",
                            main_tree_func=lambda d: False)
    assert out is None


# --- _in_main_tree: git prints absolute git-dir but relative common-dir from a
#     subdir; both must resolve against the query dir before comparison. --------

def test_in_main_tree_normalizes_relative_common_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "autogis")
    monkeypatch.setattr(hook_check, "_rev_parse",
                        lambda cwd, *a: str(tmp_path / ".git") + "\n../.git\n")
    assert hook_check._in_main_tree(d) is True


def test_in_main_tree_false_for_linked_worktree(monkeypatch):
    monkeypatch.setattr(hook_check, "_rev_parse",
                        lambda cwd, *a: "/repo/.git/worktrees/wt\n/repo/.git\n")
    assert hook_check._in_main_tree("/repo/.claude/worktrees/wt") is False


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_in_main_tree_real_git_repo_and_worktree(tmp_path):
    # Regression guard for the subdir git-dir/common-dir format the injected
    # tests can't reach (git prints one absolute, one relative). Real repo +
    # linked worktree, no mocks.
    main = tmp_path / "main"
    main.mkdir()
    run = lambda *a, cwd=main: subprocess.run(
        ["git", *a], cwd=str(cwd), check=True, capture_output=True)
    run("init", "-b", "main")
    run("-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "--allow-empty", "-m", "init")
    sub = main / "pkg"
    sub.mkdir()
    wt = tmp_path / "wt"
    run("worktree", "add", "-b", "feat", str(wt))
    assert hook_check._in_main_tree(str(main)) is True
    assert hook_check._in_main_tree(str(sub)) is True     # subdir — the regression
    assert hook_check._in_main_tree(str(wt)) is False     # linked worktree
