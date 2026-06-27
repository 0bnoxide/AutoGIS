"""Export Env_Samples + Env_AnalyticalResults to a four-sheet Excel summary.

Headless: reads in-memory record lists, writes with openpyxl.  No arcpy.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, fields as dc_fields
from pathlib import Path
from typing import List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from .gdb_schema import AnalyticalResultRecord, SampleRecord

_HEADER_FILL = PatternFill("solid", fgColor="4472C4")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _write_sheet(ws, rows: list, field_names: list) -> None:
    ws.append(field_names)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append([row.get(f) for f in field_names])
    for i, _ in enumerate(field_names, 1):
        ws.column_dimensions[get_column_letter(i)].width = 14


def export_analytical_summary(
    samples: List[SampleRecord],
    results: List[AnalyticalResultRecord],
    output_path: Path,
    site_id: str,
    event_id: str = "",
) -> Path:
    """Write a four-sheet Excel summary and return the written path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_fields = [f.name for f in dc_fields(AnalyticalResultRecord)]
    all_rows = [asdict(r) for r in results]
    det_rows = [r for r in all_rows if r.get("IsDetected")]
    exc_rows = [r for r in all_rows if r.get("ExceedsScreeningLevel")]

    counts: dict = defaultdict(lambda: defaultdict(int))
    for r in all_rows:
        a = r.get("AnalyteName", "")
        counts[a]["total"] += 1
        if r.get("IsDetected"):
            counts[a]["detected"] += 1
        if r.get("ExceedsScreeningLevel"):
            counts[a]["exceeds"] += 1
        if r.get("IsNonDetect"):
            counts[a]["nondetect"] += 1
    summary_fields = ["AnalyteName", "TotalCount", "DetectionCount",
                      "NonDetectCount", "ExceedanceCount"]
    summary_rows = [
        {"AnalyteName": a,
         "TotalCount": v["total"],
         "DetectionCount": v["detected"],
         "NonDetectCount": v["nondetect"],
         "ExceedanceCount": v["exceeds"]}
        for a, v in sorted(counts.items())]

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    ws_all = wb.create_sheet("All Results")
    _write_sheet(ws_all, all_rows, result_fields)

    ws_det = wb.create_sheet("Detections")
    _write_sheet(ws_det, det_rows, result_fields)

    ws_exc = wb.create_sheet("Exceedances")
    _write_sheet(ws_exc, exc_rows, result_fields)

    ws_sum = wb.create_sheet("Summary by Analyte")
    _write_sheet(ws_sum, summary_rows, summary_fields)

    wb.save(output_path)
    return output_path
