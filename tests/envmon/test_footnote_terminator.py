"""Non-sample rows must not be parsed as data (ADR-0106).

Real MDEQ groundwater reports (e.g. the H272 Havre workbooks) carry rows that
look structurally like data but carry no measurement:

* a ``NOTES:`` footnote/legend block whose label sits in the ID column, with
  color-legend prose in the analyte cells; and
* inline event-marker rows with a real well ID, a *blank* date, and a prose
  annotation in an analyte cell (``BOS 200 Pilot Test Injections ...``).

Both used to be emitted as bogus records; a 66-char legend/annotation value even
overflowed ``Env_AnalyticalResults.ResultRawText`` TEXT(64) and crashed the GDB
insert. The unifying guard: a row with **no valid date AND no parseable result**
is not a sample — skip it (drop sample *and* results / water level). A row that
has *either* a date *or* a numeric result survives.
"""
import openpyxl
import pytest

from autogis.core.common.config import ParserProfile
from autogis.core.common.qa import QACollector
from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader
from autogis.core.envmon.normalize_groundwater import normalize_gw_table_2

BOS = "BOS 200 Pilot Test Injections Performed on October 23 and 24, 2025"  # 66 chars
LEGEND = "Purple = Lab reporting limit is equal to or greater than MDEQ RBSL"  # 66

PROFILE_YAML = """\
profile_id: test_footnote
plausible_gwe_range_ft: [0, 10000]
sheets:
  - sheet_name: "GWA"
    data_type: GW_ANALYTICAL
    analyte_header_row: 6
    units_row: 7
    data_start_row: 9
    id_column: A
    date_column: B
    analyte_columns: {from: C, to: D}
  - sheet_name: "GWL"
    data_type: GW_WATER_LEVEL_ONLY
    analyte_header_row: 6
    units_row: 7
    data_start_row: 9
    id_column: A
    date_column: B
    gwe_column: C
"""


@pytest.fixture
def parsed(tmp_path):
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "GWA"
    a["C6"] = "Benzene"; a["D6"] = "Toluene"
    a["A9"] = "MW-1"; a["B9"] = "2025-01-01"; a["C9"] = "0.5"; a["D9"] = "<1.0"     # real
    a["A10"] = "MW-2"; a["B10"] = None;        a["C10"] = "1.2"                      # dateless + numeric -> keep
    a["A11"] = "ANN-1"; a["B11"] = None;       a["C11"] = BOS                        # BOS annotation -> drop
    a["A12"] = "NOTES:"; a["B12"] = "Red = concentration exceeds MDEQ RBSL"          # NOTES legend -> drop
    a["C12"] = LEGEND
    a["A13"] = "MW-F"; a["B13"] = None;        a["C13"] = "=1+1"                      # dateless + FORMULA (no cached value) -> keep (formula QA)
    w = wb.create_sheet("GWL")
    w["C6"] = "GWE"
    w["A9"] = "MW-1"; w["B9"] = "2025-01-01"; w["C9"] = 2475.0                       # real
    w["A10"] = "NOTES:"; w["B10"] = "NP: not present"; w["C10"] = None               # NOTES -> drop
    wb_path = tmp_path / "footnote.xlsx"
    wb.save(wb_path)
    prof_path = tmp_path / "prof.yaml"
    prof_path.write_text(PROFILE_YAML, encoding="utf-8")
    profile = ParserProfile.load(prof_path)
    qa = QACollector()
    reader = ProfileWorkbookReader(wb_path, profile, qa)
    wl, samples, results = normalize_gw_table_2(
        wb_path, profile, "SITE", "B", {}, {}, qa, reader=reader)
    return wl, samples, results, qa


def test_footnote_and_annotation_rows_dropped_analytical(parsed):
    _wl, samples, results, _qa = parsed
    samp_ids = {s.LocationID for s in samples}
    assert "NOTES:" not in samp_ids, "NOTES footnote row must not become a sample"
    assert "ANN-1" not in samp_ids, "BOS annotation row must not become a sample"
    assert not any(r.LocationID in ("NOTES:", "ANN-1") for r in results), \
        "no bogus analytical results from non-sample rows"


def test_no_prose_overflows_resultrawtext(parsed):
    """The bug's crash signature: a >64-char prose value in ResultRawText.
    After the fix, nothing prose-length leaks into a result record."""
    _wl, _samples, results, _qa = parsed
    assert all(len(r.ResultRawText) <= 64 for r in results)


def test_dateless_but_numeric_row_survives(parsed):
    """Guard keys on 'no date AND no result' — a real dateless row that still
    carries a numeric result must be kept (guards against an over-broad fix)."""
    _wl, samples, results, _qa = parsed
    assert "MW-2" in {s.LocationID for s in samples}
    assert any(r.LocationID == "MW-2" for r in results)


def test_dateless_formula_row_survives_and_flags(parsed):
    """A dateless row whose only result is a formula with NO cached value must
    survive — its value reads as blank, but dropping it would silently lose the
    row AND skip the mandatory formula_cell_missing_cached_value error (codex P1)."""
    _wl, samples, _results, qa = parsed
    assert "MW-F" in {s.LocationID for s in samples}, \
        "formula-backed dateless row must not be dropped"
    codes = {getattr(m, "category", "") for m in qa.records}
    assert "formula_cell_missing_cached_value" in codes, \
        "the mandatory formula-recalc QA error must still fire"


def test_footnote_row_dropped_water_level(parsed):
    wl, _samples, _results, _qa = parsed
    wl_ids = {w.LocationID for w in wl}
    assert "MW-1" in wl_ids
    assert "NOTES:" not in wl_ids, "NOTES footnote must not become a water level"


def test_skip_is_visible_in_qa(parsed):
    """Dropped rows must be surfaced, not silently discarded."""
    _wl, _samples, _results, qa = parsed
    codes = {getattr(m, "category", "") for m in qa.records}
    assert "skipped_non_sample_row" in codes
    assert "skipped_non_data_row" in codes
