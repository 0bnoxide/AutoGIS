"""event_results_merger.py — multi-event CSV concatenator with dedup + manifest."""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

_DEFAULT_DEDUP_KEY = ("SampleID", "AnalyteName", "ReportedUnits")


@dataclass
class SourceFile:
    path: Path
    event_label: str
    event_date: str
    sha256: str
    row_count: int


@dataclass
class MergeResult:
    merged_path: Path
    manifest_path: Optional[Path]
    source_files: list
    total_rows: int
    duplicate_rows_dropped: int
    qa: QACollector


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def infer_event_label(path: Path, pattern: str = r"(\d{8})") -> str:
    m = re.search(pattern, path.stem)
    if m:
        return m.group(1)
    return path.stem


def merge_event_results(
    source_paths: list,
    out_path: Path,
    *,
    event_labels: Optional[list] = None,
    dedup_key: tuple = _DEFAULT_DEDUP_KEY,
    add_source_column: bool = True,
    manifest_path: Optional[Path] = None,
    qa: Optional[QACollector] = None,
) -> MergeResult:
    if qa is None:
        qa = QACollector()

    all_rows: list[dict] = []
    source_files: list[SourceFile] = []

    for idx, src in enumerate(source_paths):
        src = Path(src)
        label = (event_labels[idx] if event_labels and idx < len(event_labels)
                 else infer_event_label(src))
        if not src.exists():
            qa.add(QARecord(SEV_ERROR, "missing_source",
                            f"Source file not found: {src}"))
            source_files.append(SourceFile(path=src, event_label=label,
                                           event_date="", sha256="", row_count=0))
            continue
        sha = _sha256_file(src)
        with src.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if add_source_column:
            for r in rows:
                r["EventLabel"] = label
        all_rows.extend(rows)
        source_files.append(SourceFile(
            path=src, event_label=label, event_date="",
            sha256=sha, row_count=len(rows),
        ))

    # Dedup
    seen_keys: set[tuple] = set()
    deduped: list[dict] = []
    dropped = 0
    for r in all_rows:
        key = tuple(r.get(k, "") for k in dedup_key)
        if key in seen_keys:
            dropped += 1
        else:
            seen_keys.add(key)
            deduped.append(r)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if deduped:
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(deduped[0].keys()))
            w.writeheader()
            for r in deduped:
                w.writerow(r)
    else:
        out_path.write_text("")

    if manifest_path:
        write_merge_manifest(source_files, Path(manifest_path))

    qa.add(QARecord(SEV_INFO, "merge_complete",
                    f"{len(source_files)} sources, {len(deduped)} rows, "
                    f"{dropped} duplicates dropped → {out_path}"))

    return MergeResult(
        merged_path=out_path,
        manifest_path=Path(manifest_path) if manifest_path else None,
        source_files=source_files,
        total_rows=len(deduped),
        duplicate_rows_dropped=dropped,
        qa=qa,
    )


def write_merge_manifest(source_files: list, manifest_path: Path) -> None:
    fields = ["source_file", "event_label", "event_date", "sha256", "row_count"]
    with Path(manifest_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for sf in source_files:
            w.writerow({
                "source_file": str(sf.path),
                "event_label": sf.event_label,
                "event_date": sf.event_date,
                "sha256": sf.sha256,
                "row_count": sf.row_count,
            })
