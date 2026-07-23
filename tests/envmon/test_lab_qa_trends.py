"""Tests for Phase 7 longitudinal lab-QA trends — arcpy-free.

The synthetic fixture verifies the deterministic rules/arithmetic are correctly
implemented. The roadmap gate's "reproduce a manually reviewed set of historical
events" leg needs real historical QC data + a reviewer and is recorded as a
Proposed gate item in ADR-0108 for user sign-off — not asserted here (authoring
both the rule and its expected output would be circular).
"""
from datetime import date
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector
from autogis.core.common.records_csv import read_records_csv, write_records_csv
from autogis.core.envmon.gdb_schema import QCResultRecord
from autogis.core.envmon.lab_qa_trends import (
    LabQAThresholds, LabQATrendRow, compute_blank_trends,
    compute_lab_qa_trends, compute_recovery_trends,
)


def _qc(qctype, analyte, *, rec=None, lo=None, hi=None, result=None, rl=None,
        nd=0, sid="S", d=None, method="8260", matrix="GW"):
    return QCResultRecord(
        ImportBatchID="B", SiteID="SITE", Matrix=matrix, SampleID=sid,
        QCType=qctype, AnalyteName=analyte, AnalyteCanonicalName=analyte,
        SourceWorkbook="w", SourceSheet="s", SourceRow=1, MethodID=method,
        AnalysisDate=d, ResultNumeric=result, ReportingLimit=rl,
        IsNonDetect=nd, PercentRecovery=rec,
        RecoveryLowerLimit=lo, RecoveryUpperLimit=hi)


# ── recovery ────────────────────────────────────────────────────────────────

def test_recovery_out_of_default_window_flagged():
    rows = [_qc("SURROGATE", "Toluene", rec=55.0, sid="R1", d=date(2026, 1, 1)),
            _qc("SURROGATE", "Toluene", rec=95.0, sid="R2", d=date(2026, 2, 1))]
    t = compute_recovery_trends(rows, LabQAThresholds())[0]
    assert t.n_total == 2 and t.n_flagged == 1
    assert t.worst_sample_id == "R1" and t.worst_value == 55.0
    assert t.flag_rate == 0.5
    assert t.date_first == "2026-01-01" and t.date_last == "2026-02-01"


def test_recovery_row_limits_override_default():
    # 60% is outside the default 70-130 but inside the lab window [50,150]
    rows = [_qc("LCS", "Benzene", rec=60.0, lo=50.0, hi=150.0, sid="R3")]
    assert compute_recovery_trends(rows, LabQAThresholds())[0].n_flagged == 0


def test_recovery_high_side_flagged():
    rows = [_qc("MS", "Xylene", rec=145.0, sid="R4")]  # > default upper 130
    t = compute_recovery_trends(rows, LabQAThresholds())[0]
    assert t.n_flagged == 1 and t.worst_value == 145.0


def test_rows_without_recovery_excluded():
    rows = [_qc("MB", "Benzene", result=1.0, rl=1.0)]  # no PercentRecovery
    assert compute_recovery_trends(rows, LabQAThresholds()) == []


def test_threshold_and_citation_present_in_output():
    rows = [_qc("SURROGATE", "Toluene", rec=55.0)]
    t = compute_recovery_trends(rows, LabQAThresholds())[0]
    assert "recovery within" in t.threshold_applied
    assert "SW-846" in t.citation  # cited standard represented in output


# ── blank ───────────────────────────────────────────────────────────────────

def test_blank_detection_flagged_at_or_above_rl():
    rows = [
        _qc("MB", "Benzene", result=2.0, rl=1.0, sid="B1"),       # detect
        _qc("MB", "Benzene", result=None, rl=1.0, nd=1, sid="B2"),  # clean ND
        _qc("Method Blank", "Benzene", result=0.4, rl=1.0, sid="B3"),  # < RL
    ]
    t = compute_blank_trends(rows, LabQAThresholds())[0]
    assert t.n_total == 3 and t.n_flagged == 1
    assert t.worst_sample_id == "B1" and t.worst_value == 2.0


def test_blank_rl_multiple_override():
    rows = [_qc("MB", "Benzene", result=0.6, rl=1.0, sid="B1")]
    # default multiple 1.0 → 0.6 < 1.0 clean; multiple 0.5 → 0.6 >= 0.5 flagged
    assert compute_blank_trends(rows, LabQAThresholds())[0].n_flagged == 0
    t2 = LabQAThresholds.from_dict({"blank_rl_multiple": 0.5})
    assert compute_blank_trends(rows, t2)[0].n_flagged == 1


def test_blank_substring_and_custom_qc_types():
    # "EQUIPMENT BLANK" via substring; custom code via override set
    rows = [_qc("Equipment Blank", "Lead", result=5.0, rl=1.0, sid="E1"),
            _qc("RINSATE", "Lead", result=5.0, rl=1.0, sid="E2")]
    default = compute_blank_trends(rows, LabQAThresholds())
    # only the equipment blank matches the default set
    assert sum(t.n_total for t in default) == 1
    custom = LabQAThresholds.from_dict({"blank_qc_types": ["RINSATE", "EQUIPMENT BLANK"]})
    assert sum(t.n_total for t in compute_blank_trends(rows, custom)) == 2


def test_blank_missing_rl_emits_qa_warning():
    qa = QACollector()
    rows = [_qc("MB", "Benzene", result=1.0, rl=None, sid="B1")]
    t = compute_blank_trends(rows, LabQAThresholds(), qa)[0]
    assert t.n_flagged == 1  # positive result counts as detected
    assert any(getattr(r, "category", "") == "blank_no_rl" for r in qa.records)


# ── grouping / combined ─────────────────────────────────────────────────────

def test_grouping_by_matrix_method_analyte():
    rows = [
        _qc("SURROGATE", "Toluene", rec=55.0, method="8260", matrix="GW"),
        _qc("SURROGATE", "Toluene", rec=55.0, method="8270", matrix="GW"),
        _qc("SURROGATE", "Toluene", rec=55.0, method="8260", matrix="SO"),
    ]
    trends = compute_recovery_trends(rows, LabQAThresholds())
    assert len(trends) == 3  # three distinct (matrix, method, analyte) groups


def test_combined_sorted_and_empty_input():
    assert compute_lab_qa_trends([]) == []
    rows = [_qc("SURROGATE", "T", rec=55.0), _qc("MB", "B", result=2.0, rl=1.0)]
    metrics = [t.metric for t in compute_lab_qa_trends(rows)]
    assert metrics == sorted(metrics)  # blank before recovery


# ── CLI round-trip (synthetic multi-event set) ──────────────────────────────

def _write_qc_csv(path, rows):
    write_records_csv(rows, path, record_class=QCResultRecord)


def test_command_in_help():
    res = CliRunner().invoke(autogis, ["envmon", "lab-qa-trends", "--help"])
    assert res.exit_code == 0
    assert "--qc-results" in res.output and "--out" in res.output


def test_cli_multi_event_trends(tmp_path):
    # Two "events" as two CSVs → longitudinal set
    e1 = tmp_path / "event1_qc.csv"
    e2 = tmp_path / "event2_qc.csv"
    _write_qc_csv(e1, [
        _qc("SURROGATE", "Toluene", rec=55.0, sid="R1", d=date(2026, 1, 1)),
        _qc("MB", "Benzene", result=2.0, rl=1.0, sid="B1", d=date(2026, 1, 1)),
    ])
    _write_qc_csv(e2, [
        _qc("SURROGATE", "Toluene", rec=120.0, sid="R2", d=date(2026, 4, 1)),
        _qc("MB", "Benzene", result=0.2, rl=1.0, sid="B2", d=date(2026, 4, 1)),
    ])
    out = tmp_path / "trends.csv"
    res = CliRunner().invoke(autogis, [
        "envmon", "lab-qa-trends",
        "--qc-results", str(e1), "--qc-results", str(e2),
        "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert out.exists()

    trends = read_records_csv(out, LabQATrendRow)
    rec = next(t for t in trends if t.metric == "recovery")
    # both surrogate events aggregate into one group, spanning the date range
    assert rec.n_total == 2 and rec.n_flagged == 1  # 55 out, 120 in
    assert rec.date_first == "2026-01-01" and rec.date_last == "2026-04-01"
    blank = next(t for t in trends if t.metric == "blank")
    assert blank.n_total == 2 and blank.n_flagged == 1  # 2.0 detect, 0.2 clean
    assert "flagged QC result(s)" in res.output


def test_cli_thresholds_override(tmp_path):
    qc = tmp_path / "qc.csv"
    _write_qc_csv(qc, [_qc("MB", "Benzene", result=0.6, rl=1.0, sid="B1")])
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text('{"blank_rl_multiple": 0.5}', encoding="utf-8")
    out = tmp_path / "trends.csv"
    res = CliRunner().invoke(autogis, [
        "envmon", "lab-qa-trends", "--qc-results", str(qc),
        "--thresholds", str(thresholds), "--out", str(out)])
    assert res.exit_code == 0, res.output
    blank = read_records_csv(out, LabQATrendRow)[0]
    assert blank.n_flagged == 1  # 0.6 >= 0.5*1.0 with override
