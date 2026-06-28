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
