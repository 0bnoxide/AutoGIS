"""source_registry.py — append-only CSV registry of ingested source documents.

Tracks which files were processed by which tool, their SHA-256 hash, and
site/event context. Follows the append-only RunHistory pattern in
``autogis/core/common/run_history.py``. Arcpy-free; stdlib only.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_FIELDS = [
    "registered_at",
    "file_path",
    "sha256",
    "file_size_bytes",
    "site_id",
    "event_id",
    "tool",
    "notes",
]


class SourceRegistryError(Exception):
    pass


@dataclass
class SourceDocRecord:
    registered_at: str      # ISO-8601 datetime string
    file_path: str
    sha256: str             # hex digest, 64 chars
    file_size_bytes: int
    site_id: str
    event_id: str
    tool: str
    notes: str = ""


def compute_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of *path* (reads in 64 KiB chunks)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode(row: dict) -> SourceDocRecord:
    return SourceDocRecord(
        registered_at=row["registered_at"],
        file_path=row["file_path"],
        sha256=row["sha256"],
        file_size_bytes=int(row["file_size_bytes"]),
        site_id=row["site_id"],
        event_id=row["event_id"],
        tool=row["tool"],
        notes=row.get("notes", ""),
    )


class SourceRegistry:
    """Thin wrapper around an append-only CSV source-document registry.

    The registry CSV columns are exactly the fields of :class:`SourceDocRecord`.
    A header row is written only when the file is first created. The registry
    itself does not block duplicates — that is the caller's job via
    :meth:`is_registered`.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def register(self, record: SourceDocRecord) -> None:
        """Append *record* to the registry CSV, creating the file if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        exists = self._path.exists()
        with self._path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow({
                "registered_at": record.registered_at,
                "file_path": record.file_path,
                "sha256": record.sha256,
                "file_size_bytes": str(record.file_size_bytes),
                "site_id": record.site_id,
                "event_id": record.event_id,
                "tool": record.tool,
                "notes": record.notes,
            })

    def _load(self) -> list[SourceDocRecord]:
        if not self._path.exists():
            return []
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                return [_decode(row) for row in csv.DictReader(fh)]
        except (OSError, KeyError, ValueError) as exc:
            raise SourceRegistryError(
                f"Cannot read source registry at {self._path}: {exc}"
            ) from exc

    def list_records(
        self,
        site_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> list[SourceDocRecord]:
        """Return all records, optionally filtered by *site_id* and/or *event_id*."""
        records = self._load()
        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        if event_id is not None:
            records = [r for r in records if r.event_id == event_id]
        return records

    def is_registered(self, file_path: str, sha256: str) -> bool:
        """Return True if a record with matching *file_path* and *sha256* exists."""
        return any(
            r.file_path == file_path and r.sha256 == sha256
            for r in self._load()
        )
