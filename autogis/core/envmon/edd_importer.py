# autogis/core/envmon/edd_importer.py
from __future__ import annotations

import csv
import dataclasses
from datetime import date
from pathlib import Path
from typing import Optional

from ..common.config import screening_for
from ..common.qa import QACollector, SEV_ERROR, SEV_WARNING
from .edd_profile import LabEDDProfile
from .gdb_schema import (
    SampleRecord, AnalyticalResultRecord, QCResultRecord, compute_unique_key,
)
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


def _qc_float(profile: LabEDDProfile, row: dict, field: str) -> Optional[float]:
    raw = profile.resolve_column(row, field)
    if not raw:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def normalize_qc_rows(
    rows: list[dict],
    profile: LabEDDProfile,
    site_id: str,
    batch_id: str,
    analyte_dictionary: dict,
    qa: QACollector,
) -> list[QCResultRecord]:
    """Convert reader-tagged lab-QC rows to QCResultRecord lists (spec D4/D5).

    One record per source row — MSD/LCSD are their own rows in EQuIS v1 and
    qc_dup_* merely echoes the row's own values (verified against the real
    WMRD export), so spike fields read the primary qc_* columns with a
    per-field qc_dup_* fallback. No second record is ever synthesized.
    """
    source_name = profile.profile_id
    records: list[QCResultRecord] = []
    for row_num, row in enumerate(rows, start=2):
        try:
            row_num = int(row.get("__source_row") or row_num)
        except (TypeError, ValueError):
            pass

        sample_id = profile.resolve_column(row, "sample_id")
        analyte_raw = profile.resolve_column(row, "analyte") or ""
        if not sample_id or not analyte_raw:
            qa.add(SEV_ERROR, "edd_qc_missing_required_field",
                   f"Row {row_num}: QC row missing "
                   f"{'sample_id' if not sample_id else 'analyte'} — skipped",
                   site_id=site_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            continue

        canonical = normalize_analyte_name(analyte_raw, analyte_dictionary)
        if canonical is None:
            qa.add(SEV_WARNING, "edd_unknown_analyte",
                   f"Row {row_num}: QC analyte '{analyte_raw}' not in the "
                   f"analyte dictionary; using raw name",
                   site_id=site_id, sample_id=sample_id,
                   import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            canonical = analyte_raw

        parsed = parse_result_value(profile.resolve_column(row, "result"))

        result_numeric = parsed.result_numeric
        sm = _qc_float(profile, row, "qc_spike_measured")
        spike_measured = sm if sm is not None \
            else _qc_float(profile, row, "qc_dup_spike_measured")
        if result_numeric is None and not parsed.is_nondetect \
                and spike_measured is not None:
            # spike rows report the measured spike in qc_spike_measured, not
            # result_value (documented convention, paper mapping)
            result_numeric = spike_measured

        def _fallback(primary: str, dup: str) -> Optional[float]:
            v = _qc_float(profile, row, primary)
            return v if v is not None else _qc_float(profile, row, dup)

        records.append(QCResultRecord(
            ImportBatchID=batch_id,
            SiteID=site_id,
            Matrix=profile.map_value(
                "matrix", profile.resolve_column(row, "matrix") or ""),
            SampleID=sample_id,
            QCType=profile.resolve_column(row, "qc_type") or "",
            AnalyteName=analyte_raw,
            AnalyteCanonicalName=canonical,
            SourceWorkbook=source_name,
            SourceSheet=profile.result_sheet,
            SourceRow=row_num,
            PrepBatchID=profile.resolve_column(row, "prep_batch_id") or "",
            AnalysisBatchID=profile.resolve_column(
                row, "analysis_batch_id") or "",
            ParentSampleID=profile.resolve_column(
                row, "parent_sample_id") or "",
            LabSampleID=profile.resolve_column(row, "lab_sample_id") or "",
            CASNumber=profile.resolve_column(row, "cas_number") or "",
            MethodID=profile.resolve_column(row, "method") or "",
            ResultFraction=profile.map_value(
                "result_fraction",
                profile.resolve_column(row, "result_fraction") or ""),
            MethodDilutionKey=(profile.resolve_column(
                row, "dilution_factor") or "").strip(),
            AnalysisDate=parse_excel_date(
                profile.resolve_column(row, "analysis_date") or ""),
            ResultRawText=parsed.raw_text,
            ResultNumeric=result_numeric,
            Units=profile.resolve_column(row, "units") or "",
            ReportingLimit=_qc_float(profile, row, "reporting_limit"),
            DetectionLimit=_qc_float(profile, row, "detection_limit"),
            Qualifier=parsed.qualifier or
                (profile.resolve_column(row, "qualifier") or ""),
            IsNonDetect=int(parsed.is_nondetect),
            SpikeAmount=_fallback("qc_spike_added", "qc_dup_spike_added"),
            OriginalConcentration=_fallback("qc_original_conc",
                                            "qc_dup_original_conc"),
            PercentRecovery=_fallback("qc_spike_recovery",
                                      "qc_dup_spike_recovery"),
            RecoveryLowerLimit=_qc_float(profile, row, "qc_spike_lcl"),
            RecoveryUpperLimit=_qc_float(profile, row, "qc_spike_ucl"),
            RPD=_qc_float(profile, row, "qc_rpd"),
            RPDControlLimit=_qc_float(profile, row, "qc_rpd_cl"),
        ))
    return records


# MethodDilutionKey is TEXT(64) in both Env_AnalyticalResults and
# Env_QCResults (gdb_schema). compute_unique_key compares the full in-memory
# string, but the GDB truncates at 64 on write — so a key over the limit
# dedups correctly this batch and then silently fails to match its truncated
# stored twin on reimport. ADR-0084's method fold grows the analytical value,
# so the ceiling is now reachable.
_METHOD_DILUTION_KEY_MAXLEN = 64


def detect_overlength_keys(
    records: list,
    table_name: str,
    qa: QACollector,
    batch_id: str,
) -> int:
    """Blocking guard: a MethodDilutionKey longer than its TEXT(64) schema slot
    (ADR-0084 post-merge review, P2). Rejecting before the append keeps a
    truncatable key from ever reaching the GDB and breaking idempotency. The
    upgrade path, if real method recipes approach the limit, is a bounded
    prefix+hash encoding rather than raising this ceiling. Returns the count of
    overlength records."""
    n = 0
    for rec in records:
        mdk = getattr(rec, "MethodDilutionKey", "") or ""
        if len(mdk) > _METHOD_DILUTION_KEY_MAXLEN:
            n += 1
            qa.add(SEV_ERROR, "edd_key_too_long",
                   f"{table_name}: MethodDilutionKey is {len(mdk)} chars, over "
                   f"the {_METHOD_DILUTION_KEY_MAXLEN}-char schema limit "
                   f"(source row {getattr(rec, 'SourceRow', '?')}): '{mdk}'. "
                   f"It would truncate on write and break dedup — batch marked "
                   f"ERROR.",
                   import_batch_id=batch_id,
                   recommended_action="Shorten the method/dilution recipe or "
                                      "add a bounded key encoding "
                                      "(prefix+hash).",
                   source_row=getattr(rec, "SourceRow", None))
    return n


def detect_within_file_key_collisions(
    records: list,
    table_name: str,
    qa: QACollector,
    batch_id: str,
) -> int:
    """Blocking guard: rows from ONE file that share an idempotent-dedup key.

    append_records_idempotent skips the later row of such a pair as a mere
    INFO record, so without this guard the batch stores fewer rows than it
    reports and still finalizes PASS — silent data loss. Known real-data
    trigger (issue #230): the frozen unique keys under-discriminate
    (Env_QCResults surrogate reruns lack a run-instance component; the
    analytical two-method case is resolved by the ADR-0084 method fold). A
    within-file collision cannot be safely auto-resolved without a source-
    provided run identity — collapsing value-equal rows can drop a genuinely
    distinct run (ADR-0084 post-merge review, P1b) — so it stays a blocking
    ERROR for human adjudication. Returns the surplus (would-be-dropped) row
    count.
    """
    by_key: dict[tuple, list] = {}
    for rec in records:
        key = compute_unique_key(dataclasses.asdict(rec), table_name)
        by_key.setdefault(key, []).append(rec)
    surplus = 0
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        surplus += len(group) - 1
        rows = ", ".join(str(getattr(r, "SourceRow", "?")) for r in group)
        qa.add(SEV_ERROR, "edd_key_collision",
               f"{table_name}: {len(group)} rows in this file share the "
               f"dedup key {key} (source rows {rows}); all but the first "
               f"would be silently dropped by the idempotent append. "
               f"Distinct results are colliding under the current unique "
               f"key (issue #230) — batch marked ERROR.",
               import_batch_id=batch_id,
               recommended_action="Inspect the colliding source rows; see "
                                  "issue #230 for the key redesign.",
               source_row=getattr(group[0], "SourceRow", None))
    return surplus


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

    # Step-3 QC fork: readers with a QC concept (equis_xls) tag lab-QC rows;
    # untagged formats pass through unchanged.
    qc_rows = [r for r in rows if r.get("__equis_stream") == "qc"]
    data_rows = [r for r in rows if r.get("__equis_stream") != "qc"]

    samples, results = normalize_edd_rows(
        rows=data_rows,
        profile=profile,
        site_id=site_id,
        batch_id=batch_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        qa=qa,
        event_date_override=event_date_override,
    )

    qc_records = []
    if qc_rows:
        qc_records = normalize_qc_rows(
            qc_rows, profile, site_id, batch_id, analyte_dictionary, qa)

    # Batch-integrity guards for issue #230 (PR #229 review + PR #236 review):
    # a within-file key collision or an overlength key cannot be written
    # faithfully — the idempotent writer would drop a colliding row, and an
    # over-64-char key truncates at InsertCursor. These are batch-level
    # failures, so they must gate the write itself, not merely flag QA: the
    # writer never inspects `qa`, so without an explicit abort a truncated key
    # or a partial-collision write still reaches the GDB (the exact corruption
    # the guards claim to prevent). Per-row errors (missing required field)
    # are NOT gated here — those rows were already dropped in normalize, and
    # the remaining good rows still import (batch flagged ERROR).
    bad = (detect_within_file_key_collisions(
               results, "Env_AnalyticalResults", qa, batch_id)
           + detect_overlength_keys(
               results, "Env_AnalyticalResults", qa, batch_id))
    if qc_records:
        bad += detect_within_file_key_collisions(
            qc_records, "Env_QCResults", qa, batch_id)
        bad += detect_overlength_keys(
            qc_records, "Env_QCResults", qa, batch_id)

    # Reader-flagged structural collisions (epar4 duplicate test keys, PR #253)
    # are batch-integrity failures too — the reader emits the blocking QA but
    # can't gate the write, so fold them into the same abort.
    bad += sum(1 for r in qa.records
               if r.category == "equis_test_key_collision")

    if bad:
        # Abort before any append: reject the whole batch for adjudication so
        # nothing partial or truncated ever lands. No row is written.
        finalize_batch(
            gdb_path, batch_id, qa,
            {"analytical_results": 0, "analytical_skipped": 0,
             "samples": 0, "samples_skipped": 0,
             "qc_results": 0, "qc_skipped": 0},
            "ERROR")
        write_qa_to_gdb(gdb_path, qa, batch_id)
        return batch_id

    ins_s, skip_s = append_records_idempotent(
        gdb_path, "Env_Samples", samples, qa, batch_id)
    ins_a, skip_a = append_records_idempotent(
        gdb_path, "Env_AnalyticalResults", results, qa, batch_id)
    ins_q = skip_q = 0
    if qc_records:
        ins_q, skip_q = append_records_idempotent(
            gdb_path, "Env_QCResults", qc_records, qa, batch_id)

    # Counts reflect what actually landed (inserted/skipped), not the
    # pre-dedup record-list lengths (PR #229 review).
    finalize_batch(
        gdb_path,
        batch_id,
        qa,
        {"analytical_results": ins_a, "analytical_skipped": skip_a,
         "samples": ins_s, "samples_skipped": skip_s,
         "qc_results": ins_q, "qc_skipped": skip_q},
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
