"""index_field_attachments.py — Tool 6.5 SyncFieldAttachments, envmon-side index.

The AGOL download half already ships as the attachment harvester
(``autogis/core/harvest/``), which downloads attachments and writes a
CSV/JSON manifest. This tool is purely the envmon-side half: it reads that
manifest and populates the ``AttachmentIndex`` SQLite table so other envmon
tools (boring logs, wells, dashboards) can join records to their local
attachments. No live AGOL call — fully headless, stdlib only.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from ..common.schema.attachments import AttachmentIndex
from ..common.sqlite_schema import create_table_sql, insert_rows

_EXT_TYPES = {
    ".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".heic": "photo",
    ".tif": "photo", ".tiff": "photo",
    ".pdf": "document", ".doc": "document", ".docx": "document",
    ".xls": "spreadsheet", ".xlsx": "spreadsheet", ".csv": "spreadsheet",
}


def classify_attachment(name: str) -> str:
    """photo / document / spreadsheet / other, from the file extension."""
    return _EXT_TYPES.get(Path(name or "").suffix.lower(), "other")


def load_manifest(path: Path) -> list[dict]:
    """Read a harvester manifest — ``.json`` or CSV (both come from
    ``harvest.manifest.Manifest.write``).

    A truncated/malformed manifest or broken encoding is reported as a
    ``ValueError`` naming the file, not a raw ``json.JSONDecodeError`` /
    ``UnicodeDecodeError`` traceback (issue #496; same idiom as #439).
    """
    p = Path(path)
    try:
        if p.suffix.lower() == ".json":
            rows = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(
                    f"Malformed manifest {p}: expected a JSON array of rows, "
                    f"got {type(rows).__name__} (#503)")
            return rows
        with p.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (json.JSONDecodeError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"Malformed manifest {p}: {exc}") from exc


def _i(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_attachment_index(
    rows: list[dict], *, related_table: str = "",
    synced: Optional[datetime] = None, qa: Optional[QACollector] = None,
) -> list[AttachmentIndex]:
    """Map manifest rows (AttachmentResult fields) to AttachmentIndex records.

    Rows without a parseable ``attachment_id`` are skipped; if *qa* is
    supplied the skip is surfaced (never silent).
    """
    synced = synced or datetime.now()
    out: list[AttachmentIndex] = []
    skipped = 0
    unjoinable = 0
    for row in rows:
        aid = _i(row.get("attachment_id"))
        if aid is None:
            skipped += 1
            continue
        name = row.get("original_name") or ""
        row_related_table = row.get("source_table") or related_table
        if not row_related_table:
            unjoinable += 1
        out.append(AttachmentIndex(
            attachment_id=aid,
            related_table=row_related_table,
            related_id=str(row.get("objectid") or ""),
            original_name=name,
            local_path=row.get("saved_path") or "",
            attachment_type=classify_attachment(name),
            size_bytes=_i(row.get("size")),
            checksum=row.get("checksum") or "",
            status=row.get("disposition") or row.get("status") or "",
            synced_date=synced,
        ))
    if skipped and qa is not None:
        qa.add(SEV_WARNING, "manifest_rows_skipped",
               f"{skipped} manifest row(s) skipped: missing/invalid "
               f"attachment_id")
    if unjoinable and qa is not None:
        qa.add(SEV_WARNING, "attachment_related_table_missing",
               f"{unjoinable} record(s) written with an empty related_table "
               f"— the manifest row has no source_table and no "
               f"--related-table override was given, so these attachments "
               f"aren't joinable to any table yet.")
    return out


def validate_attachment_index(
    records: list[AttachmentIndex], qa: QACollector,
) -> None:
    """Cross-check built index records, writing issues to *qa*."""
    for r in records:
        if r.status == "downloaded" and not r.local_path:
            qa.add(SEV_ERROR, "downloaded_missing_path",
                   f"Attachment {r.attachment_id} ({r.original_name!r}) is "
                   f"marked downloaded but has no local path.")
    # Intentionally no on-disk existence check — manifests may come from a
    # different machine than this one; add a --check-files pass if stale-path
    # detection is ever needed.
    counts = Counter(r.attachment_type for r in records)
    by_type = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    qa.add(SEV_INFO, "index_summary",
           f"{len(records)} attachment(s)" + (f": {by_type}" if by_type else ""))


def write_attachment_index(
    db_path: Path, records: list[AttachmentIndex], *, replace: bool = False,
) -> int:
    """Persist records to the AttachmentIndex SQLite table. Returns count.

    Appends by default; ``replace=True`` clears existing rows first (re-index
    of a refreshed manifest).
    """
    p = Path(db_path)
    if p.parent != Path("."):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        conn.execute(create_table_sql(AttachmentIndex))
        if replace:
            conn.execute(f'DELETE FROM "{AttachmentIndex.table_name}"')
        n = insert_rows(conn, AttachmentIndex, records)
        conn.commit()
    finally:
        conn.close()
    return n
