"""evaluate_rpd.py — evaluate RPD records against a threshold, produce QA output."""
from __future__ import annotations

from dataclasses import dataclass

from .gdb_schema import RPDRecord
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO

DEFAULT_RPD_THRESHOLD_PCT = 30.0


@dataclass
class EvaluateRPDResult:
    records: list[RPDRecord]
    threshold_pct: float
    passed: int = 0
    failed: int = 0
    not_calculable: int = 0

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def exceedances(self) -> list[RPDRecord]:
        return [r for r in self.records
                if r.RPDStatus == "CALCULATED"
                and r.RPDValue is not None
                and r.RPDValue > self.threshold_pct]


def evaluate_rpd_records(
    records: list[RPDRecord],
    rpd_threshold_pct: float = DEFAULT_RPD_THRESHOLD_PCT,
) -> EvaluateRPDResult:
    result = EvaluateRPDResult(records=records, threshold_pct=rpd_threshold_pct)
    for rec in records:
        if rec.RPDStatus != "CALCULATED" or rec.RPDValue is None:
            result.not_calculable += 1
        elif rec.RPDValue > rpd_threshold_pct:
            result.failed += 1
        else:
            result.passed += 1
    return result


def rpd_to_qa(result: EvaluateRPDResult) -> QACollector:
    qa = QACollector()
    for rec in result.exceedances:
        qa.add(QARecord(
            severity=SEV_ERROR,
            category="rpd_exceedance",
            message=(f"{rec.AnalyteName} at {rec.ParentLocationID}/{rec.DuplicateLocationID}: "
                     f"RPD={rec.RPDValue:.1f}% exceeds {result.threshold_pct:.0f}% threshold"),
            analyte_name=rec.AnalyteName,
            location_id=rec.ParentLocationID,
            sample_id=rec.ParentResultRaw,
        ))
    qa.add(QARecord(
        severity=SEV_INFO,
        category="rpd_summary",
        message=(f"RPD evaluation: {result.passed} pass, {result.failed} fail, "
                 f"{result.not_calculable} not calculable (threshold={result.threshold_pct}%)"),
    ))
    return qa
