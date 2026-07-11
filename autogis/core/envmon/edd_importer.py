# autogis/core/envmon/edd_importer.py
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from ..common.config import screening_for
from ..common.qa import QACollector, SEV_ERROR, SEV_WARNING
from .edd_profile import LabEDDProfile
from .gdb_schema import SampleRecord, AnalyticalResultRecord
from .result_parser import (
    apply_qualifiers, classify_display, evaluate_screening,
    normalize_analyte_name, parse_excel_date, parse_result_value,
)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_edd_file(path: Path, profile: LabEDDProfile,
                  qa: Optional[QACollector] = None) -> list[dict]:
    """Read EDD file and return a flat list of row dicts.

    For two_tab_xlsx, sample-sheet metadata is merged onto each result row
    before returning, so the output is the same shape regardless of format.
    ``qa`` is optional (back-compat); readers with load-time transforms
    (wqx_csv, equis_xls) emit warnings through it.
    """
    path = Path(path)
    if profile.format == "flat_csv":
        return _read_flat_csv(path, profile)
    if profile.format == "two_tab_xlsx":
        return _read_two_tab_xlsx(path, profile)
    if profile.format == "wqx_csv":
        from .wqx_reader import read_wqx_csv
        return read_wqx_csv(path, profile, qa)
    if profile.format == "equis_xls":
        from .equis_reader import read_equis_xls
        return read_equis_xls(path, profile, qa)
    raise ValueError(f"Unknown EDD format '{profile.format}'")


def _read_flat_csv(path: Path, profile: LabEDDProfile) -> list[dict]:
    with path.open(newline="", encoding=profile.encoding) as fh:
        return list(csv.DictReader(fh))


def _read_two_tab_xlsx(path: Path, profile: LabEDDProfile) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def _sheet_to_dicts(ws) -> list[dict]:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h is not None else "" for h in rows[0]]
        return [dict(zip(headers, row)) for row in rows[1:]]

    sample_rows = _sheet_to_dicts(wb[profile.sample_sheet])
    result_rows = _sheet_to_dicts(wb[profile.result_sheet])

    # Build sample metadata index keyed by lab sample id
    sample_col = (profile.columns.get("sample_id") or "")
    if isinstance(sample_col, list):
        sample_col = sample_col[0]
    sample_index = {str(r.get(sample_col, "")): r for r in sample_rows}

    merged = []
    for result in result_rows:
        key = str(result.get(sample_col, ""))
        base = dict(sample_index.get(key, {}))
        base.update(result)   # result columns win on collision
        merged.append(base)
    return merged


# ---------------------------------------------------------------------------
# Normalizer (arcpy-free)
# ---------------------------------------------------------------------------

def normalize_edd_rows(
    rows: list[dict],
    profile: LabEDDProfile,
    site_id: str,
    batch_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    qa: QACollector,
    event_date_override: Optional[date] = None,
) -> tuple[list[SampleRecord], list[AnalyticalResultRecord]]:
    """Convert flat EDD row dicts to SampleRecord + AnalyticalResultRecord lists.

    Rows with missing required fields are skipped with SEV_ERROR QA records.
    All other errors are warnings — the row is still processed.
    """
    source_name = profile.profile_id

    samples: list[SampleRecord] = []
    results: list[AnalyticalResultRecord] = []
    seen_sample_keys: set[tuple] = set()

    for row_num, row in enumerate(rows, start=2):  # 2 = data starts after header
        # Readers that filter rows at load (wqx_csv) stamp the true source row
        # so provenance doesn't drift after a skipped row.
        try:
            row_num = int(row.get("__source_row") or row_num)
        except (TypeError, ValueError):
            pass

        # --- extract required fields ---
        sample_id   = profile.resolve_column(row, "sample_id")
        location_id = profile.resolve_column(row, "location_id")
        date_raw    = profile.resolve_column(row, "event_date") or ""
        matrix_raw  = profile.resolve_column(row, "matrix") or ""
        analyte_raw = profile.resolve_column(row, "analyte") or ""
        result_raw  = profile.resolve_column(row, "result")
        units_raw   = profile.resolve_column(row, "units") or ""

        missing = [f for f, v in [("sample_id", sample_id),
                                   ("location_id", location_id),
                                   ("analyte", analyte_raw or None)]
                   if not v]
        if missing:
            qa.add(SEV_ERROR, "edd_missing_required_field",
                   f"Row {row_num}: missing required field(s): "
                   f"{', '.join(missing)} — row skipped",
                   site_id=site_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            continue

        # --- date ---
        if event_date_override is not None:
            sample_date = event_date_override
        else:
            sample_date = parse_excel_date(date_raw)
            if sample_date is None:
                qa.add(SEV_WARNING, "edd_bad_date",
                       f"Row {row_num}: cannot parse date '{date_raw}'; "
                       f"row will have no event date",
                       site_id=site_id, location_id=location_id,
                       sample_id=sample_id, import_batch_id=batch_id,
                       source_sheet=source_name, source_row=row_num)

        # --- matrix ---
        matrix = profile.map_value("matrix", matrix_raw)
        if matrix_raw and matrix_raw not in profile.value_maps.get("matrix", {}):
            qa.add(SEV_WARNING, "edd_unknown_matrix",
                   f"Row {row_num}: matrix '{matrix_raw}' not in profile "
                   f"matrix_map; using as-is",
                   site_id=site_id, location_id=location_id,
                   sample_id=sample_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)

        # --- result parsing ---
        parsed = parse_result_value(result_raw)

        # apply separate qualifier column (EDD-specific: separate from result)
        qualifier_raw = profile.resolve_column(row, "qualifier") or ""
        if qualifier_raw.strip():
            apply_qualifiers(parsed, qualifier_raw)

        # force nondetect for known ND qualifiers
        if any(q in (parsed.qualifier_list or [])
               for q in profile.nondetect_qualifiers):
            parsed.is_nondetect = True
            parsed.is_detected = False

        # --- analyte resolution ---
        canonical = normalize_analyte_name(analyte_raw, analyte_dictionary)
        if canonical is None:
            qa.add(SEV_WARNING, "edd_unknown_analyte",
                   f"Row {row_num}: analyte '{analyte_raw}' not found in "
                   f"analyte dictionary; using raw name",
                   site_id=site_id, location_id=location_id,
                   sample_id=sample_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            canonical = analyte_raw

        # --- optional fields ---
        rl_raw  = profile.resolve_column(row, "reporting_limit")
        method  = profile.resolve_column(row, "method") or ""
        lab_sid = profile.resolve_column(row, "lab_sample_id") or ""
        fraction   = profile.map_value(
            "result_fraction", profile.resolve_column(row, "result_fraction") or "")
        qc_type    = profile.map_value(
            "qc_type", profile.resolve_column(row, "qc_type") or "")
        # Step-1 composition: the mapped dilution_factor column verbatim.
        # Readers with richer run discriminators (Step 2/3) precompose a
        # value and map method_dilution_key-equivalent columns to it via the
        # profile — deterministic from source either way (ADR-0075).
        dilution   = (profile.resolve_column(row, "dilution_factor") or "").strip()
        method_name = profile.resolve_column(row, "method_name") or ""
        analysis_date = parse_excel_date(
            profile.resolve_column(row, "analysis_date") or "")
        limit_type = profile.resolve_column(row, "limit_type") or ""
        lab_name   = profile.resolve_column(row, "lab_name") or ""
        prep_method = profile.resolve_column(row, "prep_method") or ""
        prep_date  = parse_excel_date(
            profile.resolve_column(row, "prep_date") or "")
        result_basis = profile.resolve_column(row, "result_basis") or ""
        speciation = profile.resolve_column(row, "method_speciation") or ""
        try:
            dt = float(profile.resolve_column(row, "depth_top_ft") or "")
        except (ValueError, TypeError):
            dt = None
        try:
            db = float(profile.resolve_column(row, "depth_bot_ft") or "")
        except (ValueError, TypeError):
            db = None
        depth_text = f"{dt}'-{db}'" if dt is not None and db is not None else ""

        # reporting limit from profile column overrides any parsed from result
        if rl_raw:
            try:
                parsed.reporting_limit = float(rl_raw.replace(",", ""))
            except (ValueError, AttributeError):
                pass

        # detection limit column (format-agnostic; mirrors the RL override —
        # WQX routes MDL-typed limits here, Step-3 EQuIS formats carry
        # method_detection_limit natively)
        dl_raw = profile.resolve_column(row, "detection_limit")
        if dl_raw:
            try:
                parsed.detection_limit = float(dl_raw.replace(",", ""))
            except (ValueError, AttributeError):
                pass

        # Step-3 EQuIS additions — format-agnostic like detection_limit
        # (every EQuIS dialect carries cas_rn / quantitation_limit /
        # reportable_result natively; other formats simply don't map them).
        cas_number = profile.resolve_column(row, "cas_number") or ""
        quantitation_limit = None
        ql_raw = profile.resolve_column(row, "quantitation_limit")
        if ql_raw:
            try:
                quantitation_limit = float(ql_raw.replace(",", ""))
            except (ValueError, AttributeError):
                pass
        rep_raw = (profile.resolve_column(row, "is_reportable") or "").strip()
        is_reportable = int(rep_raw) if rep_raw in ("0", "1") else None

        # --- analyte dictionary entry ---
        entry = ({k: v for k, v in analyte_dictionary.items()
                  if not k.startswith("_")}.get(canonical) or {})

        # --- screening ---
        sl_entry = screening_for(screening_levels, matrix, canonical)
        sl_value = sl_entry["value"] if sl_entry and "value" in sl_entry else None
        sl_source = sl_entry.get("source", "") if sl_entry else ""
        exceeds = evaluate_screening(parsed, sl_value)
        display_class = classify_display(parsed, exceeds)

        # --- SampleRecord (deduplicated) ---
        sample_key = (site_id, location_id, sample_id,
                      str(sample_date), matrix)
        if sample_key not in seen_sample_keys:
            seen_sample_keys.add(sample_key)
            samples.append(SampleRecord(
                ImportBatchID=batch_id,
                SiteID=site_id,
                Matrix=matrix,
                LocationID=location_id,
                SampleID=sample_id,
                ParentSampleID="",
                SampleDate=sample_date,
                SampleDateRaw=date_raw,
                DepthTop_ft=dt,
                DepthBottom_ft=db,
                DepthIntervalText=depth_text,
                IsDuplicate=0,
                DuplicateType="",
                LabSampleID=lab_sid,
                SourceWorkbook=source_name,
                SourceSheet=profile.format,
                SourceRow=row_num,
            ))

        # --- AnalyticalResultRecord ---
        results.append(AnalyticalResultRecord(
            ImportBatchID=batch_id,
            SiteID=site_id,
            Matrix=matrix,
            LocationID=location_id,
            SampleID=sample_id,
            ParentSampleID="",
            SampleDate=sample_date,
            DepthTop_ft=dt,
            DepthBottom_ft=db,
            DepthIntervalText=depth_text,
            AnalyticalGroup=entry.get("analytical_group", ""),
            MethodGroup=entry.get("method_group", ""),
            AnalyteName=analyte_raw,
            AnalyteCanonicalName=canonical,
            AnalyteAbbreviation=entry.get("abbreviation", analyte_raw[:12]),
            ResultRawText=parsed.raw_text,
            ResultNumeric=parsed.result_numeric,
            ReportingLimit=parsed.reporting_limit,
            DetectionLimit=parsed.detection_limit,
            Units=units_raw or entry.get("default_units_by_matrix",
                                         {}).get(matrix, ""),
            Qualifier=parsed.qualifier,
            IsNonDetect=int(parsed.is_nondetect),
            IsDetected=int(parsed.is_detected),
            IsEstimated=int(parsed.is_estimated),
            IsDiluted=int(parsed.is_diluted),
            IsNotAnalyzed=int(parsed.is_not_analyzed or parsed.is_blank),
            IsNotSampled=int(parsed.is_not_sampled),
            IsNotMeasured=int(parsed.is_not_measured or parsed.is_dry),
            ScreeningLevel=sl_value,
            ScreeningLevelSource=sl_source,
            ExceedsScreeningLevel=None if exceeds is None else int(exceeds),
            DisplayText=parsed.display_text,
            DisplayColorClass=display_class,
            SourceWorkbook=source_name,
            SourceSheet=profile.format,
            SourceRow=row_num,
            SourceColumn="",
            SourceCell="",
            ResultFraction=fraction,
            QCType=qc_type,
            MethodDilutionKey=dilution,
            MethodID=method,
            MethodName=method_name,
            AnalysisDate=analysis_date,
            LimitType=limit_type,
            LabName=lab_name,
            PrepMethodID=prep_method,
            PrepDate=prep_date,
            ResultBasis=result_basis,
            MethodSpeciation=speciation,
            CASNumber=cas_number,
            QuantitationLimit=quantitation_limit,
            IsReportable=is_reportable,
        ))

    return samples, results


# ---------------------------------------------------------------------------
# Module-level stubs — monkeypatchable in tests; forward to import_to_gdb
# at call time so this module is importable without arcpy.
# ---------------------------------------------------------------------------

def create_edd_import_batch(gdb_path, edd_path, site_id, lab_name, profile_id, mode="append"):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import create_edd_import_batch as _f
    return _f(gdb_path, edd_path, site_id, lab_name, profile_id, mode)


def append_records_idempotent(gdb_path, table_name, records, qa, batch_id):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import append_records_idempotent as _f
    return _f(gdb_path, table_name, records, qa, batch_id)


def finalize_batch(gdb_path, batch_id, qa, counts, status):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import finalize_batch as _f
    return _f(gdb_path, batch_id, qa, counts, status)


def write_qa_to_gdb(gdb_path, qa, batch_id):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import write_qa_to_gdb as _f
    return _f(gdb_path, qa, batch_id)


def create_or_update_gdb_schema(gdb_path, qa=None):  # pragma: no cover
    from autogis.core.envmon.gdb_schema import create_or_update_gdb_schema as _f
    return _f(gdb_path, qa=qa)


# ---------------------------------------------------------------------------
# Orchestrator (calls import_to_gdb stubs above — arcpy required for GDB writes)
# ---------------------------------------------------------------------------

def run_edd_import(
    edd_path: Path,
    profile: LabEDDProfile,
    gdb_path: Path,
    site_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    event_date_override: Optional[date] = None,
    qa: Optional[QACollector] = None,
) -> str:
    """Run a full EDD import. Returns the import batch_id.

    Follows the same lifecycle as import_to_gdb.run_import():
      create_edd_import_batch -> normalize -> append -> finalize -> write_qa

    Pass ``qa`` to also receive the QA records caller-side (e.g. for a
    ``--report`` file); the same records are still written to the GDB.
    Reader-level warnings (wqx_csv load transforms) land in it too — the
    collector is initialized before the read (PR #225/#226 reconciliation).
    """
    edd_path = Path(edd_path)
    gdb_path = Path(gdb_path)

    # Self-heal the GDB schema (mirrors run_import in import_to_gdb.py): the
    # widened key columns must exist before _existing_key_set reads them.
    create_or_update_gdb_schema(gdb_path)

    batch_id = create_edd_import_batch(
        gdb_path, edd_path, site_id, profile.lab_name, profile.profile_id,
    )

    qa = qa if qa is not None else QACollector()
    rows = read_edd_file(edd_path, profile, qa)

    samples, results = normalize_edd_rows(
        rows=rows,
        profile=profile,
        site_id=site_id,
        batch_id=batch_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        qa=qa,
        event_date_override=event_date_override,
    )

    append_records_idempotent(gdb_path, "Env_Samples", samples, qa, batch_id)
    append_records_idempotent(gdb_path, "Env_AnalyticalResults", results, qa, batch_id)

    finalize_batch(
        gdb_path,
        batch_id,
        qa,
        {"analytical_results": len(results)},
        "ERROR" if qa.has_blocking() else "PASS",
    )

    write_qa_to_gdb(gdb_path, qa, batch_id)
    return batch_id


# ---------------------------------------------------------------------------
# Lightweight sample extraction (no GDB writes)
# ---------------------------------------------------------------------------

def extract_sample_roster(edd_path: Path, profile) -> list:
    """Return list[LabSample] from an EDD without importing to GDB.

    Accepts either LabEDDProfile or ParserProfile (duck-typed).
    """
    from .reconcile_survey123_lab import LabSample

    edd_path = Path(edd_path)
    rows = read_edd_file(edd_path, profile)

    seen: dict[str, LabSample] = {}
    for row in rows:
        sample_id = profile.resolve_column(row, "sample_id") or ""
        if not sample_id:
            continue
        if sample_id not in seen:
            location_id = profile.resolve_column(row, "location_id") or ""
            event_date = profile.resolve_column(row, "event_date") or ""
            matrix = profile.resolve_column(row, "matrix") or ""
            seen[sample_id] = LabSample(
                sample_id=sample_id,
                location_id=location_id,
                sample_date=str(event_date),
                matrix=matrix,
                analyte_count=0,
            )
        seen[sample_id].analyte_count += 1

    return list(seen.values())
