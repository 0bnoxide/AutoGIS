"""Evaluate duplicate-sample RPD from in-memory EDD records.

Lab EDDs carry field duplicates as separate sample rows (IsDuplicate=1,
ParentSampleID set).  This module finds those pairs, computes RPD per analyte,
and produces RPDRecord objects alongside QA records for any issues.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .gdb_schema import AnalyticalResultRecord, RPDRecord, SampleRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
# read_records_csv now lives in core.common.records_csv; re-exported for back-compat.
from ..common.records_csv import read_records_csv  # noqa: F401

_FORMULA_ERRORS = {"#VALUE!", "#DIV/0!", "#N/A", "#REF!", "#NAME?", "#NUM!", "#NULL!"}


def _rpd(parent: float, dup: float) -> Optional[float]:
    mean = (parent + dup) / 2.0
    if mean == 0:
        return None
    return abs(parent - dup) / mean * 100.0


def evaluate_duplicate_rpd(
    samples: List[SampleRecord],
    results: List[AnalyticalResultRecord],
    site_id: str,
    batch_id: str,
    qa: QACollector,
) -> List[RPDRecord]:
    """Find duplicate-parent sample pairs, compute RPD, emit QA records.

    Returns one RPDRecord per duplicate-analyte pair.  Formula-error rows get
    a ``rpd_formula_error`` QA WARNING and produce an RPDRecord with
    RPDStatus='NC_ERROR'.
    """
    parent_map = {s.SampleID: s for s in samples if s.IsDuplicate == 0}
    dup_samples = [s for s in samples if s.IsDuplicate == 1 and s.ParentSampleID]

    result_idx: dict = {}
    for r in results:
        result_idx.setdefault(r.SampleID, {})[r.AnalyteName] = r

    records: List[RPDRecord] = []
    for dup in dup_samples:
        parent = parent_map.get(dup.ParentSampleID)
        if parent is None:
            qa.add(SEV_WARNING, "rpd_parent_not_found",
                   f"duplicate sample {dup.SampleID!r} references parent "
                   f"{dup.ParentSampleID!r} which is not in the sample list",
                   site_id=site_id, sample_id=dup.SampleID,
                   import_batch_id=batch_id, source_workbook=dup.SourceWorkbook)
            continue

        dup_results = result_idx.get(dup.SampleID, {})
        par_results = result_idx.get(parent.SampleID, {})
        analytes = set(dup_results) | set(par_results)

        for analyte in sorted(analytes):
            p_rec = par_results.get(analyte)
            d_rec = dup_results.get(analyte)
            p_raw = p_rec.ResultRawText if p_rec else ""
            d_raw = d_rec.ResultRawText if d_rec else ""

            p_err = p_raw.upper() in _FORMULA_ERRORS
            d_err = d_raw.upper() in _FORMULA_ERRORS
            if p_err or d_err:
                qa.add(SEV_WARNING, "rpd_formula_error",
                       f"formula error in {analyte!r} for pair "
                       f"{parent.SampleID!r}/{dup.SampleID!r}: "
                       f"parent={p_raw!r} dup={d_raw!r}",
                       site_id=site_id, analyte_name=analyte,
                       import_batch_id=batch_id,
                       source_workbook=dup.SourceWorkbook)
                status, rpd_val, calc_err = "NC_ERROR", None, f"formula error: {p_raw or d_raw}"
            elif (p_rec and p_rec.IsDetected and p_rec.ResultNumeric is not None
                  and d_rec and d_rec.IsDetected and d_rec.ResultNumeric is not None):
                rpd_val = _rpd(p_rec.ResultNumeric, d_rec.ResultNumeric)
                status, calc_err = "CALCULATED", ""
                if rpd_val is None:
                    status, calc_err = "NC_ZERO_MEAN", "both values are zero"
            elif ((p_rec and p_rec.IsNonDetect) or (d_rec and d_rec.IsNonDetect)):
                rpd_val, status, calc_err = None, "NC_NONDETECT", ""
            else:
                rpd_val, status, calc_err = None, "NC_STATUS", ""

            rl = (p_rec.ReportingLimit if p_rec else None) or \
                 (d_rec.ReportingLimit if d_rec else None)
            src = d_rec or p_rec
            records.append(RPDRecord(
                ImportBatchID=batch_id, SiteID=site_id,
                EventDate=parent.SampleDate,
                ParentLocationID=parent.LocationID,
                DuplicateLocationID=dup.LocationID,
                AnalyteName=analyte,
                ParentResultRaw=p_raw, DuplicateResultRaw=d_raw,
                ParentResultNumeric=p_rec.ResultNumeric if p_rec else None,
                DuplicateResultNumeric=d_rec.ResultNumeric if d_rec else None,
                RPDValue=rpd_val,
                RL=rl, FiveTimesRL=rl * 5 if rl else None,
                RPDStatus=status, CalculationError=calc_err,
                SourceWorkbook=src.SourceWorkbook if src else "",
                SourceSheet=src.SourceSheet if src else "",
                SourceRow=src.SourceRow if src else 0))

    if records:
        qa.add(SEV_INFO, "rpd_complete",
               f"RPD evaluated: {len(records)} analyte-pair(s) from "
               f"{len(dup_samples)} duplicate sample(s)")
    return records


