"""PreToolUse coordination hook — deny wrong-branch/main commits, warn on
claimed-file edits. Pure decision logic in decide(); main() handles I/O.
Fails open: any error → allow (exit 0, no output).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

# git global options that consume a following token as their argument, so the
# real subcommand is the token *after* the argument (e.g. `git -C /repo commit`).
_GLOBAL_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree",
                         "--namespace", "--exec-path", "--super-prefix"}
# Subcommands that write history/refs — the read-only-main and claimed-branch
# rules key on these. merge/rebase/cherry-pick/revert create commits exactly
# like `commit` (`git checkout main && git merge feat/x` was a false-allow).
# `pull` is deliberately absent: an ff-pull is the sanctioned way to update
# main (it is what the SessionStart hook itself does). Plumbing ref-writers
# (update-ref, branch -f, fetch-with-refspec) stay out of scope — this is a
# guardrail against common agent mistakes, not a security boundary.
_GIT_WRITE_SUBCMDS = {"commit", "push", "merge", "rebase", "cherry-pick",
                      "revert"}
_REDIRECT_RE = re.compile(r"^(?:\d+|&)?(>>?)(.*)$")


def _git_commands(cmd):
    """Yield (subcmd, dir, args) for each git invocation in a shell command.

    dir is where that command runs: the
    invocation's own `-C` / `--work-tree` / `--git-dir`'s parent, else the
    carried `cd` target, else '' (caller falls back to cwd). args are the
    command's own tokens after the subcommand.

    Splits on shell separators and tokenizes, so the operative subcommand is
    identified by position (first non-option token after `git`), not by mere
    word presence — `git log --grep=commit` yields nothing. Only *sequential*
    separators (&&/;/newline) carry the cd; `|`, `||` and a background `&`
    reset it (that git runs in the original cwd, not the cd target).
    Best-effort — subshells, $vars, and command substitution fall through to
    '' (cwd), the deny-biased direction."""
    cur = ""
    parts = re.split(r"(&&|\|\||;|\||&|\n)", cmd)   # keep separators (odd idx)
    for k in range(0, len(parts), 2):
        if k > 0 and parts[k - 1] in ("|", "||", "&"):
            cur = ""                        # non-sequential: cd doesn't carry
        seg = parts[k]
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        if not toks:
            continue
        if toks[0] == "cd" and len(toks) >= 2:
            cur = toks[1]
            continue
        if "git" not in toks:
            continue
        i = toks.index("git") + 1
        loc = ""                            # this invocation's own location
        sub = ""
        while i < len(toks):
            t = toks[i]
            if t == "-C" and i + 1 < len(toks):
                loc = toks[i + 1]
                i += 2
                continue
            if t == "--work-tree" and i + 1 < len(toks):
                loc = toks[i + 1]
                i += 2
                continue
            if t.startswith("--work-tree="):
                loc = t.split("=", 1)[1]
                i += 1
                continue
            # --git-dir points at <tree>/.git: the write lands in its parent.
            if t == "--git-dir" and i + 1 < len(toks):
                loc = os.path.dirname(toks[i + 1]) or toks[i + 1]
                i += 2
                continue
            if t.startswith("--git-dir="):
                v = t.split("=", 1)[1]
                loc = os.path.dirname(v) or v
                i += 1
                continue
            if t.startswith("-"):           # skip option (+ arg)
                i += 2 if t in _GLOBAL_OPTS_WITH_ARG else 1
                continue
            sub = t                         # first non-option token = subcmd
            break
        if sub:
            yield sub, (loc or cur), toks[i + 1:]


def _git_writes(cmd):
    """Yield every history/ref-writing git command in a shell command."""
    for command in _git_commands(cmd):
        if command[0] in _GIT_WRITE_SUBCMDS:
            yield command


def _is_git_write(cmd):
    return next(_git_writes(cmd), None) is not None


def _shell_file_writes(cmd):
    """Yield (writer, dir, path) for common shell writes to named files.

    This is deliberately a guardrail, not a shell interpreter: it recognizes
    output redirection plus the ordinary file operands of tee, sed -i, dd
    of=, and truncate. Sequential `cd` handling matches _git_writes(); complex
    expansion, subshells, and arbitrary programs remain out of scope."""
    cur = ""
    parts = re.split(r"(&&|\|\||;|\||&|\n)", cmd)
    for k in range(0, len(parts), 2):
        if k > 0 and parts[k - 1] in ("|", "||", "&"):
            cur = ""
        seg = parts[k]
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        if not toks:
            continue
        if toks[0] == "cd" and len(toks) >= 2:
            cur = toks[1]
            continue

        # `> file`, `>>file`, `2> error.log`; descriptor duplication such as
        # `2>&1` is not a file write.
        for i, tok in enumerate(toks):
            match = _REDIRECT_RE.match(tok)
            if not match:
                continue
            path = match.group(2)
            if not path and i + 1 < len(toks):
                path = toks[i + 1]
            if path and not path.startswith("&"):
                yield "redirection", cur, path

        exe = os.path.basename(toks[0])
        args = toks[1:]
        if exe == "tee":
            operands = False
            for arg in args:
                if arg == "--":
                    operands = True
                elif operands or not arg.startswith("-"):
                    yield "tee", cur, arg
        elif exe == "sed" and any(
                arg == "-i" or arg.startswith("-i") or
                arg == "--in-place" or arg.startswith("--in-place=")
                for arg in args):
            has_script_option = any(
                arg in ("-e", "--expression", "-f", "--file") or
                arg.startswith("--expression=") or arg.startswith("--file=")
                for arg in args)
            script_seen = has_script_option
            skip = False
            for arg in args:
                if skip:
                    skip = False
                    continue
                if arg in ("-e", "--expression", "-f", "--file"):
                    skip = True
                    continue
                if arg.startswith("-"):
                    continue
                if not script_seen:
                    script_seen = True
                    continue
                yield "sed -i", cur, arg
        elif exe == "dd":
            for arg in args:
                if arg.startswith("of=") and len(arg) > 3:
                    yield "dd", cur, arg[3:]
        elif exe == "truncate":
            skip = False
            operands = False
            for arg in args:
                if skip:
                    skip = False
                    continue
                if arg == "--":
                    operands = True
                elif not operands and arg in ("-s", "--size"):
                    skip = True
                elif not operands and arg.startswith("-"):
                    continue
                else:
                    yield "truncate", cur, arg


def _pushes_to_main(args):
    """True when a `git push`'s args update the remote 'main' ref: `push
    origin main`, `feat:main`, `+feat:main`, `HEAD:refs/heads/main`, or the
    deletion `:main`. Pushing to main is blocked from ANY branch — checking
    only the checked-out branch false-allowed `git push origin main` from a
    feature branch. A remote literally named 'main' can false-match —
    acceptable rarity; FORCE is the recourse."""
    for t in args:
        if not t or t.startswith("-"):
            continue                        # options; refspecs never start '-'
        t = t.lstrip("+")
        dst = t.split(":", 1)[1] if ":" in t else t
        if dst in ("main", "refs/heads/main"):
            return True
    return False


def _deny(reason):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}


def _warn(msg):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": msg}}


def _git_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except Exception:
        return ""


def _staged_numeric_adrs(cwd):
    """Return numeric ADR additions/rename destinations, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "diff", "--cached", "--name-status",
             "--diff-filter=AR", "-z"], capture_output=True, timeout=3)
        if result.returncode:
            return None
    except Exception:
        return None
    out = []
    fields = result.stdout.decode("utf-8").split("\0")
    i = 0
    while i < len(fields) - 1:
        status = fields[i]
        i += 1
        if status.startswith("R"):
            if i + 1 >= len(fields):
                return None
            i += 1
        elif status != "A" or i >= len(fields):
            return None
        path = fields[i]
        i += 1
        match = re.fullmatch(r"docs/adr/(\d{4})-[^/\t\r\n]+\.md", path)
        if match:
            out.append((match.group(1), path))
    return out


def _first_existing(d):
    """Nearest existing ancestor of directory d (d itself if it exists), so a
    new file in a not-yet-created package still resolves via its worktree
    instead of failing `git -C` to ''."""
    d = os.path.abspath(d)
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return d


def _coord_root(reg_path):
    """Root of the repo this registry governs — reg_path is always
    <root>/.claude/coordination/claims.json (see registry.claims_path)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(reg_path))))


def _belongs_to_coord_repo(target, root):
    """Whether target is in this checkout or one of its linked worktrees."""
    t = os.path.normcase(os.path.realpath(target))
    r = os.path.normcase(os.path.realpath(root))
    if t == r or t.startswith(r.rstrip("\\/") + os.sep):
        return True
    existing = _first_existing(os.path.dirname(t))
    common = _rev_parse(existing, "--git-common-dir").strip()
    if not common:
        return False
    if not os.path.isabs(common):
        common = os.path.join(existing, common)
    return os.path.normcase(os.path.dirname(os.path.realpath(common))) == r


def _foreign_repo(target, root):
    """True when target provably belongs to a DIFFERENT git repo than the
    coordination root — its writes (even on a branch named 'main') are that
    repo's business, e.g. a scratch clone in the temp dir; denying those with
    a message about OUR read-only main is a false-deny. Conservative: paths
    under root, non-repo dirs, and git failures all count as OURS, so the
    deny/conflict checks still apply. realpath, so a link-spelled path can't
    dodge the prefix check."""
    t = os.path.normcase(os.path.realpath(target))
    r = os.path.normcase(os.path.realpath(root))
    if t == r or t.startswith(r.rstrip("\\/") + os.sep):
        return False
    common = _rev_parse(target, "--git-common-dir").strip()
    if not common:
        return False
    if not os.path.isabs(common):
        common = os.path.join(target, common)
    main_root = os.path.dirname(os.path.realpath(common))
    return os.path.normcase(main_root) != r


def _rev_parse(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", *args],
                           capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _in_main_tree(d):
    # main tree: git-dir and git-common-dir point at the SAME .git; a linked
    # worktree: they differ. git prints either absolute OR cwd-relative paths
    # (e.g. '../.git' from a subdir), so resolve both against d before compare.
    # One subprocess returns both lines; a git error → '' → [] → False (fail-open).
    out = _rev_parse(d, "--git-dir", "--git-common-dir").splitlines()
    if len(out) != 2:
        return False

    def _abs(p):
        p = p.strip()
        return os.path.normcase(os.path.abspath(
            p if os.path.isabs(p) else os.path.join(d, p)))

    return _abs(out[0]) == _abs(out[1])


def _shared_tree_warn(reg_path, sid, target, cwd, main_tree_func=None):
    """Soft (non-blocking) nudge when another live session shares this main
    working tree AND the write targets it — the gotcha-#1 HEAD-churn condition.
    repo_root() does one cheap `git rev-parse`, then the registry read; the
    *expensive* _in_main_tree probe runs ONLY when a sharer actually exists."""
    import registry
    sharers = registry.tree_sharers(reg_path, sid, registry.repo_root(cwd))
    if not sharers:
        return None
    if not (main_tree_func or _in_main_tree)(target):
        return None
    return _warn(
        "[coord] %d other session(s) share this main working tree and this write "
        "targets it — concurrent checkouts here can move your HEAD onto the wrong "
        "branch. Isolate: EnterWorktree, then "
        "'python .claude/coordination/coord_cli.py resync'." % len(sharers))


def decide(payload, reg_path, branch_func=None, main_tree_func=None,
           staged_func=None):
    if os.environ.get("AUTOGIS_COORD_FORCE") == "1":
        return None
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    normal_commit = tool == "Bash" and any(
        sub == "commit" for sub, _d, _args in _git_writes(
            ti.get("command", "")))
    pre_heartbeat_claims = None
    if normal_commit:
        try:
            pre_heartbeat_claims = registry.list_claims(reg_path)
        except Exception:
            pass

    # Best-effort: refresh this session's own heartbeat on any tool call.
    def heartbeat():
        try:
            registry.heartbeat(reg_path, sid)
        except Exception:
            pass

    if not normal_commit:
        heartbeat()

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = ti.get("file_path", "") or ti.get("notebook_path", "")
        if fp:
            # Edit/Write send absolute paths in production, but file_glob claims
            # are repo-relative — make the path relative to the repo root
            # (reg_path is <root>/.claude/coordination/claims.json) before match.
            # realpath, not abspath: a junction/symlink from outside the repo
            # INTO it must classify as in-repo, or main is writable through a
            # link (false-allow).
            root = _coord_root(reg_path)
            rel = fp
            if os.path.isabs(fp):
                try:
                    rel = os.path.relpath(os.path.realpath(fp),
                                          os.path.realpath(root))
                except ValueError:
                    rel = fp
            rel = rel.replace("\\", "/")
            # 'main' is read-only: block writes to files INSIDE the repo. Paths
            # outside the repo (memory dir, scratchpad — rel escapes with ../ or
            # stays absolute on a cross-drive relpath) are always allowed.
            in_repo = not rel.startswith("../") and not os.path.isabs(rel)
            if in_repo:
                bf = branch_func or _git_branch
                # the write's own dir, not payload cwd (stale for pinned-cwd
                # subagents — issue #136 bug 1a)
                target = _first_existing(os.path.dirname(os.path.realpath(fp)))
                if (bf(target) or bf(cwd)) == "main":
                    return _deny(
                        "[coord] 'main' is read-only — writing %s is blocked. "
                        "Only reading is allowed on main. Check out a feature "
                        "branch and claim your files via the session-coordination "
                        "framework before writing (see CLAUDE.md > Worktrees & "
                        "session coordination). Override: AUTOGIS_COORD_FORCE=1."
                        % fp)
                warn = _shared_tree_warn(reg_path, sid, target, cwd,
                                         main_tree_func)
                if warn:
                    return warn
            conflicts = registry.file_conflicts(reg_path, sid, rel)
            if conflicts:
                c = conflicts[0]
                return _warn(
                    "[coord] %s is claimed by session %s (pattern %s). "
                    "Coordinate before editing." % (fp, c["session_id"][:8],
                                                     c.get("value")))
        return None

    if tool == "Bash":
        command = ti.get("command", "")
        commands = list(_git_commands(command))
        writes = list(_git_writes(command))
        if writes:
            bf = branch_func or _git_branch
            root = _coord_root(reg_path)
            staged_in_command = set()
            compound_commit_targets = set()
            for sub, d, _args in commands:
                target = _first_existing(os.path.join(cwd, d) if d else cwd)
                if _foreign_repo(target, root):
                    continue
                target = os.path.realpath(target)
                if sub in {"add", "mv"}:
                    staged_in_command.add(target)
                elif sub == "commit" and target in staged_in_command:
                    compound_commit_targets.add(target)
            first_target = None      # first non-foreign target, for the warn
            checked = set()          # dirs already branch-checked
            for sub, d, args in writes:
                # this write's own dir, not payload cwd (stale for pinned-cwd
                # subagents — issue #136 bug 1a); abs parsed dir wins the join
                target = _first_existing(os.path.join(cwd, d) if d else cwd)
                if _foreign_repo(target, root):
                    continue
                if first_target is None:
                    first_target = target
                if target not in checked:
                    checked.add(target)
                    branch = bf(target) or bf(cwd)
                    if branch == "main":
                        return _deny(
                            "[coord] git %s on 'main' is blocked — 'main' is "
                            "read-only. Use a feature branch + PR. "
                            "Override: AUTOGIS_COORD_FORCE=1." % sub)
                    conflicts = registry.branch_conflicts(reg_path, sid, branch)
                    if conflicts:
                        c = conflicts[0]
                        return _deny(
                            "[coord] Branch '%s' is claimed by session %s "
                            "(pid %s). You may be on the wrong branch. "
                            "Override: AUTOGIS_COORD_FORCE=1."
                            % (branch, c["session_id"][:8], c.get("pid")))
                if sub == "push" and _pushes_to_main(args):
                    return _deny(
                        "[coord] Pushing to remote 'main' is blocked from any "
                        "branch — merge via PR instead. "
                        "Override: AUTOGIS_COORD_FORCE=1.")
                if sub == "commit":
                    if os.path.realpath(target) in compound_commit_targets:
                        return _deny(
                            "[coord] Stage ADR changes and commit them in "
                            "separate Bash commands so the reservation guard "
                            "can inspect the final index.")
                    staged = (staged_func or _staged_numeric_adrs)(target)
                    if staged is not None and pre_heartbeat_claims is not None:
                        reserved = set()
                        for claim in pre_heartbeat_claims:
                            if (claim.get("session_id") == sid and
                                    claim.get("kind") == "adr"):
                                try:
                                    reserved.add(int(claim.get("value")))
                                except (TypeError, ValueError):
                                    pass
                        for number, path in sorted(staged):
                            if int(number) not in reserved:
                                replacement = path.rsplit("/", 1)[-1].replace(
                                    number, "XXXX", 1)
                                return _deny(
                                    "[coord] ADR %s is staged as %s without this "
                                    "session owning reservation %s; run coord "
                                    "reserve-adr --strict or rename the file to %s."
                                    % (number, path, number, replacement))
            if first_target is not None:
                warn = _shared_tree_warn(reg_path, sid, first_target, cwd,
                                         main_tree_func)
                if warn:
                    if normal_commit:
                        heartbeat()
                    return warn
            if normal_commit:
                heartbeat()
        root = _coord_root(reg_path)
        bf = branch_func or _git_branch
        for writer, d, path in _shell_file_writes(command):
            base = os.path.join(cwd, d) if d else cwd
            path = os.path.expanduser(path)
            target_path = os.path.abspath(os.path.join(base, path))
            if not _belongs_to_coord_repo(target_path, root):
                continue
            target = _first_existing(
                os.path.dirname(os.path.realpath(target_path)))
            if (bf(target) or bf(cwd)) == "main":
                return _deny(
                    "[coord] 'main' is read-only — %s writing %s is blocked. "
                    "Use a feature branch and claim the file before writing. "
                    "Override: AUTOGIS_COORD_FORCE=1."
                    % (writer, target_path))
        return None

    return None


def _reg_path(payload):
    # registry.py is always a sibling of this hook; import it relative to
    # __file__ (robust regardless of cwd / worktree). The shared registry FILE,
    # however, lives at the canonical MAIN-tree root so all worktree sessions
    # share one claims.json — registry.claims_path resolves that via git.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry
    return registry.claims_path(payload.get("cwd"))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        out = decide(payload, _reg_path(payload))
    except Exception:
        sys.exit(0)
    if out:
        print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
