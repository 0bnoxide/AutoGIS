"""Workbook -> GDB import orchestration.

Requires arcpy at runtime (lazily imported) so the pure-Python parts of
this package stay testable outside ArcGIS Pro.

Modes
-----
validate_only        Parse + QA only; nothing written to the GDB.
append               Insert only records whose unique key is absent.
replace_batch        Delete rows from a prior ImportBatchID, then append.
replace_site_event   Delete rows for (SiteID, EventDate[, Matrix]), then append.

The source workbook is NEVER modified (openpyxl read-only loads).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from logging_utils import get_logger
from qa_checks import QACollector, SEV_ERROR, SEV_INFO
from envmon_config import ParserProfile, SiteConfig, load_analyte_dictionary, load_screening_levels
from excel_profile_reader import ProfileWorkbookReader
from gdb_schema import TABLE_SCHEMAS, UNIQUE_KEYS, create_or_update_gdb_schema
from normalize_groundwater import normalize_gw_table_2
from normalize_soil import normalize_soil_table
from normalize_metals import normalize_metals_table
from normalize_ibi import normalize_ibi_table
from normalize_rpd import normalize_rpd_table

LOG = get_logger(__name__)

VALID_MODES = ("validate_only", "append", "replace_batch", "replace_site_event")


def _arcpy():
    import arcpy
    return arcpy


def where_date(field: str, ymd: str) -> str:
    """File-GDB SQL clause matching any time on a calendar date."""
    return (f"{field} >= date '{ymd} 00:00:00' "
            f"AND {field} <= date '{ymd} 23:59:59'")


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _as_dict(record) -> dict:
    return record if isinstance(record, dict) else asdict(record)


def create_import_batch(gdb: Path, workbook: Path, site_config: SiteConfig,
                        profile: ParserProfile, mode: str,
                        operator: str = "") -> str:
    """Insert an Env_ImportBatch row; returns the new ImportBatchID."""
    arcpy = _arcpy()
    batch_id = uuid.uuid4().hex[:16].upper()
    fields = ["ImportBatchID", "SiteID", "SiteName", "SourceWorkbook",
              "SourceWorkbookHash", "ImportDateTime", "ImportedBy",
              "ParserProfile", "ImportMode", "QAStatus", "SourceSheets"]
    sheets = ";".join(profile.sheets)[:512]
    row = [batch_id, site_config.site_id, site_config.site_name,
           str(workbook)[:255], file_sha256(workbook),
           _dt.datetime.now(), operator[:64] or "envmon",
           profile.profile_id, mode, "IN_PROGRESS", sheets]
    with arcpy.da.InsertCursor(str(gdb / "Env_ImportBatch"), fields) as cur:
        cur.insertRow(row)
    return batch_id


def finalize_batch(gdb: Path, batch_id: str, qa: QACollector,
                   counts: Dict[str, int], status: str) -> None:
    arcpy = _arcpy()
    sev = qa.counts()
    fields = ["ImportBatchID", "QAStatus", "AnalyticalRecordCount",
              "WaterLevelRecordCount", "RPDRecordCount", "WarningCount",
              "ErrorCount", "Notes"]
    with arcpy.da.UpdateCursor(str(gdb / "Env_ImportBatch"), fields) as cur:
        for r in cur:
            if r[0] == batch_id:
                r[1] = status
                r[2] = counts.get("analytical_results", 0)
                r[3] = counts.get("water_levels", 0)
                r[4] = counts.get("rpd_results", 0)
                r[5] = sev.get("WARNING", 0)
                r[6] = sev.get("ERROR", 0) + sev.get("CRITICAL", 0)
                r[7] = json.dumps(counts)[:512]
                cur.updateRow(r)


def _existing_key_set(table_path: str, key_fields: Sequence[str]) -> set:
    arcpy = _arcpy()
    keys = set()
    with arcpy.da.SearchCursor(table_path, list(key_fields)) as cur:
        for row in cur:
            keys.add(tuple(_norm_key_part(v) for v in row))
    return keys


def _norm_key_part(v):
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        return v.strip().upper()
    return v


def append_records_idempotent(
    gdb: Path,
    table_name: str,
    records: Sequence,
    qa: QACollector,
    batch_id: str,
    allow_duplicate_records: bool = False,
) -> Tuple[int, int]:
    """Insert records whose unique key is not already present.

    Returns (inserted, skipped). Skipped rows get an INFO QA record so
    nothing is silently dropped.
    """
    arcpy = _arcpy()
    if not records:
        return 0, 0
    field_names = [f[0] for f in TABLE_SCHEMAS[table_name]]
    table_path = str(gdb / table_name)
    key_fields = UNIQUE_KEYS[table_name]

    existing = (set() if allow_duplicate_records
                else _existing_key_set(table_path, key_fields))

    inserted = skipped = 0
    with arcpy.da.InsertCursor(table_path, field_names) as cur:
        for rec in records:
            d = _as_dict(rec)
            d.setdefault("ImportBatchID", batch_id)
            key = tuple(_norm_key_part(d.get(k)) for k in key_fields)
            if not allow_duplicate_records and key in existing:
                skipped += 1
                qa.add(SEV_INFO, "duplicate_key_skipped",
                       f"{table_name} key {key} already present; row skipped "
                       "(idempotent append).",
                       recommended_action="Use replace_batch / "
                                           "replace_site_event to re-import.",
                       import_batch_id=batch_id)
                continue
            cur.insertRow([d.get(f) for f in field_names])
            existing.add(key)
            inserted += 1
    return inserted, skipped


def delete_rows(gdb: Path, table_name: str, where: str) -> int:
    arcpy = _arcpy()
    n = 0
    with arcpy.da.UpdateCursor(str(gdb / table_name), ["OID@"],
                               where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()
            n += 1
    return n


def _delete_for_replace(gdb: Path, mode: str, site_id: str,
                        batch_id_to_replace: Optional[str],
                        event_date: Optional[str],
                        matrix: Optional[str],
                        qa: QACollector) -> None:
    if mode == "replace_batch":
        if not batch_id_to_replace:
            raise ValueError("replace_batch requires batch_id_to_replace")
        where = f"ImportBatchID = '{batch_id_to_replace}'"
        for t in ("Env_WaterLevels", "Env_Samples", "Env_AnalyticalResults",
                  "Env_RPDResults"):
            n = delete_rows(gdb, t, where)
            LOG.info("replace_batch: deleted %s rows from %s", n, t)
    elif mode == "replace_site_event":
        if not event_date:
            raise ValueError("replace_site_event requires event_date "
                             "(YYYY-MM-DD)")
        for t, date_field in (("Env_WaterLevels", "EventDate"),
                              ("Env_Samples", "SampleDate"),
                              ("Env_AnalyticalResults", "SampleDate"),
                              ("Env_RPDResults", "EventDate")):
            where = (f"SiteID = '{site_id}' AND "
                     + where_date(date_field, event_date))
            if matrix and t in ("Env_Samples", "Env_AnalyticalResults"):
                where += f" AND Matrix = '{matrix}'"
            n = delete_rows(gdb, t, where)
            LOG.info("replace_site_event: deleted %s rows from %s", n, t)
    qa.add(SEV_INFO, "replace_mode_delete",
           f"Mode {mode}: prior rows removed before append.", site_id=site_id)


def write_qa_to_gdb(gdb: Path, qa: QACollector, batch_id: str) -> int:
    arcpy = _arcpy()
    fields = [f[0] for f in TABLE_SCHEMAS["Env_ImportQA"]]
    n = 0
    with arcpy.da.InsertCursor(str(gdb / "Env_ImportQA"), fields) as cur:
        for rec in qa.records:
            d = rec.as_gdb_row()
            d["ImportBatchID"] = d.get("ImportBatchID") or batch_id
            cur.insertRow([d.get(f) for f in fields])
            n += 1
    return n


def run_import(
    workbook: Path,
    gdb: Path,
    site_config: SiteConfig,
    profile: ParserProfile,
    analyte_dictionary_path: Path,
    screening_levels_path: Path,
    qa_output_dir: Path,
    mode: str = "validate_only",
    matrix_filter: Optional[str] = None,
    batch_id_to_replace: Optional[str] = None,
    event_date: Optional[str] = None,
    operator: str = "",
    allow_duplicate_records: bool = False,
    allow_errors_override: bool = False,
) -> Dict:
    """Full import pipeline. Returns a summary dict (also written as JSON)."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")

    qa = QACollector()
    site_id = site_config.site_id
    adict = load_analyte_dictionary(analyte_dictionary_path)
    slevels = load_screening_levels(screening_levels_path)

    reader = ProfileWorkbookReader(workbook, profile, qa)

    batch_id = "VALIDATE_ONLY"
    if mode != "validate_only":
        create_or_update_gdb_schema(gdb, qa=qa)
        batch_id = create_import_batch(gdb, workbook, site_config, profile,
                                       mode, operator)

    water_levels: List = []
    samples: List = []
    results: List = []
    rpd: List = []

    run_gw = matrix_filter in (None, "GW")
    run_soil = matrix_filter in (None, "SOIL")

    if run_gw:
        wl, s, r = normalize_gw_table_2(workbook, profile, site_id, batch_id,
                                        adict, slevels, qa, reader=reader)
        water_levels.extend(wl); samples.extend(s); results.extend(r)
        s, r = normalize_metals_table(workbook, profile, site_id, batch_id,
                                      adict, slevels, qa, reader=reader)
        samples.extend(s); results.extend(r)
        s, r = normalize_ibi_table(workbook, profile, site_id, batch_id,
                                   adict, slevels, qa, reader=reader)
        samples.extend(s); results.extend(r)
        rpd.extend(normalize_rpd_table(workbook, profile, site_id, batch_id,
                                       qa, reader=reader))
    if run_soil:
        s, r = normalize_soil_table(workbook, profile, site_id, batch_id,
                                    adict, slevels, qa, reader=reader)
        samples.extend(s); results.extend(r)

    counts = {"water_levels": len(water_levels), "samples": len(samples),
              "analytical_results": len(results), "rpd_results": len(rpd)}
    summary = {
        "workbook": str(workbook),
        "mode": mode,
        "import_batch_id": batch_id,
        "counts_parsed": counts,
        "qa_counts": qa.counts(),
        "qa_status": qa.status(allow_errors=allow_errors_override),
    }

    blocking = qa.has_blocking(allow_errors=allow_errors_override)
    if mode == "validate_only" or blocking:
        if blocking and mode != "validate_only":
            finalize_batch(gdb, batch_id, qa, counts, "BLOCKED_BY_QA")
            LOG.error("Import blocked by QA (%s). Nothing written.",
                      summary["qa_counts"])
        summary["written"] = {"inserted": 0, "skipped": 0}
    else:
        if mode in ("replace_batch", "replace_site_event"):
            _delete_for_replace(gdb, mode, site_id, batch_id_to_replace,
                                event_date, matrix_filter, qa)
        ins = skp = 0
        for table_name, recs in (("Env_WaterLevels", water_levels),
                                 ("Env_Samples", samples),
                                 ("Env_AnalyticalResults", results),
                                 ("Env_RPDResults", rpd)):
            i, s = append_records_idempotent(
                gdb, table_name, recs, qa, batch_id, allow_duplicate_records)
            ins += i; skp += s
        summary["written"] = {"inserted": ins, "skipped": skp}
        finalize_batch(gdb, batch_id, qa, counts, "COMPLETE")

    qa_output_dir = Path(qa_output_dir)
    qa_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    qa.write_csv(qa_output_dir / f"import_qa_{stamp}.csv")
    qa.write_json_summary(qa_output_dir / f"import_qa_{stamp}.json",
                          extra=summary)
    qa.write_markdown(qa_output_dir / f"import_qa_{stamp}.md",
                      title=f"Import QA — {Path(workbook).name} ({mode})")
    if mode != "validate_only":
        write_qa_to_gdb(gdb, qa, batch_id)

    return summary
