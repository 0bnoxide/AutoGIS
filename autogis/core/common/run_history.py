# autogis/core/common/run_history.py
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
_NONE_SENTINEL = "__None__"


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

    def write(self, record: RunRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            exists = self._path.exists()
            with self._path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_FIELDS)
                if not exists:
                    writer.writeheader()
                writer.writerow(_encode(record))
        except Exception as exc:
            log.warning("RunHistory.write failed (best-effort): %s", exc)

    def _load(self) -> list[RunRecord]:
        if not self._path.exists():
            return []
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                return [_decode(row) for row in csv.DictReader(fh)]
        except Exception as exc:
            raise RunHistoryError(
                f"Cannot read run history at {self._path}: {exc}"
            ) from exc

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
