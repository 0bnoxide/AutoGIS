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
    matcher = "^(Bash|apply_patch)$"
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


def _edits(payload):
    """Yield Claude-shaped payload(s) for one Codex payload.

    Bash -> passthrough. apply_patch/Edit/Write -> one Edit payload per target
    file, path absolutised against cwd. An apply_patch whose paths don't parse
    still yields one cwd-anchored sentinel so the main-read-only guard fires
    (fail toward checking, not toward a silent allow, on the highest-value rule).
    Any other tool -> nothing (allow).
    """
    tool = payload.get("tool_name", "")
    base = {"session_id": payload.get("session_id", ""),
            "cwd": payload.get("cwd", "")}
    if tool == "Bash":
        yield {**base, "tool_name": "Bash",
               "tool_input": payload.get("tool_input") or {}}
        return
    if tool in ("apply_patch", "Edit", "Write", "MultiEdit"):
        ti = payload.get("tool_input") or {}
        fp = ti.get("file_path")
        if fp:  # already path-shaped (Edit/Write variant) -- pass through
            yield {**base, "tool_name": "Edit", "tool_input": {"file_path": fp}}
            return
        paths = _patch_paths(ti.get("command", ""))
        if not paths:  # unparseable patch -> guard the cwd branch anyway
            paths = [os.path.join(base["cwd"] or ".", "UNKNOWN")]
        for p in paths:
            ap = p if os.path.isabs(p) else os.path.join(base["cwd"] or ".", p)
            yield {**base, "tool_name": "Edit", "tool_input": {"file_path": ap}}


def check(payload, branch_func=None, main_tree_func=None):
    """First *deny* verdict among the payload's synthesised edits, else None.
    Warns are treated as allow (dropped). branch_func/main_tree_func are the
    same injection seams decide() exposes -- used by the self-test."""
    for p in _edits(payload):
        out = hook_check.decide(p, hook_check._reg_path(p),
                                branch_func=branch_func,
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

    # Bash passes through unchanged
    b = {"tool_name": "Bash", "cwd": "/r", "session_id": "s",
         "tool_input": {"command": "git commit"}}
    assert list(_edits(b)) == [{"session_id": "s", "cwd": "/r",
                                "tool_name": "Bash",
                                "tool_input": {"command": "git commit"}}]

    # non-edit tool -> allow (no synthesised edits)
    assert list(_edits({"tool_name": "WebSearch", "cwd": "/r"})) == []

    # unparseable patch -> single cwd sentinel so the main-guard still fires
    sent = list(_edits({"tool_name": "apply_patch", "cwd": "/r",
                        "session_id": "s", "tool_input": {"command": "garbage"}}))
    assert len(sent) == 1 and os.path.basename(
        sent[0]["tool_input"]["file_path"]) == "UNKNOWN", sent

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
