"""field_completeness_validator.py — sampling plan vs. lab results completeness check."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO


@dataclass
class CompletenessIssue:
    issue_type: str
    sample_id: str
    location_id: str
    analyte_group: str
    detail: str
    severity: str


@dataclass
class CompletenessResult:
    issues: list
    planned_count: int
    received_count: int
    matched_count: int
    not_sampled: list
    unexpected: list
    hold_time_violations: int
    qa: QACollector


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


def validate_field_completeness(
    plan_rows: list,
    result_rows: list,
    *,
    match_field: str = "SampleID",
    hold_time_field: str = "HoldTimeDays",
) -> CompletenessResult:
    qa = QACollector()
    issues: list = []

    plan_by_id = {r.get(match_field, ""): r for r in plan_rows}
    result_by_id: dict[str, list] = {}
    for r in result_rows:
        sid = r.get(match_field, "")
        result_by_id.setdefault(sid, []).append(r)

    plan_ids = set(plan_by_id.keys())
    result_ids = set(result_by_id.keys())

    matched = plan_ids & result_ids
    not_sampled = sorted(plan_ids - result_ids)
    unexpected = sorted(result_ids - plan_ids)
    hold_violations = 0

    for sid in not_sampled:
        pr = plan_by_id[sid]
        issues.append(CompletenessIssue(
            issue_type="not_sampled", sample_id=sid,
            location_id=pr.get("LocationID", ""),
            analyte_group=pr.get("AnalyteGroup", ""),
            detail=f"{sid} in plan but not in lab results.",
            severity="ERROR",
        ))
        qa.add(QARecord(SEV_ERROR, "not_sampled", f"{sid} not in lab results."))

    for sid in unexpected:
        issues.append(CompletenessIssue(
            issue_type="unexpected_result", sample_id=sid,
            location_id="", analyte_group="",
            detail=f"{sid} in lab results but not in plan.",
            severity="WARNING",
        ))
        qa.add(QARecord(SEV_WARNING, "unexpected_result",
                        f"{sid} in results but not in plan."))

    # Duplicate result check
    for sid, recs in result_by_id.items():
        if len(recs) > 1:
            issues.append(CompletenessIssue(
                issue_type="duplicate_sample_id", sample_id=sid,
                location_id="", analyte_group="",
                detail=f"{sid} appears {len(recs)} times in results.",
                severity="WARNING",
            ))
            qa.add(QARecord(SEV_WARNING, "duplicate_sample_id",
                            f"{sid} appears {len(recs)} times."))

    # Hold time check for matched samples
    for sid in matched:
        pr = plan_by_id[sid]
        hold_days_str = pr.get(hold_time_field, "")
        coll_date_str = pr.get("CollectionDate", "")
        for rr in result_by_id[sid]:
            analysis_date_str = rr.get("AnalysisDate", "")
            coll = _parse_date(coll_date_str)
            analysis = _parse_date(analysis_date_str)
            try:
                hold_days = int(float(hold_days_str))
            except (ValueError, TypeError):
                continue
            if coll and analysis:
                elapsed = (analysis - coll).days
                if elapsed > hold_days:
                    hold_violations += 1
                    issues.append(CompletenessIssue(
                        issue_type="hold_time_exceeded", sample_id=sid,
                        location_id=pr.get("LocationID", ""),
                        analyte_group=pr.get("AnalyteGroup", ""),
                        detail=(f"Elapsed {elapsed}d > hold time {hold_days}d "
                                f"(collected {coll_date_str}, analysed {analysis_date_str})."),
                        severity="WARNING",
                    ))
                    qa.add(QARecord(SEV_WARNING, "hold_time_exceeded",
                                    f"{sid}: {elapsed}d elapsed > {hold_days}d hold time."))

    qa.add(QARecord(SEV_INFO, "completeness_checked",
                    f"Planned: {len(plan_ids)}  Received: {len(result_ids)}  "
                    f"Matched: {len(matched)}  Not sampled: {len(not_sampled)}  "
                    f"Unexpected: {len(unexpected)}  Hold violations: {hold_violations}"))

    return CompletenessResult(
        issues=issues, planned_count=len(plan_ids),
        received_count=len(result_ids), matched_count=len(matched),
        not_sampled=not_sampled, unexpected=unexpected,
        hold_time_violations=hold_violations, qa=qa,
    )


def write_completeness_report(result: CompletenessResult, out_path: Path) -> None:
    fields = ["issue_type", "sample_id", "location_id",
              "analyte_group", "detail", "severity"]
    with Path(out_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for issue in result.issues:
            w.writerow({f: getattr(issue, f, "") for f in fields})
