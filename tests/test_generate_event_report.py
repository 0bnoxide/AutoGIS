"""Tests for generate_event_report (Tool 10.5)."""
from datetime import date
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.generate_event_report import generate_event_report


def test_minimal_report():
    """Minimal call with no CSV inputs should produce a valid Markdown document."""
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2", qa=qa, generated_date=date(2026, 6, 28)
    )
    assert "# Monitoring Event Report" in md
    assert "H281" in md
    assert "2026Q2" in md


def test_generated_date_in_report():
    qa = QACollector()
    md = generate_event_report(
        "S", "E", qa=qa, generated_date=date(2026, 6, 28)
    )
    assert "2026-06-28" in md


def test_empty_inputs_no_crash():
    """All inputs absent must not crash."""
    qa = QACollector()
    md = generate_event_report("S", "E", qa=qa, generated_date=date(2026, 1, 1))
    assert md.startswith("# Monitoring Event Report")


def test_qa_info_emitted():
    qa = QACollector()
    generate_event_report("S", "E", qa=qa, generated_date=date(2026, 1, 1))
    assert any(r.category == "generate_event_report_complete" for r in qa.records)


def test_results_csv_counted(tmp_path):
    results_csv = tmp_path / "results.csv"
    results_csv.write_text(
        "ExceedsScreeningLevel\n1\n0\n1\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        results_csv=results_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "Total analytical results | 3" in md
    assert "Screening level exceedances | 2" in md


def test_executive_summary_present():
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2", qa=qa, generated_date=date(2026, 6, 28)
    )
    assert "## Executive Summary" in md


def test_comparison_csv_produces_trend_section(tmp_path):
    comp_csv = tmp_path / "comparison.csv"
    comp_csv.write_text(
        "TrendLabel\nINCREASE\nINCREASE\nDECREASE\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        comparison_csv=comp_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## Trend vs Previous Event" in md
    assert "INCREASE" in md
    assert "DECREASE" in md


def test_gaps_csv_produces_data_gaps_section(tmp_path):
    gaps_csv = tmp_path / "gaps.csv"
    gaps_csv.write_text(
        "LocationID,AnalyteName,Status,Detail\n"
        "MW-1,Benzene,MISSING,Not sampled\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        gaps_csv=gaps_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## Data Gaps" in md
    assert "MW-1" in md
    assert "MISSING" in md


def test_history_csv_top_10(tmp_path):
    history_csv = tmp_path / "history.csv"
    rows = "\n".join(
        f"MW-{i},Benzene,GW,5,5,0,1.0,10.0,5.5,2026-04-01,5.0,1,INCREASE,ug/L"
        for i in range(15)
    )
    history_csv.write_text(
        "LocationID,AnalyteCanonicalName,Matrix,NTotal,NDetects,NNonDetects,"
        "MinResult,MaxResult,MeanResult,LatestDate,LatestResult,LatestExceedance,"
        "TrendVsPrevious,Units\n" + rows,
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        history_csv=history_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## History Summary" in md


def test_rpd_section_shown(tmp_path):
    rpd_csv = tmp_path / "rpd.csv"
    rpd_csv.write_text(
        "severity,location_id,analyte,message\n"
        "ERROR,MW-1,Benzene,RPD 35% exceeds 20% limit\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        rpd_qa_csv=rpd_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## Duplicate RPD QA" in md
    assert "1 RPD QA record" in md


def test_nonexistent_csv_ignored(tmp_path):
    """Paths that don't exist should be silently skipped."""
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        results_csv=tmp_path / "nonexistent.csv",
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "# Monitoring Event Report" in md  # report still generated
