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
