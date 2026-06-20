"""RPD / field-duplicate comparison normalization.

RPD sheets are comparison blocks, not sample tables. The profile rpd_layout
maps the columns; RPD is recomputed and cross-checked against the workbook
value where one exists.
"""
from __future__ import annotations

from typing import List

from ..common.config import ParserProfile, col_index
from .excel_profile_reader import ProfileWorkbookReader
from .gdb_schema import RPDRecord
from ..common.qa import QACollector, SEV_WARNING
from .result_parser import parse_excel_date, parse_result_value

_RPD_TOLERANCE_PCT = 0.5


def _rpd(parent: float, dup: float) -> float | None:
    mean = (parent + dup) / 2.0
    if mean == 0:
        return None
    return abs(parent - dup) / mean * 100.0


def normalize_rpd_table(workbook_path, profile: ParserProfile, site_id: str,
                        batch_id: str, qa: QACollector,
                        reader: ProfileWorkbookReader | None = None
                        ) -> List[RPDRecord]:
    reader = reader or ProfileWorkbookReader(workbook_path, profile, qa)
    records: List[RPDRecord] = []
    for sheet in profile.sheets_of_type("RPD"):
        if not reader.require_sheet(sheet):
            continue
        lay = sheet.rpd_layout or {}
        a_col = col_index(lay.get("analyte_column", "A"))
        p_col = col_index(lay.get("parent_column", "B"))
        d_col = col_index(lay.get("duplicate_column", "C"))
        r_col = col_index(lay.get("rpd_column"))
        rl_col = col_index(lay.get("rl_column"))
        parent_loc = lay.get("parent_location_id", "")
        dup_loc = lay.get("duplicate_location_id", "")
        event_date = None
        if lay.get("event_date_cell"):
            ref = lay["event_date_cell"]
            import re as _re
            m = _re.match(r"([A-Z]+)(\d+)", ref.upper())
            if m:
                cell = reader.cell(sheet.sheet_name, int(m.group(2)),
                                   col_index(m.group(1)))
                event_date = parse_excel_date(cell.value, reader.date_system)
        wb = reader.path.name
        # iterate using the analyte column as the row driver
        sheet_iter = type(sheet)(**{**sheet.__dict__})
        sheet_iter.id_column = a_col
        for row in reader.iter_data_rows(sheet_iter):
            analyte = reader.cell(sheet.sheet_name, row, a_col).raw_text.strip()
            p_cell = reader.cell(sheet.sheet_name, row, p_col)
            d_cell = reader.cell(sheet.sheet_name, row, d_col)
            p = parse_result_value(p_cell.value)
            d = parse_result_value(d_cell.value)
            rl = None
            if rl_col:
                rlp = parse_result_value(
                    reader.cell(sheet.sheet_name, row, rl_col).value)
                rl = rlp.result_numeric if rlp.is_numeric else rlp.reporting_limit
            rl = rl or p.reporting_limit or d.reporting_limit
            status, calc_err, rpd_val = "", "", None
            if p.is_numeric and d.is_numeric:
                rpd_val = _rpd(p.result_numeric, d.result_numeric)
                status = "CALCULATED"
                if r_col:
                    sheet_rpd = parse_result_value(
                        reader.cell(sheet.sheet_name, row, r_col).value)
                    if (sheet_rpd.is_numeric and rpd_val is not None and
                            abs(sheet_rpd.result_numeric - rpd_val)
                            > _RPD_TOLERANCE_PCT):
                        calc_err = (f"workbook RPD {sheet_rpd.result_numeric} "
                                    f"!= recomputed {rpd_val:.1f}")
                        qa.add(SEV_WARNING, "rpd_calculation_mismatch",
                               f"{analyte}: {calc_err}", site_id=site_id,
                               analyte_name=analyte,
                               import_batch_id=batch_id, source_workbook=wb,
                               source_sheet=sheet.sheet_name, source_row=row)
            elif p.is_nondetect or d.is_nondetect:
                status = "NC_NONDETECT"  # not calculable with a nondetect
            else:
                status = "NC_STATUS"
            records.append(RPDRecord(
                ImportBatchID=batch_id, SiteID=site_id, EventDate=event_date,
                ParentLocationID=parent_loc, DuplicateLocationID=dup_loc,
                AnalyteName=analyte, ParentResultRaw=p.raw_text,
                DuplicateResultRaw=d.raw_text,
                ParentResultNumeric=p.result_numeric,
                DuplicateResultNumeric=d.result_numeric,
                RPDValue=rpd_val, RL=rl,
                FiveTimesRL=rl * 5 if rl else None,
                RPDStatus=status, CalculationError=calc_err,
                SourceWorkbook=wb, SourceSheet=sheet.sheet_name,
                SourceRow=row))
    return records
