# autogis/core/envmon/edd_importer.py
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from autogis.core.common.config import screening_for
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord
from autogis.core.envmon.result_parser import (
    apply_qualifiers, classify_display, evaluate_screening,
    normalize_analyte_name, parse_excel_date, parse_result_value,
)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_edd_file(path: Path, profile: LabEDDProfile) -> list[dict]:
    """Read EDD file and return a flat list of row dicts.

    For two_tab_xlsx, sample-sheet metadata is merged onto each result row
    before returning, so the output is the same shape regardless of format.
    """
    path = Path(path)
    if profile.format == "flat_csv":
        return _read_flat_csv(path, profile)
    if profile.format == "two_tab_xlsx":
        return _read_two_tab_xlsx(path, profile)
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
        matrix = profile.matrix_map.get(matrix_raw, matrix_raw)
        if matrix_raw and matrix_raw not in profile.matrix_map:
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
        ))

    return samples, results
