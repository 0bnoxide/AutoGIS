"""Tests for Markdown well inspection report generation."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.well_inspection_report import (
    build_well_inspection_reports,
    generate_site_summary,
    generate_well_report,
)


def test_well_report_includes_metadata_and_history():
    content = generate_well_report(
        "MW-1",
        {"WellID": "MW-1", "Location": "North fence"},
        [{"InspectionDate": "2026-06-01", "Condition": "Good", "Notes": "OK"}],
    )
    assert "MW-1" in content
    assert "North fence" in content
    assert "2026-06-01" in content
    assert "Latest Inspection" in content


def test_well_report_no_history():
    content = generate_well_report("MW-2", {"WellID": "MW-2"}, [])
    assert "No inspection records on file" in content


def test_site_summary_flags_never_inspected():
    qa = QACollector()
    wells = [{"WellID": "MW-1"}, {"WellID": "MW-2"}]
    inspections_by_well = {
        "MW-1": [{"InspectionDate": "2026-06-01", "Condition": "Good"}],
    }
    content = generate_site_summary(
        wells, inspections_by_well, site_id="H281", qa=qa)
    assert "Never inspected:** 1" in content
    assert any(r.category == "wells_never_inspected" for r in qa.records)


def test_site_summary_flags_non_passing_condition():
    qa = QACollector()
    wells = [{"WellID": "MW-1"}]
    inspections_by_well = {
        "MW-1": [{"InspectionDate": "2026-06-01", "Condition": "Damaged"}],
    }
    generate_site_summary(wells, inspections_by_well, site_id="H281", qa=qa)
    assert any(r.category == "wells_need_attention" for r in qa.records)


def test_site_summary_all_passing_no_warnings():
    qa = QACollector()
    wells = [{"WellID": "MW-1"}]
    inspections_by_well = {
        "MW-1": [{"InspectionDate": "2026-06-01", "Condition": "Good"}],
    }
    generate_site_summary(wells, inspections_by_well, site_id="H281", qa=qa)
    assert not any(r.category in ("wells_never_inspected", "wells_need_attention")
                   for r in qa.records)


def test_build_well_inspection_reports_writes_one_file_per_well_plus_summary(tmp_path):
    wells_csv = tmp_path / "wells.csv"
    wells_csv.write_text("WellID,Location\nMW-1,North\nMW-2,South\n", encoding="utf-8")
    log_csv = tmp_path / "log.csv"
    log_csv.write_text(
        "WellID,InspectionDate,Condition,Notes\n"
        "MW-1,2026-01-01,Good,fine\n"
        "MW-1,2026-06-01,Good,still fine\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "reports"
    qa = QACollector()
    written = build_well_inspection_reports(
        wells_csv, out_dir, site_id="H281", maintenance_log_csv=log_csv, qa=qa)

    assert len(written) == 3  # MW-1.md, MW-2.md, SiteSummary.md
    assert (out_dir / "MW-1.md").exists()
    assert (out_dir / "MW-2.md").exists()
    assert (out_dir / "SiteSummary.md").exists()

    mw1_content = (out_dir / "MW-1.md").read_text(encoding="utf-8")
    assert "2026-06-01" in mw1_content
    # newest inspection first
    assert mw1_content.index("2026-06-01") < mw1_content.index("2026-01-01")


def test_build_well_inspection_reports_no_maintenance_log(tmp_path):
    wells_csv = tmp_path / "wells.csv"
    wells_csv.write_text("WellID\nMW-1\n", encoding="utf-8")
    out_dir = tmp_path / "reports"
    qa = QACollector()
    written = build_well_inspection_reports(
        wells_csv, out_dir, site_id="H281", qa=qa)
    assert len(written) == 2
    assert "No inspection records" in (out_dir / "MW-1.md").read_text(encoding="utf-8")
    assert any(r.category == "wells_never_inspected" for r in qa.records)


def test_malicious_well_id_cannot_escape_output_dir(tmp_path):
    """A WellID containing '../' must not write outside output_dir."""
    wells_csv = tmp_path / "wells.csv"
    wells_csv.write_text("WellID\n../../evil\n", encoding="utf-8")
    out_dir = tmp_path / "reports"
    qa = QACollector()
    written = build_well_inspection_reports(
        wells_csv, out_dir, site_id="H281", qa=qa)

    assert not (tmp_path / "evil.md").exists()
    for path in written:
        assert path.resolve().is_relative_to(out_dir.resolve())
    assert any(r.category == "unsafe_well_id" for r in qa.records)


def test_duplicate_well_id_does_not_silently_overwrite(tmp_path):
    """Two wells-CSV rows sharing a WellID must warn, not silently drop one."""
    wells_csv = tmp_path / "wells.csv"
    wells_csv.write_text(
        "WellID,Location\nMW-1,North\nMW-1,South\n", encoding="utf-8")
    out_dir = tmp_path / "reports"
    qa = QACollector()
    written = build_well_inspection_reports(
        wells_csv, out_dir, site_id="H281", qa=qa)

    # Only the first occurrence is written; count reflects reality.
    well_reports = [p for p in written if p.name != "SiteSummary.md"]
    assert len(well_reports) == 1
    assert "North" in (out_dir / "MW-1.md").read_text(encoding="utf-8")
    assert any(r.category == "duplicate_well_id" for r in qa.records)
