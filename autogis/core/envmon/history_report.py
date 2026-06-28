"""Summarise per-location per-analyte history across events (Tool 10.1)."""
from __future__ import annotations
import dataclasses
import statistics
from datetime import date
from typing import List, Optional
from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO

_STABLE_PCT = 10.0


@dataclasses.dataclass
class HistorySummaryRow:
    SiteID: str
    LocationID: str
    AnalyteCanonicalName: str
    Matrix: str
    NTotal: int
    NDetects: int
    NNonDetects: int
    MinResult: Optional[float]
    MaxResult: Optional[float]
    MeanResult: Optional[float]
    LatestDate: Optional[date]
    LatestResult: str
    LatestExceedance: Optional[int]
    TrendVsPrevious: str
    Units: str


def build_history_report(
    results: List[AnalyticalResultRecord],
    *,
    qa: QACollector,
) -> List[HistorySummaryRow]:
    """Summarise monitoring history by location / analyte / matrix."""
    from collections import defaultdict

    groups: dict[tuple, list[AnalyticalResultRecord]] = defaultdict(list)
    for r in results:
        if r.IsNotAnalyzed:
            continue
        key = (r.SiteID, r.LocationID, r.AnalyteCanonicalName, r.Matrix)
        groups[key].append(r)

    rows: List[HistorySummaryRow] = []
    for (site, loc, analyte, matrix), recs in sorted(groups.items()):
        recs_sorted = sorted(recs, key=lambda r: r.SampleDate or date.min)
        n_total = len(recs_sorted)
        detected = [r for r in recs_sorted
                    if not r.IsNonDetect and r.ResultNumeric is not None]
        non_detects = [r for r in recs_sorted if r.IsNonDetect]
        n_det = len(detected)
        n_nd = len(non_detects)

        nums = [r.ResultNumeric for r in detected]
        min_r = min(nums) if nums else None
        max_r = max(nums) if nums else None
        mean_r = statistics.mean(nums) if nums else None

        latest = recs_sorted[-1]
        units = latest.Units or ""

        dates = sorted({r.SampleDate for r in recs_sorted if r.SampleDate})
        trend = "INSUFFICIENT_DATA"
        if len(dates) >= 2:
            cur_date, prev_date = dates[-1], dates[-2]
            cur_recs = [r for r in recs_sorted if r.SampleDate == cur_date]
            prv_recs = [r for r in recs_sorted if r.SampleDate == prev_date]
            cur_det = [r.ResultNumeric for r in cur_recs
                       if not r.IsNonDetect and r.ResultNumeric is not None]
            prv_det = [r.ResultNumeric for r in prv_recs
                       if not r.IsNonDetect and r.ResultNumeric is not None]
            if not cur_det and not prv_det:
                trend = "ND_BOTH"
            elif cur_det and prv_det:
                cur_mean = statistics.mean(cur_det)
                prv_mean = statistics.mean(prv_det)
                if prv_mean == 0:
                    trend = "INCREASE" if cur_mean > 0 else "STABLE"
                else:
                    pct = (cur_mean - prv_mean) / abs(prv_mean) * 100
                    trend = ("STABLE" if abs(pct) <= _STABLE_PCT
                             else ("INCREASE" if pct > 0 else "DECREASE"))
            else:
                trend = "INSUFFICIENT_DATA"

        rows.append(HistorySummaryRow(
            SiteID=site, LocationID=loc, AnalyteCanonicalName=analyte,
            Matrix=matrix, NTotal=n_total, NDetects=n_det, NNonDetects=n_nd,
            MinResult=min_r, MaxResult=max_r, MeanResult=mean_r,
            LatestDate=latest.SampleDate, LatestResult=latest.DisplayText or "",
            LatestExceedance=latest.ExceedsScreeningLevel,
            TrendVsPrevious=trend, Units=units))

    total_recs = sum(len(v) for v in groups.values())
    qa.add(SEV_INFO, "history_report_complete",
           f"build_history_report: {len(rows)} summary row(s) from "
           f"{total_recs} records")
    return rows
