"""SessionStart coordination hook — auto-claim the current branch + worktree
for this session so other sessions' PreToolUse checks can see it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request


def _git_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except Exception:
        return ""


def claim_session(payload, reg_path, branch_func=None):
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    if not sid:
        return []
    made = []
    bf = branch_func or _git_branch
    branch = bf(cwd)
    if branch:
        made.append(registry.claim(reg_path, sid, "branch", branch))
    made.append(registry.claim(reg_path, sid, "worktree", os.path.abspath(cwd)))
    try:
        registry.reap_stale(reg_path)
    except Exception:
        pass
    return made


def _reg_path(payload):
    # See hook_check._reg_path: import registry relative to __file__, but locate
    # the shared claims.json at the canonical main-tree root (worktree-safe).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import registry
    return registry.claims_path(payload.get("cwd"))


_POLICY = (
    "[coord] BRANCH POLICY — 'main' is READ-ONLY. On main only reading is "
    "allowed; any write (Edit/Write/MultiEdit to a repo file, git commit/push) "
    "is blocked by the PreToolUse hook. Before doing any work: check out a "
    "feature branch and claim it + your files via the session-coordination "
    "framework (see CLAUDE.md > Worktrees & session coordination). This applies "
    "to subagents too — the hook enforces it for every tool call regardless of "
    "who makes it, so pass this rule along when you dispatch one. Override for a "
    "one-off: AUTOGIS_COORD_FORCE=1, exported before the session/hook launches "
    "(an inline per-command prefix cannot reach the hook process). Pinned-cwd "
    "subagents: use 'coord_cli.py whoami|release-mine|resync' instead."
)

_MNEMOVERSE_DOMAIN = "collab:autogis"
_MNEMOVERSE_QUERIES = ("STATUS handoff", "BLOCKER", "DECISION")
_MNEMOVERSE_TOP_K = 3
_MNEMOVERSE_MAX_ITEMS = 5
_MNEMOVERSE_ITEM_CHARS = 1200


def _clip(text, limit):
    text = str(text).strip().replace("\x00", "")
    return text if len(text) <= limit else text[:limit - 14].rstrip() + " …[truncated]"


def mnemoverse_context(environ=None, open_url=None):
    """Read the three ADR-0095 queries and format bounded startup context.

    One public batch endpoint keeps startup cheap while preserving three
    targeted semantic queries. Failures never block the session; they leave a
    visible instruction to use the already-configured MCP tool manually.
    """
    env = os.environ if environ is None else environ
    api_key = env.get("MNEMOVERSE_API_KEY", "")
    fallback = (
        "[mnemoverse] Automatic collab:autogis retrieval unavailable. If the "
        "MCP tools are present, run the ADR-0095 reads manually: STATUS "
        "handoff, BLOCKER, DECISION."
    )
    if not api_key:
        return fallback

    base_url = env.get(
        "MNEMOVERSE_API_URL", "https://core.mnemoverse.com/api/v1"
    ).rstrip("/")
    body = {"queries": [
        {"query": query, "domain": _MNEMOVERSE_DOMAIN,
         "top_k": _MNEMOVERSE_TOP_K, "include_associations": True}
        for query in _MNEMOVERSE_QUERIES
    ]}
    try:
        request = urllib.request.Request(
            base_url + "/memory/read-batch",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AutoGIS-SessionStart/1.0",
                "X-Api-Key": api_key,
            },
            method="POST",
        )
        opener = open_url or urllib.request.urlopen
        with opener(request, timeout=5) as response:
            results = json.load(response).get("results", [])
        if (not isinstance(results, list)
                or len(results) != len(_MNEMOVERSE_QUERIES)
                or any(not isinstance(result, dict) for result in results)):
            return fallback
    except Exception:
        return fallback

    # Semantic queries overlap by design. Show each atom once and retain every
    # query label that found it so startup context stays below Codex's hook cap.
    matches = {}
    for query, result in zip(_MNEMOVERSE_QUERIES, results):
        items = result.get("items", [])
        if not isinstance(items, list):
            return fallback
        for item in items:
            if not isinstance(item, dict):
                continue
            atom_id = str(item.get("atom_id") or "")
            content = _clip(item.get("content", ""), _MNEMOVERSE_ITEM_CHARS)
            key = atom_id or content
            if not key:
                continue
            if key not in matches:
                matches[key] = {
                    "atom_id": atom_id or "unknown",
                    "content": content,
                    "queries": [],
                }
            if query not in matches[key]["queries"]:
                matches[key]["queries"].append(query)

    lines = [
        "[mnemoverse] Automatic collab:autogis startup retrieval completed.",
        "GitHub/repo remain authoritative; these are context pointers.",
    ]
    if not matches:
        lines.append("No matching STATUS handoff, BLOCKER, or DECISION entries.")
    for match in list(matches.values())[:_MNEMOVERSE_MAX_ITEMS]:
        labels = ", ".join(match["queries"])
        lines.append(
            "- [%s] atom_id=%s\n  %s"
            % (labels, match["atom_id"], match["content"].replace("\n", "\n  "))
        )
    if len(matches) > _MNEMOVERSE_MAX_ITEMS:
        lines.append(
            "- %d additional match(es) omitted; use memory_read for details."
            % (len(matches) - _MNEMOVERSE_MAX_ITEMS)
        )
    return "\n".join(lines)


def additional_context(payload, reg_path, memory_context=""):
    """The SessionStart additionalContext: the standing policy, plus a one-time
    nudge to isolate into a worktree when another live session already shares
    this main working tree (the gotcha-#1 contention condition)."""
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    sharers = registry.tree_sharers(reg_path, sid, registry.repo_root(cwd)) \
        if sid else []
    parts = [_POLICY]
    if sharers:
        parts.append(
            "[coord] %d other session(s) share this main working tree. "
            "Concurrent checkouts here will move your HEAD. Isolate now: "
            "EnterWorktree, then run 'python "
            ".claude/coordination/coord_cli.py resync'." % len(sharers)
        )
    if memory_context:
        parts.append(memory_context)
    return "\n\n".join(parts)


def main():
    memory_context = mnemoverse_context()
    context = _POLICY + "\n\n" + memory_context
    try:
        payload = json.load(sys.stdin)
        reg_path = _reg_path(payload)
        claim_session(payload, reg_path)
        context = additional_context(payload, reg_path, memory_context)
    except Exception:
        pass
    # State the read-only-main policy (+ nudge, if contended) as session
    # context (main session only; subagents are covered by the hook itself).
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
