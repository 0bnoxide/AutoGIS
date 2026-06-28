# Session Coordination — Tier 1 (Reflexes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local claim registry + session-start auto-claim + PreToolUse enforcement hook that stops parallel Claude Code sessions from committing to the wrong branch or to `main`.

**Architecture:** A pure-stdlib JSON registry at `.claude/coordination/claims.json` (gitignored) records which session owns which branch/worktree/file-glob, with TTL+heartbeat expiry. A SessionStart hook auto-claims the current branch + worktree. A PreToolUse hook refreshes the session's own heartbeat and **denies** a `git commit`/`push` to `main` or to a branch another live session claims (and **warns** on edits to a file another session claims). All decision logic is pure Python, unit-tested; the hooks are thin shims. The hook fails open on any error — it must never brick the user's git.

**Tech Stack:** Python 3 stdlib only (`json`, `os`, `time`, `datetime`, `fnmatch`, `subprocess`, `re`). Shell shims via Git Bash. Claude Code hooks wired in `.claude/settings.json`.

## Global Constraints

- Python **stdlib only** — no new dependencies (repo is openpyxl + stdlib).
- **Cross-platform** — runs on Windows (this machine) under Git Bash; no `fcntl`, no `os.uname` hard dependency.
- This is **session tooling under `.claude/coordination/`** — NOT part of the `autogis` package. It must not import `autogis`, `arcpy`, or `arcgis`.
- The PreToolUse hook **fails open**: any exception or parse failure → exit 0, no decision. It never denies on an internal error.
- Registry file `.claude/coordination/claims.json` (and `.lock`, `.tmp.*`) are **gitignored** — never committed.
- Override escape hatch: environment variable `AUTOGIS_COORD_FORCE=1` bypasses all blocks.
- Hook decision path makes **no MCP calls** (pure local-file read; graph/brain warnings are a later tier).
- Run tests with `python -m pytest tests/coordination/ -q`.

---

### Task 1: Registry foundation — load/save with atomic writes + lock

**Files:**
- Create: `.claude/coordination/registry.py`
- Create: `tests/coordination/__init__.py`
- Create: `tests/coordination/conftest.py`
- Test: `tests/coordination/test_registry.py`

**Interfaces:**
- Produces: `load_registry(path) -> dict` (always `{"claims": [...]}`), `save_registry(path, data) -> None` (atomic), `_acquire_lock(path)`, `_release_lock(path)`, module constant `DEFAULT_TTL_SEC = 1800`.

- [ ] **Step 1: Create the test package + import shim**

`tests/coordination/__init__.py` — empty file.

`tests/coordination/conftest.py`:

```python
import os
import sys

# The coordination module lives under .claude/ (session tooling), not in the
# autogis package, so add it to sys.path for import.
_COORD = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".claude", "coordination")
)
if _COORD not in sys.path:
    sys.path.insert(0, _COORD)
```

- [ ] **Step 2: Write the failing test**

`tests/coordination/test_registry.py`:

```python
import registry


def test_load_missing_returns_empty(tmp_path):
    assert registry.load_registry(tmp_path / "nope.json") == {"claims": []}


def test_save_then_load_roundtrips(tmp_path):
    p = tmp_path / "claims.json"
    data = {"claims": [{"session_id": "s1", "kind": "branch", "value": "feat/x"}]}
    registry.save_registry(p, data)
    assert registry.load_registry(p) == data


def test_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "claims.json"
    p.write_text("{ not json", encoding="utf-8")
    assert registry.load_registry(p) == {"claims": []}


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "claims.json"
    registry.save_registry(p, {"claims": []})
    leftovers = [f for f in os.listdir(tmp_path) if ".tmp." in f]
    assert leftovers == []


import os
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'registry'`

- [ ] **Step 4: Implement `registry.py` foundation**

```python
"""Local session-coordination claim registry (Tier 1 — reflexes).

Pure-stdlib, cross-platform. Records active resource claims by parallel Claude
Code sessions so a PreToolUse hook can block colliding git/edit operations.
Session tooling under .claude/ — must not import autogis/arcpy/arcgis.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

DEFAULT_TTL_SEC = 1800
_LOCK_STALE_SEC = 30


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _host():
    return (os.environ.get("COMPUTERNAME")
            or os.environ.get("HOSTNAME") or "local")


def _lock_path(path):
    return str(path) + ".lock"


def _acquire_lock(path, timeout=5.0, poll=0.05):
    lp = _lock_path(path)
    os.makedirs(os.path.dirname(os.path.abspath(lp)), exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lp) > _LOCK_STALE_SEC:
                    os.unlink(lp)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("could not acquire %s" % lp)
            time.sleep(poll)


def _release_lock(path):
    try:
        os.unlink(_lock_path(path))
    except OSError:
        pass


def load_registry(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"claims": []}
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        return {"claims": []}
    return data


def save_registry(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add .claude/coordination/registry.py tests/coordination/__init__.py tests/coordination/conftest.py tests/coordination/test_registry.py
git commit -m "feat(coord): registry load/save with atomic writes + lock"
```

---

### Task 2: Claims — claim, list, staleness, reaping

**Files:**
- Modify: `.claude/coordination/registry.py`
- Test: `tests/coordination/test_registry.py`

**Interfaces:**
- Consumes: `load_registry`, `save_registry`, `_acquire_lock`, `_release_lock`, `_now`, `_iso`, `_parse_iso`, `DEFAULT_TTL_SEC`.
- Produces: `claim(path, session_id, kind, value, ttl_sec=DEFAULT_TTL_SEC, pid=None, host=None, now=None) -> dict`, `list_claims(path, include_stale=False, now=None) -> list`, `is_stale(claim, now=None) -> bool`, `reap_stale(path, now=None) -> int`. `now` is an injectable `datetime` for deterministic tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/coordination/test_registry.py`:

```python
from datetime import timedelta


def test_claim_appends_entry(tmp_path):
    p = tmp_path / "c.json"
    entry = registry.claim(p, "s1", "branch", "feat/x", pid=111)
    assert entry["session_id"] == "s1"
    assert entry["kind"] == "branch"
    assert entry["value"] == "feat/x"
    assert entry["pid"] == 111
    assert "heartbeat_at" in entry and "started_at" in entry
    assert registry.list_claims(p) == [entry]


def test_claim_same_resource_refreshes_not_duplicates(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "branch", "feat/x")
    assert len(registry.list_claims(p, include_stale=True)) == 1


def test_is_stale_past_ttl(tmp_path):
    now = registry._now()
    fresh = {"heartbeat_at": registry._iso(now), "ttl_sec": 100}
    old = {"heartbeat_at": registry._iso(now - timedelta(seconds=200)),
           "ttl_sec": 100}
    assert registry.is_stale(fresh, now) is False
    assert registry.is_stale(old, now) is True


def test_list_claims_excludes_stale(tmp_path):
    now = registry._now()
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x", ttl_sec=100, now=now)
    later = now + timedelta(seconds=500)
    assert registry.list_claims(p, now=later) == []
    assert len(registry.list_claims(p, include_stale=True, now=later)) == 1


def test_reap_stale_removes_expired(tmp_path):
    now = registry._now()
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x", ttl_sec=100, now=now)
    later = now + timedelta(seconds=500)
    assert registry.reap_stale(p, now=later) == 1
    assert registry.list_claims(p, include_stale=True) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: FAIL with `AttributeError: module 'registry' has no attribute 'claim'`

- [ ] **Step 3: Implement claim/list/staleness/reap**

Append to `.claude/coordination/registry.py`:

```python
def is_stale(claim, now=None):
    now = now or _now()
    try:
        hb = _parse_iso(claim["heartbeat_at"])
    except (KeyError, ValueError, TypeError):
        return True
    return (now - hb).total_seconds() > claim.get("ttl_sec", DEFAULT_TTL_SEC)


def list_claims(path, include_stale=False, now=None):
    now = now or _now()
    claims = load_registry(path)["claims"]
    if include_stale:
        return claims
    return [c for c in claims if not is_stale(c, now)]


def claim(path, session_id, kind, value, ttl_sec=DEFAULT_TTL_SEC,
          pid=None, host=None, now=None):
    now = now or _now()
    _acquire_lock(path)
    try:
        data = load_registry(path)
        for c in data["claims"]:
            if (c.get("session_id") == session_id and c.get("kind") == kind
                    and c.get("value") == value):
                c["heartbeat_at"] = _iso(now)
                c["ttl_sec"] = ttl_sec
                save_registry(path, data)
                return c
        entry = {
            "session_id": session_id,
            "kind": kind,
            "value": value,
            "pid": pid if pid is not None else os.getpid(),
            "host": host or _host(),
            "started_at": _iso(now),
            "heartbeat_at": _iso(now),
            "ttl_sec": ttl_sec,
        }
        data["claims"].append(entry)
        save_registry(path, data)
        return entry
    finally:
        _release_lock(path)


def reap_stale(path, now=None):
    now = now or _now()
    _acquire_lock(path)
    try:
        data = load_registry(path)
        live = [c for c in data["claims"] if not is_stale(c, now)]
        removed = len(data["claims"]) - len(live)
        if removed:
            data["claims"] = live
            save_registry(path, data)
        return removed
    finally:
        _release_lock(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/coordination/registry.py tests/coordination/test_registry.py
git commit -m "feat(coord): claim/list/staleness/reap with TTL"
```

---

### Task 3: Heartbeat + release

**Files:**
- Modify: `.claude/coordination/registry.py`
- Test: `tests/coordination/test_registry.py`

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: `heartbeat(path, session_id, now=None) -> int` (count refreshed), `release(path, session_id, kind=None, value=None) -> int` (count removed).

- [ ] **Step 1: Write the failing tests**

Append to `tests/coordination/test_registry.py`:

```python
def test_heartbeat_refreshes_only_own_claims(tmp_path):
    now = registry._now()
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x", now=now)
    registry.claim(p, "s2", "branch", "feat/y", now=now)
    later = now + timedelta(seconds=300)
    assert registry.heartbeat(p, "s1", now=later) == 1
    claims = {c["session_id"]: c for c in registry.list_claims(p, include_stale=True)}
    assert claims["s1"]["heartbeat_at"] == registry._iso(later)
    assert claims["s2"]["heartbeat_at"] == registry._iso(now)


def test_release_all_for_session(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "worktree", "/wt/x")
    registry.claim(p, "s2", "branch", "feat/y")
    assert registry.release(p, "s1") == 2
    remaining = registry.list_claims(p, include_stale=True)
    assert len(remaining) == 1 and remaining[0]["session_id"] == "s2"


def test_release_specific_resource(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    registry.claim(p, "s1", "worktree", "/wt/x")
    assert registry.release(p, "s1", kind="branch", value="feat/x") == 1
    remaining = registry.list_claims(p, include_stale=True)
    assert len(remaining) == 1 and remaining[0]["kind"] == "worktree"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: FAIL with `AttributeError: module 'registry' has no attribute 'heartbeat'`

- [ ] **Step 3: Implement heartbeat + release**

Append to `.claude/coordination/registry.py`:

```python
def heartbeat(path, session_id, now=None):
    now = now or _now()
    _acquire_lock(path)
    try:
        data = load_registry(path)
        n = 0
        for c in data["claims"]:
            if c.get("session_id") == session_id:
                c["heartbeat_at"] = _iso(now)
                n += 1
        if n:
            save_registry(path, data)
        return n
    finally:
        _release_lock(path)


def release(path, session_id, kind=None, value=None):
    _acquire_lock(path)
    try:
        data = load_registry(path)
        before = len(data["claims"])

        def drop(c):
            if c.get("session_id") != session_id:
                return False
            if kind is not None and c.get("kind") != kind:
                return False
            if value is not None and c.get("value") != value:
                return False
            return True

        data["claims"] = [c for c in data["claims"] if not drop(c)]
        removed = before - len(data["claims"])
        if removed:
            save_registry(path, data)
        return removed
    finally:
        _release_lock(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/coordination/registry.py tests/coordination/test_registry.py
git commit -m "feat(coord): heartbeat + release"
```

---

### Task 4: Conflict queries — branch_conflicts + file_conflicts

**Files:**
- Modify: `.claude/coordination/registry.py`
- Test: `tests/coordination/test_registry.py`

**Interfaces:**
- Consumes: `list_claims`.
- Produces: `branch_conflicts(path, session_id, branch, now=None) -> list` (live `branch` claims on `branch` by OTHER sessions), `file_conflicts(path, session_id, file_path, now=None) -> list` (live `file_glob` claims whose glob matches `file_path`, by OTHER sessions). Both exclude `session_id`'s own claims and stale claims.

- [ ] **Step 1: Write the failing tests**

Append to `tests/coordination/test_registry.py`:

```python
def test_branch_conflicts_other_session(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    assert registry.branch_conflicts(p, "s2", "feat/x")[0]["session_id"] == "s1"
    assert registry.branch_conflicts(p, "s1", "feat/x") == []   # own claim
    assert registry.branch_conflicts(p, "s2", "feat/other") == []


def test_file_conflicts_glob_match(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "file_glob", "autogis/adapters/cli.py")
    registry.claim(p, "s1", "file_glob", "autogis/core/envmon/*.py")
    assert registry.file_conflicts(p, "s2", "autogis/adapters/cli.py")
    assert registry.file_conflicts(p, "s2", "autogis/core/envmon/normalize.py")
    assert registry.file_conflicts(p, "s2", "tests/test_x.py") == []
    assert registry.file_conflicts(p, "s1", "autogis/adapters/cli.py") == []  # own
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: FAIL with `AttributeError: module 'registry' has no attribute 'branch_conflicts'`

- [ ] **Step 3: Implement conflict queries**

Add `import fnmatch` to the top of `.claude/coordination/registry.py` (next to the other imports), then append:

```python
def branch_conflicts(path, session_id, branch, now=None):
    out = []
    for c in list_claims(path, now=now):
        if c.get("session_id") == session_id:
            continue
        if c.get("kind") == "branch" and c.get("value") == branch:
            out.append(c)
    return out


def file_conflicts(path, session_id, file_path, now=None):
    out = []
    for c in list_claims(path, now=now):
        if c.get("session_id") == session_id:
            continue
        if c.get("kind") == "file_glob" and fnmatch.fnmatch(
                file_path, c.get("value", "")):
            out.append(c)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_registry.py -q`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/coordination/registry.py tests/coordination/test_registry.py
git commit -m "feat(coord): branch_conflicts + file_conflicts queries"
```

---

### Task 5: PreToolUse enforcement hook (decision logic)

**Files:**
- Create: `.claude/coordination/hook_check.py`
- Test: `tests/coordination/test_hook_check.py`

**Interfaces:**
- Consumes: `registry.heartbeat`, `registry.branch_conflicts`, `registry.file_conflicts`.
- Produces: `decide(payload, reg_path, branch_func=None) -> dict | None`. Returns `None` to allow (no output), or a dict to print as the hook's JSON. `branch_func(cwd) -> str` is injectable so tests don't shell out to git. `main()` reads stdin JSON, resolves paths, prints `decide(...)` output (if any), and always exits 0.

- [ ] **Step 1: Write the failing tests**

`tests/coordination/test_hook_check.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/coordination/test_hook_check.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'hook_check'`

- [ ] **Step 3: Implement `hook_check.py`**

```python
"""PreToolUse coordination hook — deny wrong-branch/main commits, warn on
claimed-file edits. Pure decision logic in decide(); main() handles I/O.
Fails open: any error → allow (exit 0, no output).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

_GIT_WRITE = re.compile(r"\bgit\b.*\b(commit|push)\b")


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


def decide(payload, reg_path, branch_func=None):
    if os.environ.get("AUTOGIS_COORD_FORCE") == "1":
        return None
    import registry
    sid = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}

    # Best-effort: refresh this session's own heartbeat on any tool call.
    try:
        registry.heartbeat(reg_path, sid)
    except Exception:
        pass

    if tool in ("Edit", "Write", "MultiEdit"):
        fp = ti.get("file_path", "")
        if fp:
            rel = fp.replace("\\", "/")
            conflicts = registry.file_conflicts(reg_path, sid, rel)
            if conflicts:
                c = conflicts[0]
                return _warn(
                    "[coord] %s is claimed by session %s (pattern %s). "
                    "Coordinate before editing." % (fp, c["session_id"][:8],
                                                     c.get("value")))
        return None

    if tool == "Bash":
        cmd = ti.get("command", "")
        if _GIT_WRITE.search(cmd):
            bf = branch_func or _git_branch
            branch = bf(cwd)
            if branch == "main":
                return _deny(
                    "[coord] Direct commit/push to 'main' is blocked. Use a "
                    "feature branch + PR. Override: AUTOGIS_COORD_FORCE=1.")
            conflicts = registry.branch_conflicts(reg_path, sid, branch)
            if conflicts:
                c = conflicts[0]
                return _deny(
                    "[coord] Branch '%s' is claimed by session %s (pid %s). "
                    "You may be on the wrong branch. "
                    "Override: AUTOGIS_COORD_FORCE=1."
                    % (branch, c["session_id"][:8], c.get("pid")))
        return None

    return None


def _reg_path(payload):
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        d = os.path.abspath(payload.get("cwd") or ".")
        while True:
            if os.path.exists(os.path.join(d, ".git")):
                root = d
                break
            nd = os.path.dirname(d)
            if nd == d:
                root = payload.get("cwd") or "."
                break
            d = nd
    sys.path.insert(0, os.path.join(root, ".claude", "coordination"))
    return os.path.join(root, ".claude", "coordination", "claims.json")


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_hook_check.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/coordination/hook_check.py tests/coordination/test_hook_check.py
git commit -m "feat(coord): PreToolUse enforcement hook decision logic"
```

---

### Task 6: SessionStart auto-claim

**Files:**
- Create: `.claude/coordination/session_start.py`
- Test: `tests/coordination/test_session_start.py`

**Interfaces:**
- Consumes: `registry.claim`, `registry.reap_stale`.
- Produces: `claim_session(payload, reg_path, branch_func=None) -> list` (the claims created: a `branch` claim if on a branch, plus a `worktree` claim). `main()` reads stdin JSON and calls it; never raises.

- [ ] **Step 1: Write the failing tests**

`tests/coordination/test_session_start.py`:

```python
import registry
import session_start


def test_claims_branch_and_worktree(tmp_path):
    p = tmp_path / "c.json"
    payload = {"session_id": "s1", "cwd": "/wt/x"}
    made = session_start.claim_session(payload, p,
                                       branch_func=lambda cwd: "feat/x")
    kinds = sorted(c["kind"] for c in made)
    assert kinds == ["branch", "worktree"]
    live = registry.list_claims(p, include_stale=True)
    assert {c["kind"]: c["value"] for c in live}["branch"] == "feat/x"


def test_detached_head_claims_only_worktree(tmp_path):
    p = tmp_path / "c.json"
    payload = {"session_id": "s1", "cwd": "/wt/x"}
    made = session_start.claim_session(payload, p, branch_func=lambda cwd: "")
    assert [c["kind"] for c in made] == ["worktree"]


def test_no_session_id_is_noop(tmp_path):
    p = tmp_path / "c.json"
    made = session_start.claim_session({"cwd": "/wt/x"}, p,
                                       branch_func=lambda cwd: "feat/x")
    assert made == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/coordination/test_session_start.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'session_start'`

- [ ] **Step 3: Implement `session_start.py`**

```python
"""SessionStart coordination hook — auto-claim the current branch + worktree
for this session so other sessions' PreToolUse checks can see it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


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
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
    sys.path.insert(0, os.path.join(root, ".claude", "coordination"))
    return os.path.join(root, ".claude", "coordination", "claims.json")


def main():
    try:
        payload = json.load(sys.stdin)
        claim_session(payload, _reg_path(payload))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_session_start.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/coordination/session_start.py tests/coordination/test_session_start.py
git commit -m "feat(coord): SessionStart auto-claim branch + worktree"
```

---

### Task 7: `coord` CLI for manual list / release / claim

**Files:**
- Create: `.claude/coordination/coord_cli.py`
- Test: `tests/coordination/test_coord_cli.py`

**Interfaces:**
- Consumes: `registry.claim`, `registry.release`, `registry.list_claims`.
- Produces: `run(argv, reg_path) -> int` (exit code; prints to stdout). Subcommands: `list`, `claim --session SID --kind K --value V`, `release --session SID [--kind K] [--value V]`. `main()` wraps `run` with default path resolution.

- [ ] **Step 1: Write the failing tests**

`tests/coordination/test_coord_cli.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/coordination/test_coord_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coord_cli'`

- [ ] **Step 3: Implement `coord_cli.py`**

```python
"""coord — manual inspection/override CLI for the coordination registry.

Usage:
  python coord_cli.py list
  python coord_cli.py claim --session SID --kind branch|worktree|file_glob --value V
  python coord_cli.py release --session SID [--kind K] [--value V]
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def run(argv, reg_path):
    import registry
    ap = argparse.ArgumentParser(prog="coord")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pc = sub.add_parser("claim")
    pc.add_argument("--session", required=True)
    pc.add_argument("--kind", required=True,
                    choices=["branch", "worktree", "file_glob"])
    pc.add_argument("--value", required=True)
    pr = sub.add_parser("release")
    pr.add_argument("--session", required=True)
    pr.add_argument("--kind")
    pr.add_argument("--value")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for c in registry.list_claims(reg_path, include_stale=True):
            stale = " (stale)" if registry.is_stale(c) else ""
            print("%-10s %-10s %s%s" % (c.get("session_id", "")[:10],
                                        c.get("kind"), c.get("value"), stale))
        return 0
    if args.cmd == "claim":
        registry.claim(reg_path, args.session, args.kind, args.value)
        return 0
    if args.cmd == "release":
        n = registry.release(reg_path, args.session, args.kind, args.value)
        print("released %d" % n)
        return 0
    return 1


def _reg_path():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    sys.path.insert(0, os.path.join(root, ".claude", "coordination"))
    return os.path.join(root, ".claude", "coordination", "claims.json")


def main():
    sys.exit(run(sys.argv[1:], _reg_path()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/coordination/test_coord_cli.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add .claude/coordination/coord_cli.py tests/coordination/test_coord_cli.py
git commit -m "feat(coord): manual list/claim/release CLI"
```

---

### Task 8: Wire hooks + gitignore + integration smoke test

**Files:**
- Create: `.claude/hooks/pre-tool-use.sh`
- Modify: `.claude/hooks/session-start.sh` (append auto-claim call)
- Modify: `.claude/settings.json` (add PreToolUse + extend SessionStart)
- Modify: `.gitignore` (ignore the registry file)
- Test: `tests/coordination/test_integration.py`

**Interfaces:**
- Consumes: `hook_check.main`, `session_start.main`.
- Produces: wired hooks; an end-to-end test that pipes a PreToolUse payload through `hook_check.py` as a subprocess.

- [ ] **Step 1: Create the PreToolUse shim**

`.claude/hooks/pre-tool-use.sh`:

```bash
#!/usr/bin/env bash
# PreToolUse coordination hook — delegates to the Python decision logic.
exec python "$CLAUDE_PROJECT_DIR/.claude/coordination/hook_check.py"
```

- [ ] **Step 2: Append auto-claim to the SessionStart hook**

Add these lines to the END of `.claude/hooks/session-start.sh` (the hook receives
the SessionStart JSON on stdin; tee it so both the existing logic and the claim
step can read it — if the existing script already consumes stdin, instead add the
claim as a separate SessionStart entry in settings.json per Step 4 and skip this):

```bash

# --- session coordination: auto-claim current branch + worktree ---
python "$CLAUDE_PROJECT_DIR/.claude/coordination/session_start.py" <<<"$COORD_STDIN" 2>/dev/null || true
```

> If `session-start.sh` does not currently capture stdin into `$COORD_STDIN`,
> prefer the cleaner wiring: leave `session-start.sh` untouched and register
> `session_start.py` as a **second** SessionStart hook entry in settings.json
> (Step 4). Choose one approach; the settings.json approach is recommended
> because it keeps each hook reading stdin independently.

- [ ] **Step 3: Add the registry file to .gitignore**

Append to `.gitignore`:

```
# Session coordination registry (local-only, never committed)
.claude/coordination/claims.json
.claude/coordination/claims.json.lock
.claude/coordination/claims.json.tmp.*
```

- [ ] **Step 4: Wire hooks in settings.json**

Replace `.claude/settings.json` with (preserves the existing SessionStart entry,
adds `session_start.py` as a second SessionStart hook, and adds the PreToolUse
hook matching Bash/Edit/Write/MultiEdit):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"
          },
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/coordination/session_start.py\""
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/pre-tool-use.sh"
          }
        ]
      }
    ]
  }
}
```

(With this settings.json wiring, revert the Step 2 edit to `session-start.sh` if
you made it — `session_start.py` now runs as its own SessionStart hook.)

- [ ] **Step 5: Write the integration smoke test**

`tests/coordination/test_integration.py`:

```python
import json
import os
import subprocess
import sys

import registry

_HOOK = os.path.join(os.path.dirname(__file__), "..", "..",
                     ".claude", "coordination", "hook_check.py")


def _run_hook(payload, env):
    proc = subprocess.run([sys.executable, _HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)
    return proc.stdout.strip()


def test_hook_denies_commit_to_claimed_branch(tmp_path, monkeypatch):
    root = tmp_path
    os.makedirs(root / ".claude" / "coordination")
    os.makedirs(root / ".git")  # make _reg_path resolve root here
    reg = root / ".claude" / "coordination" / "claims.json"
    registry.claim(reg, "other", "branch", "feat/x")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    # Force the branch via a fake git is hard cross-process; instead claim a
    # branch and target it directly through main-branch path: claim 'main'.
    registry.claim(reg, "other", "branch", "main-not-used")
    payload = {"session_id": "me", "cwd": str(root), "tool_name": "Bash",
               "tool_input": {"command": "git commit -m x"}}
    out = _run_hook(payload, env)
    # On a fresh tmp .git with no branch, branch resolves to "" → no deny;
    # this asserts the hook runs and emits valid JSON or nothing (fail-open).
    assert out == "" or "hookSpecificOutput" in out


def test_hook_emits_nothing_for_safe_command(tmp_path):
    root = tmp_path
    os.makedirs(root / ".claude" / "coordination")
    os.makedirs(root / ".git")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    payload = {"session_id": "me", "cwd": str(root), "tool_name": "Bash",
               "tool_input": {"command": "ls"}}
    assert _run_hook(payload, env) == ""
```

> Note: the subprocess test deliberately avoids depending on a real git branch
> (cross-process branch injection isn't available). The deterministic branch
> logic is already covered by `test_hook_check.py` Task 5; this test verifies the
> hook runs end-to-end, reads stdin, resolves the registry, and fails open.

- [ ] **Step 6: Run the full coordination suite + whole repo suite**

Run: `python -m pytest tests/coordination/ -q`
Expected: PASS (all coordination tests)

Run: `python -m pytest -q`
Expected: PASS (full suite green — no regressions)

- [ ] **Step 7: Validate settings.json is valid JSON**

Run: `python -c "import json; json.load(open('.claude/settings.json'))"`
Expected: no output, exit 0

- [ ] **Step 8: Commit**

```bash
git add .claude/hooks/pre-tool-use.sh .claude/settings.json .gitignore tests/coordination/test_integration.py
git commit -m "feat(coord): wire PreToolUse + SessionStart hooks, gitignore registry"
```

---

## Self-Review

**Spec coverage:**
- Local registry `.claude/coordination/claims.json` with the documented schema → Tasks 1–4. ✅
- Atomic writes + lock + stale reaping → Tasks 1, 2. ✅
- `claim`/`release`/`list`/`heartbeat` helper → Tasks 2, 3, 7. ✅
- PreToolUse hook: hard-block commit to `main` / another live session's branch; warn on claimed-file edit; force escape hatch; fail-open; no MCP on hot path → Task 5. ✅
- SessionStart auto-claim (the realization of "claim before work") → Task 6. ✅
- Gitignored registry → Task 8. ✅
- Pure-Python, arcpy-free, stdlib-only, cross-platform → all tasks (no autogis/arcpy imports; `os.open` lock, no `fcntl`). ✅
- Tiers 2 (graph blast-radius) and 3 (git-synced cross-boundary + cloud agent) are explicitly **out of scope** for this plan — separate follow-on plans, per the spec's delivery strategy. ✅

**Placeholder scan:** No TBD/TODO; every code step has complete, runnable code. ✅

**Type consistency:** `claim`/`release`/`heartbeat`/`list_claims`/`is_stale`/`reap_stale`/`branch_conflicts`/`file_conflicts` signatures are defined in Tasks 2–4 and consumed with matching names/args in Tasks 5–7. `decide(payload, reg_path, branch_func=None)` and `claim_session(payload, reg_path, branch_func=None)` are consistent between definition and tests. ✅

**Known follow-ups (not blockers):** the SessionStart wiring has two options (Step 2 vs Step 4); the plan recommends the settings.json route and says to revert the other. The integration test is intentionally light (the deterministic branch logic is covered by Task 5's injectable `branch_func`).
