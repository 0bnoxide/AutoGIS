"""Batch-import multiple EDD workbooks from a manifest (Tool 2.2).

Headless, arcpy-free. Reads a manifest CSV mapping workbook paths to
LabEDD profiles, processes each through the EDD importer, and emits
normalised sample + result CSVs plus a batch manifest report.
"""
from __future__ import annotations

import csv
import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING


@dataclass
class BatchManifestRow:
    WorkbookPath: str
    ProfilePath: str
    SiteID: str
    BatchID: str
    Status: str          # OK | ERROR | SKIP
    SampleCount: int
    ResultCount: int
    ErrorSummary: str
    ProcessedAt: str


@dataclass
class BatchImportResult:
    manifest: List[BatchManifestRow] = field(default_factory=list)
    all_samples: list = field(default_factory=list)
    all_results: list = field(default_factory=list)
    qa: QACollector = field(default_factory=QACollector)


def read_manifest_csv(path: Path) -> list[dict]:
    """Read batch manifest CSV. Required columns: workbook_path, profile_path, site_id."""
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    missing = [k for k in ("workbook_path", "profile_path", "site_id")
               if rows and k not in rows[0]]
    if missing:
        raise ValueError(f"Manifest missing columns: {missing}")
    return rows


def manifest_rows_from_dir(
    edd_dir: Path,
    profile_path: Path,
    site_id: str,
    pattern: Optional[str] = None,
) -> list[dict]:
    """Synthesize manifest rows from a directory of EDD files.

    Alternate input mode for Tool 2.2 (the BatchEDDImport fold, ADR-0048):
    every file matching ``pattern`` shares one profile and site. Default
    pattern ``*.csv``; if nothing matches, falls back to ``*.xlsx``. An
    explicit pattern is used as-is with no fallback.
    """
    edd_dir = Path(edd_dir)
    files = sorted(f for f in edd_dir.glob(pattern or "*.csv") if f.is_file())
    if not files and pattern is None:
        files = sorted(f for f in edd_dir.glob("*.xlsx") if f.is_file())
    return [{"workbook_path": str(f), "profile_path": str(profile_path),
             "site_id": site_id}
            for f in files]


def run_batch_import(
    manifest_rows: list[dict],
    *,
    analyte_dictionary: Optional[dict] = None,
    screening_levels: Optional[dict] = None,
    event_date_override: Optional[date] = None,
    qa: Optional[QACollector] = None,
) -> BatchImportResult:
    """Process each manifest row through the EDD importer (headless CSV output).

    Args:
        manifest_rows: List of dicts with workbook_path, profile_path, site_id.
        analyte_dictionary: Optional analyte alias dict.
        screening_levels: Optional screening levels dict.
        event_date_override: Force all imports to this event date.
        qa: QA collector (created if not supplied).

    Returns:
        BatchImportResult with manifest, samples, and results.
    """
    from .edd_profile import LabEDDProfile
    from .edd_importer import read_edd_file, normalize_edd_rows

    if qa is None:
        qa = QACollector()

    result = BatchImportResult(qa=qa)

    for row in manifest_rows:
        wb_path = Path(row["workbook_path"])
        prof_path = Path(row["profile_path"])
        site_id = row["site_id"]
        batch_id = str(uuid.uuid4())[:8].upper()

        if not wb_path.exists():
            result.manifest.append(BatchManifestRow(
                WorkbookPath=str(wb_path), ProfilePath=str(prof_path),
                SiteID=site_id, BatchID=batch_id, Status="SKIP",
                SampleCount=0, ResultCount=0,
                ErrorSummary=f"File not found: {wb_path}",
                ProcessedAt=datetime.now(UTC).isoformat(),
            ))
            qa.add(SEV_WARNING, "workbook_not_found",
                   f"Skipping missing workbook: {wb_path}", site_id=site_id)
            continue

        if not prof_path.exists():
            result.manifest.append(BatchManifestRow(
                WorkbookPath=str(wb_path), ProfilePath=str(prof_path),
                SiteID=site_id, BatchID=batch_id, Status="SKIP",
                SampleCount=0, ResultCount=0,
                ErrorSummary=f"Profile not found: {prof_path}",
                ProcessedAt=datetime.now(UTC).isoformat(),
            ))
            qa.add(SEV_WARNING, "profile_not_found",
                   f"Skipping: profile missing: {prof_path}", site_id=site_id)
            continue

        try:
            profile = LabEDDProfile.load(prof_path)
            raw_rows = read_edd_file(wb_path, profile, qa)
            samples, results = normalize_edd_rows(
                raw_rows, profile, site_id, batch_id,
                analyte_dictionary or {}, screening_levels or {},
                qa, event_date_override,
            )
            result.all_samples.extend(samples)
            result.all_results.extend(results)
            result.manifest.append(BatchManifestRow(
                WorkbookPath=str(wb_path), ProfilePath=str(prof_path),
                SiteID=site_id, BatchID=batch_id, Status="OK",
                SampleCount=len(samples), ResultCount=len(results),
                ErrorSummary="",
                ProcessedAt=datetime.now(UTC).isoformat(),
            ))
            qa.add(SEV_INFO, "workbook_imported",
                   f"{wb_path.name}: {len(samples)} samples, "
                   f"{len(results)} results",
                   site_id=site_id)
        except Exception as exc:  # noqa: BLE001
            result.manifest.append(BatchManifestRow(
                WorkbookPath=str(wb_path), ProfilePath=str(prof_path),
                SiteID=site_id, BatchID=batch_id, Status="ERROR",
                SampleCount=0, ResultCount=0,
                ErrorSummary=str(exc)[:200],
                ProcessedAt=datetime.now(UTC).isoformat(),
            ))
            qa.add(SEV_ERROR, "workbook_import_error",
                   f"{wb_path.name}: {exc}", site_id=site_id)

    ok = sum(1 for m in result.manifest if m.Status == "OK")
    qa.add(SEV_INFO, "batch_complete",
           f"Batch import: {ok}/{len(result.manifest)} workbooks OK, "
           f"{len(result.all_samples)} samples, {len(result.all_results)} results")
    return result
