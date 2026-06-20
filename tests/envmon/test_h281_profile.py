"""End-to-end normalization of the synthetic workbook through the same
code path the import tool uses (minus arcpy)."""

import pytest

from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader
from autogis.core.envmon.normalize_groundwater import normalize_gw_table_2
from autogis.core.envmon.normalize_metals import normalize_metals_table
from autogis.core.envmon.normalize_ibi import normalize_ibi_table
from autogis.core.envmon.normalize_rpd import normalize_rpd_table

BATCH = "TESTBATCH"


@pytest.fixture()
def gw(workbook, profile, adict, slevels, qa):
    reader = ProfileWorkbookReader(workbook, profile, qa)
    wl, samples, results = normalize_gw_table_2(
        workbook, profile, "H281", BATCH, adict, slevels, qa, reader=reader)
    return dict(wl=wl, samples=samples, results=results, qa=qa,
                reader=reader)


def test_water_level_counts_and_statuses(gw):
    wl = {w.LocationID: w for w in gw["wl"]}
    assert set(wl) == {"MW-1", "MW-2", "MW-3", "MW-4", "MW-5"}
    # Dry well: no GWE, excluded from contouring, status preserved
    assert wl["MW-3"].IsDry == 1
    assert wl["MW-3"].UseForContour == 0
    assert wl["MW-3"].GroundwaterElevation_ft is None
    assert wl["MW-3"].ExclusionReason
    # Not-measured well likewise excluded
    assert wl["MW-4"].UseForContour == 0
    # Good wells contourable with the literal GWE
    assert wl["MW-2"].GroundwaterElevation_ft == pytest.approx(2089.30)
    assert wl["MW-2"].UseForContour == 1
    assert wl["MW-5"].GroundwaterElevation_ft == pytest.approx(2090.10)


def test_formula_without_cached_value_raises_qa_error(gw):
    """MW-1 GWE is '=D10-E10' with no cached value: must be a QA ERROR and
    must NOT silently become a number."""
    wl = {w.LocationID: w for w in gw["wl"]}
    assert wl["MW-1"].GroundwaterElevation_ft is None
    assert wl["MW-1"].UseForContour == 0
    cats = [(r.severity, r.category) for r in gw["qa"].records]
    assert any(sev in ("ERROR", "CRITICAL") and "formula" in cat.lower()
               for sev, cat in cats), cats


def test_results_nondetect_and_qualifiers(gw):
    res = gw["results"]
    by = {(r.LocationID, r.AnalyteCanonicalName): r for r in res}
    nd = by[("MW-2", "Benzene")]
    assert nd.IsNonDetect == 1 and nd.IsDetected == 0
    assert nd.ResultNumeric is None             # nondetect != 0
    assert nd.ReportingLimit == pytest.approx(1.0)
    est = by[("MW-1", "Benzene")]                # "12 J"
    assert est.IsDetected == 1 and est.IsEstimated == 1
    assert est.ResultNumeric == pytest.approx(12.0)
    u = by[("MW-1", "Ethylbenzene")]             # "<0.50 U"
    assert u.IsNonDetect == 1 and u.ReportingLimit == pytest.approx(0.5)
    ns = by[("MW-3", "Benzene")]
    assert ns.IsNotSampled == 1 and ns.ResultNumeric is None


def test_exceedance_against_workbook_screening_row(gw):
    by = {(r.LocationID, r.AnalyteCanonicalName): r for r in gw["results"]}
    hot = by[("MW-5", "Benzene")]                # 6.4 vs RBSL 5
    assert hot.ScreeningLevel == pytest.approx(5.0)
    assert hot.ExceedsScreeningLevel == 1
    cold = by[("MW-1", "Benzene")]               # 12 vs 5 -> also exceeds
    assert cold.ExceedsScreeningLevel == 1
    ndr = by[("MW-2", "Benzene")]
    # tri-state by design: nondetects are None (not evaluable), never True
    assert ndr.ExceedsScreeningLevel is None


def test_footnote_screening_level_parsed(gw):
    """L9 '1,000 3' -> TPH screening level 1000 with a QA note."""
    by = {(r.LocationID, r.AnalyteCanonicalName): r for r in gw["results"]}
    tph = by[("MW-1", "TPH")]
    assert tph.ScreeningLevel == pytest.approx(1000.0)


def test_source_cell_tracking(gw):
    by = {(r.LocationID, r.AnalyteCanonicalName): r for r in gw["results"]}
    hot = by[("MW-5", "Benzene")]
    assert hot.SourceSheet == "GW Table 2"
    assert hot.SourceCell == "G14"
    assert hot.SourceRow == 14


def test_mpe_minus_dtw_consistency(gw):
    """Wells with literal GWE must satisfy MPE - DTW == GWE within 0.02 ft;
    no consistency QA error should exist for MW-2/MW-5."""
    bad = [r for r in gw["qa"].records
           if "consistency" in r.category.lower()
           and r.location_id in ("MW-2", "MW-5")]
    assert bad == []


def test_metals_and_ibi(workbook, profile, adict, slevels, qa):
    reader = ProfileWorkbookReader(workbook, profile, qa)
    s, r = normalize_metals_table(workbook, profile, "H281", BATCH, adict,
                                  slevels, qa, reader=reader)
    assert {x.Matrix for x in r} == {"GW"}
    by = {(x.LocationID, x.AnalyteCanonicalName): x for x in r}
    assert by[("MW-1", "Arsenic")].IsNonDetect == 1
    assert by[("MW-1", "Lead")].IsEstimated == 1
    s2, r2 = normalize_ibi_table(workbook, profile, "H281", BATCH, adict,
                                 slevels, qa, reader=reader)
    by2 = {(x.LocationID, x.AnalyteCanonicalName): x for x in r2}
    assert by2[("MW-1", "Methane")].IsNotAnalyzed == 1
    assert by2[("MW-2", "Sulfate")].IsNonDetect == 1


def test_rpd_recompute_and_mismatch(workbook, profile, qa):
    reader = ProfileWorkbookReader(workbook, profile, qa)
    recs = normalize_rpd_table(workbook, profile, "H281", BATCH, qa,
                               reader=reader)
    by = {r.AnalyteName: r for r in recs}
    assert by["Benzene"].RPDStatus == "CALCULATED"
    assert by["Benzene"].RPDValue == pytest.approx(6.45, abs=0.05)
    assert by["Benzene"].CalculationError == ""
    assert by["Toluene"].RPDStatus == "NC_NONDETECT"
    assert by["Toluene"].RPDValue is None
    # MTBE: recomputed 22.2 vs workbook 30 -> mismatch recorded + QA warning
    assert by["MTBE"].CalculationError
    assert any(r.category == "rpd_calculation_mismatch"
               for r in qa.records)
    assert by["Benzene"].EventDate is not None
