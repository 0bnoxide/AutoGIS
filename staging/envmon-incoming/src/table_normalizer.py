"""Shared normalization core for matrix-style analytical tables.

normalize_groundwater / normalize_soil / normalize_metals / normalize_ibi all
delegate here. Sheet-to-sheet differences are expressed entirely through the
SheetProfile — no site-specific logic in code (spec: General rules).
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from envmon_config import SheetProfile, screening_for
from excel_profile_reader import ProfileWorkbookReader
from gdb_schema import AnalyticalResultRecord, SampleRecord
from qa_checks import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from result_parser import (classify_display, evaluate_screening,
                           normalize_analyte_name, parse_excel_date,
                           parse_result_value)

_DEPTH_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*['\u2032]?\s*[-\u2013to]+\s*"
                       r"(\d+(?:\.\d+)?)\s*['\u2032]?\s*$", re.IGNORECASE)


def parse_depth_interval(text: str) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None
    m = _DEPTH_RE.match(str(text))
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def _qa_formula(reader: ProfileWorkbookReader, cell, qa: QACollector,
                site_id: str, location_id: str, batch_id: str) -> bool:
    """QA a formula cell with a missing cached value. Returns True if the
    cell is unusable."""
    if cell.cached_missing:
        qa.add(SEV_ERROR, "formula_cell_missing_cached_value",
               f"formula '{cell.formula_text}' has no cached value",
               site_id=site_id, location_id=location_id,
               import_batch_id=batch_id,
               source_workbook=reader.path.name, source_sheet=cell.sheet,
               source_row=cell.row, source_cell=cell.ref,
               recommended_action="open and save the workbook in Excel to "
                                  "recalculate, then re-import")
        return True
    return False


def detect_duplicate_sample(location_id: str, profile_markers: List[str]) -> bool:
    lid = (location_id or "").upper()
    markers = [m.upper() for m in (profile_markers or ["DUP", "-D", " FD", "FD-"])]
    return any(m in lid for m in markers)


def normalize_matrix_table(
        reader: ProfileWorkbookReader, sheet: SheetProfile, *,
        matrix: str, analytical_group: str, site_id: str, batch_id: str,
        analyte_dictionary: dict, screening_levels: dict,
        qa: QACollector) -> Tuple[List[SampleRecord], List[AnalyticalResultRecord]]:
    """Normalize one sheet whose rows are samples and whose analyte columns
    are defined by the profile. Returns (samples, results)."""
    samples: List[SampleRecord] = []
    results: List[AnalyticalResultRecord] = []
    if not reader.require_sheet(sheet):
        return samples, results
    wb_name = reader.path.name

    # Resolve column headers once
    col_meta = {}
    for col in sheet.analyte_columns:
        if col in (sheet.ignored_columns or []):
            continue
        raw_name = reader.header_text(sheet, sheet.analyte_header_row, col)
        canonical = normalize_analyte_name(raw_name, analyte_dictionary)
        units = reader.header_text(sheet, sheet.units_row, col) if sheet.units_row else ""
        sl_cell = (reader.cell(sheet.sheet_name, sheet.screening_level_row, col)
                   if sheet.screening_level_row else None)
        sl_parsed = (parse_result_value(sl_cell.value, screening_context=True)
                     if sl_cell is not None else None)
        sl_value = sl_parsed.result_numeric if sl_parsed and sl_parsed.is_numeric else None
        sl_source = "workbook_row" if sl_value is not None else ""
        if canonical is None:
            qa.add(SEV_WARNING, "unknown_analyte",
                   f"column header '{raw_name}' not found in analyte dictionary",
                   site_id=site_id, analyte_name=raw_name,
                   import_batch_id=batch_id, source_workbook=wb_name,
                   source_sheet=sheet.sheet_name,
                   source_row=sheet.analyte_header_row,
                   recommended_action="add an alias to the analyte dictionary")
        entry = analyte_dictionary.get(canonical, {}) if canonical else {}
        if sl_value is None and canonical:
            cfg = screening_for(screening_levels, matrix, canonical)
            if cfg and cfg.get("value") is not None:
                sl_value = float(cfg["value"])
                sl_source = cfg.get("source", "config")
        if sl_parsed and sl_parsed.parse_warning and sl_cell is not None:
            qa.add(SEV_INFO, "screening_level_note", sl_parsed.parse_warning,
                   site_id=site_id, analyte_name=raw_name,
                   import_batch_id=batch_id, source_workbook=wb_name,
                   source_sheet=sheet.sheet_name, source_cell=sl_cell.ref)
        col_meta[col] = dict(raw_name=raw_name, canonical=canonical,
                             entry=entry, units=units, sl_value=sl_value,
                             sl_source=sl_source)

    dup_markers = sheet.raw.get("duplicate_markers")
    seen_keys = set()
    for row in reader.iter_data_rows(sheet):
        id_cell = reader.cell(sheet.sheet_name, row, sheet.id_column)
        location_id = id_cell.raw_text.strip()
        if not location_id:
            continue
        sample_id = location_id
        if sheet.sample_id_column:
            sample_id = reader.cell(sheet.sheet_name, row,
                                    sheet.sample_id_column).raw_text.strip() or location_id
        depth_text, dt, db = "", None, None
        if sheet.depth_column:
            depth_text = reader.cell(sheet.sheet_name, row,
                                     sheet.depth_column).raw_text.strip()
            dt, db = parse_depth_interval(depth_text)
            if depth_text and dt is None:
                qa.add(SEV_WARNING, "result_value_unparsable",
                       f"depth interval '{depth_text}' could not be parsed",
                       site_id=site_id, location_id=location_id,
                       import_batch_id=batch_id, source_workbook=wb_name,
                       source_sheet=sheet.sheet_name, source_row=row)
        date_cell = (reader.cell(sheet.sheet_name, row, sheet.date_column)
                     if sheet.date_column else None)
        sample_date = (parse_excel_date(date_cell.value, reader.date_system)
                       if date_cell else None)
        date_raw = date_cell.raw_text if date_cell else ""
        if sheet.date_column and sample_date is None:
            sev = SEV_WARNING if not date_raw else SEV_ERROR
            qa.add(sev, "missing_sample_date" if not date_raw else "invalid_sample_date",
                   f"sample date '{date_raw}' missing or invalid",
                   site_id=site_id, location_id=location_id,
                   import_batch_id=batch_id, source_workbook=wb_name,
                   source_sheet=sheet.sheet_name, source_row=row,
                   source_cell=date_cell.ref if date_cell else "")
        is_dup = detect_duplicate_sample(sample_id, dup_markers)
        key = (matrix, sample_id, str(sample_date), depth_text)
        if key in seen_keys:
            qa.add(SEV_WARNING, "duplicate_sample_ids",
                   f"sample '{sample_id}' on {sample_date} appears more than once",
                   site_id=site_id, location_id=location_id,
                   sample_id=sample_id, import_batch_id=batch_id,
                   source_workbook=wb_name, source_sheet=sheet.sheet_name,
                   source_row=row)
        seen_keys.add(key)
        samples.append(SampleRecord(
            ImportBatchID=batch_id, SiteID=site_id, Matrix=matrix,
            LocationID=location_id, SampleID=sample_id,
            ParentSampleID="" if not is_dup else location_id.split("DUP")[0].strip("-_ "),
            SampleDate=sample_date, SampleDateRaw=date_raw,
            DepthTop_ft=dt, DepthBottom_ft=db, DepthIntervalText=depth_text,
            IsDuplicate=int(is_dup), DuplicateType="FIELD_DUP" if is_dup else "",
            LabSampleID="", SourceWorkbook=wb_name,
            SourceSheet=sheet.sheet_name, SourceRow=row))

        for col, meta in col_meta.items():
            cell = reader.cell(sheet.sheet_name, row, col)
            if _qa_formula(reader, cell, qa, site_id, location_id, batch_id):
                parsed = parse_result_value(None)
                parsed.status_code = "INVALID"
                parsed.parse_warning = "formula cached value missing"
            else:
                parsed = parse_result_value(cell.value)
            if parsed.parse_warning:
                qa.add(SEV_WARNING, "result_value_unparsable"
                       if parsed.status_code in ("UNPARSED", "INVALID")
                       else "result_parse_note",
                       parsed.parse_warning, site_id=site_id,
                       location_id=location_id, sample_id=sample_id,
                       analyte_name=meta["raw_name"],
                       import_batch_id=batch_id, source_workbook=wb_name,
                       source_sheet=sheet.sheet_name, source_row=row,
                       source_column=cell.ref[:len(cell.ref) - len(str(row))],
                       source_cell=cell.ref)
            exceeds = evaluate_screening(parsed, meta["sl_value"])
            if parsed.is_detected and meta["sl_value"] is None and meta["canonical"]:
                qa.add(SEV_WARNING, "screening_level_missing",
                       f"no screening level for {meta['canonical']} ({matrix}); "
                       f"exceedance not evaluated", site_id=site_id,
                       location_id=location_id,
                       analyte_name=meta["canonical"],
                       import_batch_id=batch_id, source_workbook=wb_name,
                       source_sheet=sheet.sheet_name, source_cell=cell.ref)
            entry = meta["entry"]
            results.append(AnalyticalResultRecord(
                ImportBatchID=batch_id, SiteID=site_id, Matrix=matrix,
                LocationID=location_id, SampleID=sample_id,
                ParentSampleID="", SampleDate=sample_date,
                DepthTop_ft=dt, DepthBottom_ft=db,
                DepthIntervalText=depth_text,
                AnalyticalGroup=entry.get("analytical_group", analytical_group),
                MethodGroup=entry.get("method_group", ""),
                AnalyteName=meta["raw_name"],
                AnalyteCanonicalName=meta["canonical"] or meta["raw_name"],
                AnalyteAbbreviation=entry.get("abbreviation",
                                              meta["raw_name"][:12]),
                ResultRawText=parsed.raw_text,
                ResultNumeric=parsed.result_numeric,
                ReportingLimit=parsed.reporting_limit,
                DetectionLimit=parsed.detection_limit,
                Units=meta["units"] or entry.get("default_units_by_matrix",
                                                 {}).get(matrix, ""),
                Qualifier=parsed.qualifier,
                IsNonDetect=int(parsed.is_nondetect),
                IsDetected=int(parsed.is_detected),
                IsEstimated=int(parsed.is_estimated),
                IsDiluted=int(parsed.is_diluted),
                IsNotAnalyzed=int(parsed.is_not_analyzed or parsed.is_blank),
                IsNotSampled=int(parsed.is_not_sampled),
                IsNotMeasured=int(parsed.is_not_measured or parsed.is_dry),
                ScreeningLevel=meta["sl_value"],
                ScreeningLevelSource=meta["sl_source"],
                ExceedsScreeningLevel=None if exceeds is None else int(exceeds),
                DisplayText=parsed.display_text,
                DisplayColorClass=classify_display(parsed, exceeds),
                SourceWorkbook=wb_name, SourceSheet=sheet.sheet_name,
                SourceRow=row,
                SourceColumn=cell.ref[:len(cell.ref) - len(str(row))],
                SourceCell=cell.ref))
    return samples, results
