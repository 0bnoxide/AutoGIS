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
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..common.logging import get_logger
from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from ..common.config import ParserProfile, SiteConfig, load_analyte_dictionary, load_screening_levels
from .excel_profile_reader import ProfileWorkbookReader
from .gdb_schema import T, TABLE_SCHEMAS, UNIQUE_KEYS, create_or_update_gdb_schema, compute_unique_key, _norm_key_part
from .normalize_groundwater import normalize_gw_table_2
from .normalize_soil import normalize_soil_table
from .normalize_metals import normalize_metals_table
from .normalize_ibi import normalize_ibi_table
from .normalize_rpd import normalize_rpd_table

LOG = get_logger(__name__)

VALID_MODES = ("validate_only", "append", "replace_batch", "replace_site_event")


from ...runtime.sessions import arcpy_env as _arcpy


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


def unmapped_record_fields(records: Sequence, table_name: str) -> List[str]:
    """Record keys with no column in ``TABLE_SCHEMAS[table_name]``, sorted.

    The insert path projects every record onto the target schema
    (``[d.get(f) for f in field_names]``), so a key the schema does not carry is
    discarded with no error, no exception and no QA record. That is how the
    Survey123 normalizer's ``COCNumber`` / ``SampledBy`` / ``SampleSource``
    reached ``Env_Samples`` and vanished (#420).

    Pure and arcpy-free, so the whole silent-projection class is testable off
    Pro rather than only observable as missing data in a delivered GDB.
    """
    known = {f[0] for f in TABLE_SCHEMAS[table_name]}
    seen: set = set()
    for rec in records:
        # Field NAMES only — never _as_dict() here. asdict() is a recursive
        # deep copy, and this pass runs in addition to the insert loop's own
        # conversion, so using it doubled the pure-Python cost of every large
        # import (measured 2.8s on 50k records) to learn something available
        # without copying anything.
        seen |= (rec.keys() if isinstance(rec, dict)
                 else {f.name for f in fields(rec)})
    return sorted(seen - known)


def append_records_idempotent(
    gdb: Path,
    table_name: str,
    records: Sequence,
    qa: QACollector,
    batch_id: str,
    allow_duplicate_records: bool = False,
) -> Tuple[int, int]:
    """Insert records whose unique key is not already present.

    Returns (inserted, skipped). Idempotent skips are visible in QA; losing a
    duplicate sample is blocking because it defeats the paired QC check.
    """
    arcpy = _arcpy()
    # Materialize before the two passes below. The unmapped-field scan added a
    # second traversal, so a generator argument would be exhausted by it and
    # the insert loop would quietly write nothing while reporting (0, 0) — the
    # zero-rows-as-clean-PASS shape this module's docstring exists to prevent.
    records = list(records)
    if not records:
        return 0, 0
    field_names = [f[0] for f in TABLE_SCHEMAS[table_name]]
    table_path = str(gdb / table_name)
    key_fields = UNIQUE_KEYS[table_name]

    # WARNING, not ERROR: the rows still land, and a producer that legitimately
    # carries scratch keys should not be blocked from importing. But it must not
    # be silent — every caller of this function shares the projection, so one
    # guard here covers all of them.
    dropped = unmapped_record_fields(records, table_name)
    if dropped:
        # Readability only — keep a 60-key dump from burying the count. The
        # TEXT(512) guarantee is NOT here (a count cap bounds names, not
        # characters); write_qa_to_gdb clamps every text column to its declared
        # width, which is the one place that can promise it for every category.
        shown = ", ".join(dropped[:10])
        if len(dropped) > 10:
            shown += f", … (+{len(dropped) - 10} more)"
        qa.add(SEV_WARNING, "record_fields_not_in_schema",
               f"{table_name}: {len(dropped)} field(s) on the incoming records "
               f"have no column in the target schema and are NOT stored: "
               f"{shown}.",
               recommended_action="Add the column(s) to "
                                  "gdb_schema.TABLE_SCHEMAS and run 'autogis "
                                  "envmon upgrade-schema', or stop emitting "
                                  "them upstream.",
               import_batch_id=batch_id)

    existing = (set() if allow_duplicate_records
                else _existing_key_set(table_path, key_fields))

    inserted = skipped = 0
    with arcpy.da.InsertCursor(table_path, field_names) as cur:
        for rec in records:
            d = _as_dict(rec)
            d.setdefault("ImportBatchID", batch_id)
            key = compute_unique_key(d, table_name)
            if not allow_duplicate_records and key in existing:
                skipped += 1
                duplicate_flag = str(
                    d.get("IsDuplicate") or "").strip().lower()
                is_qc_sample = (
                    table_name == "Env_Samples"
                    and (
                        duplicate_flag in {"1", "1.0", "true", "yes"}
                        or bool(str(d.get("DuplicateType") or "").strip())
                    )
                )
                qa.add(SEV_ERROR if is_qc_sample else SEV_INFO,
                       "duplicate_key_skipped",
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
            if matrix == "SOIL" and t in ("Env_WaterLevels", "Env_RPDResults"):
                # Neither table carries a Matrix column (issue #369), and
                # neither is ever populated by a SOIL-matrix run (run_import
                # only calls normalize_gw_table_2/normalize_rpd_table when
                # matrix_filter is None or "GW"). So a --matrix SOIL replace
                # must skip them -- deleting would wipe GW rows this run
                # never parsed and never intends to replace. A --matrix GW
                # replace, by contrast, DOES parse new rows for both tables
                # and must still delete-then-insert unscoped, or the new
                # rows are silently dropped as idempotent-append duplicates
                # of the stale ones left behind (a P1 caught in review).
                qa.add(SEV_INFO, "replace_skipped_unscopable_table",
                       f"{t} has no Matrix column; left untouched by this "
                       f"--matrix {matrix} replace_site_event.", site_id=site_id)
                continue
            where = (f"SiteID = '{site_id}' AND "
                     + where_date(date_field, event_date))
            if matrix and t in ("Env_Samples", "Env_AnalyticalResults"):
                where += f" AND Matrix = '{matrix}'"
            n = delete_rows(gdb, t, where)
            LOG.info("replace_site_event: deleted %s rows from %s", n, t)
    qa.add(SEV_INFO, "replace_mode_delete",
           f"Mode {mode}: prior rows removed before append.", site_id=site_id)


def create_edd_import_batch(
    gdb: Path,
    edd_path: Path,
    site_id: str,
    lab_name: str,
    profile_id: str,
    mode: str = "append",
    operator: str = "",
) -> str:
    """Insert an Env_ImportBatch row for an EDD import; returns ImportBatchID."""
    arcpy = _arcpy()
    batch_id = uuid.uuid4().hex[:16].upper()
    fields = ["ImportBatchID", "SiteID", "SiteName", "SourceWorkbook",
              "SourceWorkbookHash", "ImportDateTime", "ImportedBy",
              "ParserProfile", "ImportMode", "QAStatus", "SourceSheets"]
    try:
        wb_hash = file_sha256(edd_path)
    except Exception:
        wb_hash = ""
    row = [batch_id, site_id, "", str(edd_path)[:255], wb_hash,
           _dt.datetime.now(), operator[:64] or "edd_importer",
           profile_id, mode, "IN_PROGRESS", lab_name[:512]]
    with arcpy.da.InsertCursor(str(gdb / "Env_ImportBatch"), fields) as cur:
        cur.insertRow(row)
    return batch_id


def write_qa_to_gdb(gdb: Path, qa: QACollector, batch_id: str) -> int:
    arcpy = _arcpy()
    schema = TABLE_SCHEMAS["Env_ImportQA"]
    fields = [f[0] for f in schema]
    # Clamp every TEXT value to its declared width, taken from the schema
    # itself. A QA message is free text — a dropped-field list, a file path,
    # an exception string — and Message is only TEXT(512). An overlong value
    # makes the InsertCursor raise, which loses EVERY QA record for the batch:
    # the entire report discarded because one line was long. One clamp here
    # covers every category and every text column, which is why the producers
    # do not each need their own. The sibling writers above already clamp the
    # same way (`str(edd_path)[:255]`, `operator[:64]`).
    widths = {f[0]: f[2] for f in schema if f[1] is T and f[2]}
    n = 0
    with arcpy.da.InsertCursor(str(gdb / "Env_ImportQA"), fields) as cur:
        for rec in qa.records:
            d = rec.as_gdb_row()
            d["ImportBatchID"] = d.get("ImportBatchID") or batch_id
            cur.insertRow([_clamp(d.get(f), widths.get(f)) for f in fields])
            n += 1
    return n


def _clamp(value, width):
    """Truncate a string to `width`; anything else passes through untouched."""
    if width and isinstance(value, str) and len(value) > width:
        return value[:width]
    return value


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
        wl, s, r = normalize_gw_table_2(
            workbook, profile, site_id, batch_id, adict, slevels, qa,
            reader=reader,
            plausible_gwe_range_ft=site_config.get("plausible_gwe_range_ft"))
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
    if not any(counts.values()):
        # A matrix filter that matches no sheet is a legitimate zero-row run
        # (no shipped profile declares a SOIL data_type, yet the .pyt offers
        # SOIL in its dropdown), so name the filter rather than blaming the
        # profile for it. The guard itself stays unconditional: a filtered
        # run whose sheet names have drifted is still a real mismatch.
        filter_note = (f" (matrix filter: {matrix_filter})"
                       if matrix_filter else "")
        qa.add(SEV_WARNING if matrix_filter else SEV_ERROR,
               "zero_rows_parsed",
               "No sheet produced any rows -- check parser profile "
               "compatibility with this workbook (wrong sheet names, "
               f"unwired data_type, or a workbook/profile mismatch){filter_note}.",
               site_id=site_id, import_batch_id=batch_id,
               source_workbook=Path(workbook).name)
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
            if not any(counts.values()):
                # Deleting here would remove the existing rows and then
                # insert nothing, so a profile/workbook mismatch would
                # silently ERASE the prior event rather than replace it.
                # An explicit-filter zero_rows_parsed is deliberately
                # non-blocking, so this is the last guard before deletion.
                qa.add(SEV_WARNING, "replace_skipped_zero_rows",
                       f"{mode}: refusing to delete existing rows because "
                       "this run parsed none -- nothing would replace them. "
                       "Existing data is untouched.",
                       site_id=site_id, import_batch_id=batch_id,
                       source_workbook=Path(workbook).name)
            else:
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
        outcome = ("BLOCKED_BY_QA"
                   if qa.has_blocking(allow_errors=allow_errors_override)
                   else "COMPLETE")
        finalize_batch(gdb, batch_id, qa, counts, outcome)

    # Insertion can add QA records (for example, a duplicate QC sample that
    # was skipped), so the returned/toolbox status must reflect the final
    # collector rather than the pre-insert snapshot.
    summary["qa_counts"] = qa.counts()
    summary["qa_status"] = qa.status(allow_errors=allow_errors_override)
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
