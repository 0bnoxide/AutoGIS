"""Tests for GenerateEventChangeLog (roadmap 9.3) — event_changelog.py."""
import zipfile

import pytest

from autogis.core.envmon.event_changelog import (
    ChangeRecord,
    ChangeType,
    EventChangeResult,
    generate_event_changelog,
    write_changelog_csv,
    write_changelog_workbook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(loc: str, analyte: str, value=1.0, exceeds=0) -> dict:
    return {
        "LocationID": loc,
        "AnalyteName": analyte,
        "ResultNumeric": str(value) if value is not None else "",
        "ExceedsScreeningLevel": str(exceeds) if exceeds is not None else "",
    }


PRIOR = [
    _row("MW-1", "Benzene", 1.0, 0),
    _row("MW-1", "Toluene", 5.0, 0),
    _row("MW-2", "Benzene", 10.0, 1),
]

CURRENT = [
    _row("MW-1", "Benzene", 1.0, 0),    # NO_CHANGE (0% delta)
    _row("MW-1", "Toluene", 20.0, 0),   # VALUE_CHANGE (+300%)
    _row("MW-2", "Benzene", 2.0, 0),    # CLEARED_EXCEEDANCE (was 1 -> 0)
    _row("MW-3", "Benzene", 1.0, 0),    # NEW_LOCATION (MW-3 absent from prior)
]


def _by_key(result: EventChangeResult) -> dict:
    return {(c.location_id, c.analyte_name): c for c in result.changes}


# ---------------------------------------------------------------------------
# Change-type classification
# ---------------------------------------------------------------------------

def test_new_location():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    c = m[("MW-3", "Benzene")]
    assert c.change_type == ChangeType.NEW_LOCATION
    assert c.prior_value is None
    assert c.current_value == pytest.approx(1.0)


def test_dropped_location():
    prior = PRIOR + [_row("MW-99", "Benzene", 5.0, 0)]
    m = _by_key(generate_event_changelog(prior, CURRENT))
    c = m[("MW-99", "Benzene")]
    assert c.change_type == ChangeType.DROPPED_LOCATION
    assert c.current_value is None
    assert c.prior_value == pytest.approx(5.0)


def test_new_analyte_in_existing_location():
    current = CURRENT + [_row("MW-1", "Arsenic", 0.5, 0)]
    m = _by_key(generate_event_changelog(PRIOR, current))
    # MW-1 already in prior, so Arsenic is NEW_ANALYTE (not NEW_LOCATION)
    assert m[("MW-1", "Arsenic")].change_type == ChangeType.NEW_ANALYTE


def test_dropped_analyte_existing_location():
    prior = PRIOR + [_row("MW-2", "Toluene", 3.0, 0)]
    m = _by_key(generate_event_changelog(prior, CURRENT))
    # MW-2 still present in current (Benzene exists), so Toluene is DROPPED_ANALYTE
    assert m[("MW-2", "Toluene")].change_type == ChangeType.DROPPED_ANALYTE


def test_new_exceedance():
    prior = [_row("MW-1", "Lead", 1.0, 0)]
    current = [_row("MW-1", "Lead", 12.0, 1)]
    m = _by_key(generate_event_changelog(prior, current))
    assert m[("MW-1", "Lead")].change_type == ChangeType.NEW_EXCEEDANCE


def test_cleared_exceedance():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    assert m[("MW-2", "Benzene")].change_type == ChangeType.CLEARED_EXCEEDANCE


def test_value_change_above_threshold():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    c = m[("MW-1", "Toluene")]
    assert c.change_type == ChangeType.VALUE_CHANGE
    assert c.delta_pct == pytest.approx(300.0)


def test_no_change_identical_rows():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    assert m[("MW-1", "Benzene")].change_type == ChangeType.NO_CHANGE


def test_delta_pct_below_threshold_is_no_change():
    prior = [_row("MW-1", "Benzene", 10.0, 0)]
    current = [_row("MW-1", "Benzene", 10.5, 0)]   # +5%, below default 10%
    m = _by_key(generate_event_changelog(prior, current, delta_pct_threshold=10.0))
    assert m[("MW-1", "Benzene")].change_type == ChangeType.NO_CHANGE


# ---------------------------------------------------------------------------
# delta_pct calculation
# ---------------------------------------------------------------------------

def test_delta_pct_positive():
    prior = [_row("MW-1", "Benzene", 10.0, 0)]
    current = [_row("MW-1", "Benzene", 15.0, 0)]   # +50%
    m = _by_key(generate_event_changelog(prior, current, delta_pct_threshold=10.0))
    assert m[("MW-1", "Benzene")].delta_pct == pytest.approx(50.0)


def test_delta_pct_negative():
    prior = [_row("MW-1", "Benzene", 20.0, 0)]
    current = [_row("MW-1", "Benzene", 10.0, 0)]   # -50%
    m = _by_key(generate_event_changelog(prior, current, delta_pct_threshold=10.0))
    assert m[("MW-1", "Benzene")].delta_pct == pytest.approx(-50.0)


def test_delta_pct_none_when_prior_zero():
    prior = [_row("MW-1", "Benzene", 0.0, 0)]
    current = [_row("MW-1", "Benzene", 5.0, 0)]
    result = generate_event_changelog(prior, current)
    m = _by_key(result)
    assert m[("MW-1", "Benzene")].delta_pct is None
    assert any(r.category == "zero_prior_value" for r in result.qa.records)


def test_delta_pct_none_when_either_value_missing():
    prior = [_row("MW-1", "Benzene", None, 0)]
    current = [_row("MW-1", "Benzene", 5.0, 0)]
    m = _by_key(generate_event_changelog(prior, current))
    assert m[("MW-1", "Benzene")].delta_pct is None


# ---------------------------------------------------------------------------
# Summary counts and metadata
# ---------------------------------------------------------------------------

def test_summary_counts():
    result = generate_event_changelog(PRIOR, CURRENT)
    assert result.new_location_count == 1         # MW-3
    assert result.dropped_location_count == 0
    assert result.cleared_exceedance_count == 1   # MW-2/Benzene
    assert result.new_exceedance_count == 0


def test_event_ids_propagate():
    result = generate_event_changelog(
        PRIOR, CURRENT,
        prior_event_id="E-2025-Q3",
        current_event_id="E-2026-Q1",
    )
    assert result.prior_event_id == "E-2025-Q3"
    assert result.current_event_id == "E-2026-Q1"


def test_qa_changelog_complete_emitted():
    result = generate_event_changelog(PRIOR, CURRENT)
    assert any(r.category == "changelog_complete" for r in result.qa.records)


def test_empty_inputs_return_no_changes():
    result = generate_event_changelog([], [])
    assert result.changes == []
    assert result.new_location_count == 0


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_changelog_csv(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.csv"
    write_changelog_csv(result, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "location_id" in text
    assert "change_type" in text
    assert "delta_pct" in text


def test_write_changelog_csv_row_count(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.csv"
    write_changelog_csv(result, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    # header + one row per change record
    assert len(lines) == 1 + len(result.changes)


def test_write_changelog_workbook(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.xlsx"
    write_changelog_workbook(result, out)
    assert out.exists()
    # XLSX is a ZIP archive; check it opens and has sheet XML files
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any("sheet" in n.lower() for n in names)


def test_write_changelog_workbook_has_all_sheets(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.xlsx"
    write_changelog_workbook(result, out)
    import openpyxl
    wb = openpyxl.load_workbook(out)
    expected_sheets = {
        "NEW_LOCATION", "DROPPED_LOCATION", "NEW_ANALYTE", "DROPPED_ANALYTE",
        "NEW_EXCEEDANCE", "CLEARED_EXCEEDANCE", "VALUE_CHANGE", "NO_CHANGE",
    }
    assert expected_sheets == set(wb.sheetnames)


def test_workbook_qa_info_emitted(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.xlsx"
    write_changelog_workbook(result, out)
    assert any(r.category == "workbook_written" for r in result.qa.records)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def test_help_lists_options():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    r = CliRunner().invoke(autogis, ["envmon", "generate-event-changelog", "--help"])
    assert r.exit_code == 0
    for opt in (
        "--prior-csv", "--current-csv", "--prior-event-id", "--current-event-id",
        "--out", "--out-xlsx", "--delta-pct-threshold", "--report", "--fail-on",
    ):
        assert opt in r.output
