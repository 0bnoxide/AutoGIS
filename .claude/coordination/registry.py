"""Local session-coordination claim registry (Tier 1 — reflexes).

Pure-stdlib, cross-platform. Records active resource claims by parallel Claude
Code sessions so a PreToolUse hook can block colliding git/edit operations.
Session tooling under .claude/ — must not import autogis/arcpy/arcgis.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import time
from datetime import datetime, timezone

DEFAULT_TTL_SEC = 1800
_LOCK_STALE_SEC = 30


def _norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


def samepath(a, b):
    return _norm(a) == _norm(b)


def repo_root(cwd=None):
    """Resolve the canonical repository root (the MAIN working tree), even when
    called from inside a linked git worktree.

    The coordination registry must be a SINGLE shared file at the main root so
    parallel sessions in different worktrees can see each other's claims. A
    worktree's ``$CLAUDE_PROJECT_DIR`` (and its ``.git`` *file*) point at the
    worktree, not the main root — so git-common-dir resolution is PRIMARY here
    and the env var / cwd is only a fail-soft fallback when git is unavailable.
    """
    cwd = cwd or os.getcwd()
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=3)
        common = r.stdout.strip()
        if r.returncode == 0 and common:
            # git's relative output (e.g. ".git") is relative to -C cwd, not to
            # this process's cwd, so join against cwd before resolving.
            if not os.path.isabs(common):
                common = os.path.join(str(cwd), common)
            return os.path.dirname(os.path.abspath(common))
    except Exception:
        pass
    return os.environ.get("CLAUDE_PROJECT_DIR") or str(cwd)


def claims_path(cwd=None):
    """Absolute path to the shared claim registry JSON at the canonical root."""
    return os.path.join(repo_root(cwd), ".claude", "coordination", "claims.json")


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
    # Windows: os.replace fails with PermissionError while another process has
    # the target open for reading (CRT opens lack FILE_SHARE_DELETE) — and the
    # hook reads this file on every tool call of every session. Readers hold it
    # only for a sub-ms json.load, so brief retries absorb the collision; on
    # final failure clean up the .tmp and re-raise (callers fail open).
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.02)


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


def tree_sharers(path, session_id, root, now=None):
    """Live `worktree` claims by *another identified* session whose value == root.

    Empty/missing session_id (orphan claims) are ignored: they cannot
    meaningfully be 'another session' and would otherwise make the hard guard
    false-block.
    """
    r = _norm(root)
    return [c for c in list_claims(path, now=now)
            if c.get("session_id") and c.get("session_id") != session_id
            and c.get("kind") == "worktree"
            and _norm(c.get("value", "")) == r]
