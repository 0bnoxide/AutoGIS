# autogis/core/common/run_history.py
from __future__ import annotations

import csv
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import msvcrt
except ImportError:  # non-Windows: module stays importable, lock is a no-op
    msvcrt = None

log = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
_NONE_SENTINEL = "__None__"

# ponytail: 1 GiB sentinel offset -- revisit if run_history.csv ever
# approaches this size.
_LOCK_OFFSET = 1 << 30


@contextmanager
def _sentinel_lock(fh):
    """Hold a mandatory OS byte-range lock on one sentinel byte past EOF.

    Windows byte-range locks are OS-enforced (including over SMB shares --
    the shared-project-drive deployment scenario) and auto-released if the
    process dies, unlike a sidecar lockfile, which would leak and need
    stale-lock heuristics. Locking a byte at _LOCK_OFFSET -- far past any
    plausible file size -- rather than a real data byte means a process that
    ignores this convention degrades to the old unlocked behavior instead of
    hitting ERROR_LOCK_VIOLATION mid-read. See ADR-0051.

    Seeks happen on the raw fd, bypassing Python's buffering, so enter this
    only while the wrapper's buffer is clean (immediately after open), and
    flush() before the block exits on the write path. LK_LOCK retries
    internally for ~10 s then raises OSError; callers treat that like any
    other I/O failure.
    """
    if msvcrt is None:
        yield
        return
    fd = fh.fileno()

    def _at_sentinel(op: int) -> None:
        pos = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, op, 1)
        finally:
            os.lseek(fd, pos, os.SEEK_SET)

    _at_sentinel(msvcrt.LK_LOCK)
    try:
        yield
    finally:
        _at_sentinel(msvcrt.LK_UNLCK)


class RunHistoryError(Exception):
    pass


@dataclass
class RunRecord:
    run_id: str
    tool_name: str
    site_id: str
    event_id: Optional[str]
    started_at: datetime
    finished_at: datetime
    status: str          # "success" | "warning" | "error" | "cancelled"
    inputs: dict
    outputs: dict
    qa_count_error: int
    qa_count_warning: int
    qa_count_info: int
    message: str


_FIELDS = [
    "run_id", "tool_name", "site_id", "event_id",
    "started_at", "finished_at", "status",
    "inputs", "outputs",
    "qa_count_error", "qa_count_warning", "qa_count_info",
    "message",
]


def _encode(record: RunRecord) -> dict:
    return {
        "run_id": record.run_id,
        "tool_name": record.tool_name,
        "site_id": record.site_id,
        "event_id": _NONE_SENTINEL if record.event_id is None else record.event_id,
        "started_at": record.started_at.strftime(_DATETIME_FMT),
        "finished_at": record.finished_at.strftime(_DATETIME_FMT),
        "status": record.status,
        "inputs": json.dumps(record.inputs),
        "outputs": json.dumps(record.outputs),
        "qa_count_error": record.qa_count_error,
        "qa_count_warning": record.qa_count_warning,
        "qa_count_info": record.qa_count_info,
        "message": record.message,
    }


def _decode(row: dict) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        tool_name=row["tool_name"],
        site_id=row["site_id"],
        event_id=None if row["event_id"] == _NONE_SENTINEL else row["event_id"],
        started_at=datetime.strptime(row["started_at"], _DATETIME_FMT),
        finished_at=datetime.strptime(row["finished_at"], _DATETIME_FMT),
        status=row["status"],
        inputs=json.loads(row["inputs"]),
        outputs=json.loads(row["outputs"]),
        qa_count_error=int(row["qa_count_error"]),
        qa_count_warning=int(row["qa_count_warning"]),
        qa_count_info=int(row["qa_count_info"]),
        message=row["message"],
    )


class RunHistory:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._cache: Optional[list[RunRecord]] = None

    def write(self, record: RunRecord) -> None:
        try:
            # Encode *before* opening/locking: if this raises (e.g. an
            # unserializable value in record.inputs/outputs), nothing has
            # been written yet, so there's no staged header left to flush
            # outside the lock on the exception unwind (see the finally
            # below for why that ordering matters).
            row = _encode(record)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a+", newline="", encoding="utf-8") as fh:
                with _sentinel_lock(fh):
                    writer = csv.DictWriter(fh, fieldnames=_FIELDS)
                    try:
                        # Size check *under the lock* is atomic w.r.t. other
                        # lockers -- the old Path.exists() check before open
                        # was a check-then-act race that let two concurrent
                        # first-writers both emit a header row, corrupting
                        # the file for every later reader.
                        if os.fstat(fh.fileno()).st_size == 0:
                            writer.writeheader()
                        writer.writerow(row)
                    finally:
                        # Must flush while still holding the lock -- a
                        # buffered header/row left unflushed here would
                        # otherwise hit disk on fh.close() *after* the lock
                        # is released (the inner `with` exits, and only then
                        # the outer `with` closes/flushes fh), letting a
                        # concurrent writer's clean write land in between
                        # and reopening the exact duplicate-header race this
                        # lock exists to close.
                        fh.flush()
        except Exception as exc:
            log.warning("RunHistory.write failed (best-effort): %s", exc)
        finally:
            self._cache = None

    def _load(self) -> list[RunRecord]:
        # Cached per instance: no call site interleaves write() and
        # query()/latest() on the same instance, so each instance is
        # effectively a read-only snapshot and re-parsing the CSV on every
        # call is pure waste.
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            self._cache = []
            return self._cache
        try:
            # "r+" (not "r") because msvcrt.locking requires a handle opened
            # for writing, even though we only read here -- but only where the
            # lock actually engages. Off Windows the sentinel lock is a
            # documented no-op (ADR-0051), so demanding a writable handle
            # there only made query()/latest() fail on read-only files and
            # read-only mounts (issue #432).
            mode = "r+" if msvcrt is not None else "r"
            with self._path.open(mode, newline="", encoding="utf-8") as fh:
                with _sentinel_lock(fh):
                    self._cache = [_decode(row) for row in csv.DictReader(fh)]
        except Exception as exc:
            raise RunHistoryError(
                f"Cannot read run history at {self._path}: {exc}"
            ) from exc
        return self._cache

    def query(
        self,
        site_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        since: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> list[RunRecord]:
        records = self._load()
        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        if tool_name is not None:
            records = [r for r in records if r.tool_name == tool_name]
        if since is not None:
            records = [r for r in records if r.finished_at >= since]
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    def latest(self, tool_name: str, site_id: str) -> Optional[RunRecord]:
        matches = self.query(tool_name=tool_name, site_id=site_id)
        if not matches:
            return None
        # Tie-break by insertion order (index) so last-written wins when
        # two records share the same second (CSV datetime is second-precision).
        return max(enumerate(matches), key=lambda x: (x[1].finished_at, x[0]))[1]
