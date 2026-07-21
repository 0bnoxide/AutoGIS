#!/usr/bin/env python3
"""Codex -> AutoGIS coordination shim.

Codex fires PreToolUse *command* hooks with the SAME stdin/stdout contract as
Claude Code (a JSON tool-call payload in, a `hookSpecificOutput`/
`permissionDecision` verdict out), so the AutoGIS read-only-main + claimed-file
rules in `hook_check.decide()` are reused verbatim. There is deliberately NO
second copy of those rules here (a PowerShell/JS reimplementation would drift
from hook_check.py the moment its logic changes) -- decide() stays the one
source of truth. This shim only bridges the two *input* shapes:

  * Bash        -> byte-identical to Claude's payload (tool_input.command);
                   passed straight through to decide().
  * apply_patch -> Codex's edit tool. Its payload carries the PATCH STRING in
                   tool_input.command, NOT a file_path, but decide() keys the
                   main-read-only + claimed-file checks on file_path. So we
                   parse the target path(s) out of the V4A
                   `*** Add|Update|Delete File:` / `*** Move to:` headers,
                   absolutise them against the payload cwd (decide() resolves a
                   path's branch via os.path.realpath, which otherwise binds to
                   the hook process cwd, not Codex's), and synthesise one Edit
                   payload per file.

Deny output needs no translation: decide()'s deny dict already matches Codex's
`permissionDecision:"deny"` schema. Warns are dropped (see ponytail note).
Fails open (any error -> allow), matching hook_check.py -- this is a
coordination guardrail, not a security boundary.

Wire from ~/.codex/config.toml (or managed requirements.toml):

    [[hooks.PreToolUse]]
    matcher = "^(Bash|apply_patch|Edit|Write)$"   # edits report tool_name=apply_patch
    [[hooks.PreToolUse.hooks]]
    type = "command"
    command_windows = 'python "C:/Users/ichbi/AutoGIS/.claude/coordination/codex_coord_shim.py"'
    timeout = 10

# ponytail: warns dropped on the Codex side -- Codex's handling of Claude's
# `additionalContext` field is unconfirmed, so a claimed-file *warn* (non-
# blocking in Claude too) becomes a silent allow here; the read-before-work
# handoff ritual covers claimed-file coordination. Upgrade to additionalContext
# passthrough if/when Codex documents it. Hard denies (main / cross-session
# branch) are always emitted.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hook_check  # noqa: E402  (path set above)

# V4A apply_patch file headers: `*** Add|Update|Delete File: <path>` and the
# rename destination `*** Move to: <path>`. One capture group each; finditer
# preserves source order so multi-file patches yield every touched path.
_PATCH_PATH = re.compile(
    r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$"
    r"|^\*\*\*\s+Move\s+to:\s*(.+?)\s*$",
    re.MULTILINE,
)


def _patch_paths(patch):
    """Target paths named in a V4A apply_patch string (as written, unresolved)."""
    return [m.group(1) or m.group(2) for m in _PATCH_PATH.finditer(patch or "")]


def _edit(base, path):
    """One Edit payload, path absolutised against cwd -- decide() resolves a
    file's branch via os.path.realpath, which must bind to Codex's cwd, not the
    hook process's."""
    ap = path if os.path.isabs(path) else os.path.join(base["cwd"] or ".", path)
    return {**base, "tool_name": "Edit", "tool_input": {"file_path": ap}}


def _edits(payload):
    """Yield Claude-shaped payload(s) for one Codex payload.

    Bash -> passthrough, PLUS an Edit per file if the command body carries V4A
    patch headers (Codex may surface apply_patch as a shell heredoc/argv; a
    patch piped through Bash makes no git write, so without this it slips past
    as a silent allow). apply_patch/Edit/Write -> one Edit per target file. An
    apply_patch whose paths don't parse still yields one cwd-anchored sentinel
    so the main-read-only guard fires (fail toward checking on the highest-value
    rule). Any other tool -> nothing (allow).
    """
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    base = {"session_id": payload.get("session_id", ""),
            "cwd": payload.get("cwd", "")}
    if tool == "Bash":
        yield {**base, "tool_name": "Bash", "tool_input": ti}
        for p in _patch_paths(ti.get("command", "")):
            yield _edit(base, p)
        return
    if tool in ("apply_patch", "Edit", "Write", "MultiEdit"):
        fp = ti.get("file_path")
        if fp:  # already path-shaped (Edit/Write variant) -- pass through
            yield _edit(base, fp)
            return
        # unparseable patch -> sentinel so the cwd branch is still guarded
        for p in _patch_paths(ti.get("command", "")) or ["UNKNOWN"]:
            yield _edit(base, p)


def check(payload, branch_func=None, main_tree_func=None):
    """First *deny* verdict among the payload's synthesised edits, else None.
    Warns are treated as allow (dropped). The registry path is resolved once
    (constant across a payload's edits -- bounds git subprocess calls under the
    hook timeout); the per-file branch lookup stays inside decide() so a
    `git -C <other>` in a Bash command is judged by ITS dir, not cwd (#136).
    branch_func/main_tree_func are decide()'s injection seams -- exercised by
    the self-test's real-decide() integration case."""
    reg = None
    for p in _edits(payload):
        if reg is None:
            reg = hook_check._reg_path(p)
        out = hook_check.decide(p, reg, branch_func=branch_func,
                                main_tree_func=main_tree_func)
        if out and (out.get("hookSpecificOutput", {})
                    .get("permissionDecision") == "deny"):
            return out
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        out = check(payload)
    except Exception:
        sys.exit(0)  # fail open, like hook_check.py
    if out:
        print(json.dumps(out))
    sys.exit(0)


def _selftest():
    patch = ("*** Begin Patch\n*** Update File: core/foo.py\n"
             "*** Add File: adapters/bar.py\n*** Delete File: old.py\n"
             "*** Move to: adapters/baz.py\n*** End Patch")
    assert _patch_paths(patch) == ["core/foo.py", "adapters/bar.py", "old.py",
                                   "adapters/baz.py"], _patch_paths(patch)

    cwd = os.path.abspath(os.sep + "repo")  # real abs path (drive on Windows)
    p = {"tool_name": "apply_patch", "cwd": cwd, "session_id": "s",
         "tool_input": {"command": patch}}
    edits = list(_edits(p))
    assert all(e["tool_name"] == "Edit" for e in edits), edits
    fps = [e["tool_input"]["file_path"] for e in edits]
    assert [os.path.basename(f) for f in fps] == ["foo.py", "bar.py", "old.py",
                                                  "baz.py"], fps
    # absolutised against cwd so decide()'s realpath binds to Codex's cwd
    assert all(os.path.isabs(f) and f.startswith(cwd) for f in fps), fps

    # plain Bash passes through unchanged (no patch headers -> no extra edits)
    b = {"tool_name": "Bash", "cwd": "/r", "session_id": "s",
         "tool_input": {"command": "git commit"}}
    assert list(_edits(b)) == [{"session_id": "s", "cwd": "/r",
                                "tool_name": "Bash",
                                "tool_input": {"command": "git commit"}}]

    # Bash carrying an apply_patch heredoc -> passthrough PLUS an Edit per file,
    # so a patch piped through the shell can't dodge the main/claims guard.
    bp = {"tool_name": "Bash", "cwd": cwd, "session_id": "s",
          "tool_input": {"command": "apply_patch <<'EOF'\r\n"
                         "*** Update File: core/x.py \r\n*** End Patch\r\nEOF"}}
    bpe = list(_edits(bp))
    assert bpe[0]["tool_name"] == "Bash", bpe
    assert [os.path.basename(e["tool_input"]["file_path"])
            for e in bpe[1:]] == ["x.py"], bpe  # CRLF + trailing space tolerated

    # non-edit tool -> allow (no synthesised edits)
    assert list(_edits({"tool_name": "WebSearch", "cwd": "/r"})) == []

    # unparseable patch -> single cwd sentinel so the main-guard still fires
    sent = list(_edits({"tool_name": "apply_patch", "cwd": "/r",
                        "session_id": "s", "tool_input": {"command": "garbage"}}))
    assert len(sent) == 1 and os.path.basename(
        sent[0]["tool_input"]["file_path"]) == "UNKNOWN", sent

    # REAL integration (no mock): synthesised Edit -> real hook_check.decide()
    # -> main-read-only deny. Uses this file's own dir (always inside the repo)
    # as cwd so _reg_path resolves via git; branch forced 'main' via decide()'s
    # seam. This is the load-bearing path; the mocked cases below only cover
    # verdict routing.
    here = os.path.dirname(os.path.abspath(__file__))
    real = check({"tool_name": "apply_patch", "cwd": here,
                  "session_id": "selftest",
                  "tool_input": {"command": "*** Update File: README.md\n"}},
                 branch_func=lambda d: "main", main_tree_func=lambda d: False)
    assert real and real["hookSpecificOutput"][
        "permissionDecision"] == "deny", real

    # check(): first deny wins; warn-only -> allow. Monkeypatch decide() to
    # exercise the shim's verdict routing without touching git/claims.json.
    deny = {"hookSpecificOutput": {"permissionDecision": "deny",
                                   "permissionDecisionReason": "x"}}
    warn = {"hookSpecificOutput": {"additionalContext": "y"}}
    hook_check._reg_path = lambda pl: "x"
    hook_check.decide = (lambda pl, rp, branch_func=None, main_tree_func=None:
                         deny if pl["tool_input"].get("file_path", "")
                         .endswith("foo.py") else warn)
    assert check(p) is deny  # foo.py denies before the later files
    assert check({"tool_name": "apply_patch", "cwd": "/r", "session_id": "s",
                  "tool_input": {"command": "*** Update File: only_warn.py\n"}}
                 ) is None  # warn-only -> allow
    print("shim selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
