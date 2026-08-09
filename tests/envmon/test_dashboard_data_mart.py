"""Tests for dashboard_data_mart transformation functions (Tool 6.7) — arcpy-free.

Checklist mirrors the Approved design spec
docs/superpowers/specs/2026-06-27-build-dashboard-data-mart-design.md
Only the pure-Python transformation layer is exercised (the arcpy orchestrator
is marked ``# pragma: no cover``). Output dict keys follow the Dash_* schemas in
gdb_schema.py.
"""
import dataclasses
import json

import pytest

from autogis.core.envmon.dashboard_data_mart import (
    MartSummary,
    select_prior_water_levels,
    build_dash_site_status,
    build_dash_event_status,
    build_dash_well_status,
    build_dash_gw_level_summary,
    build_dash_current_exceedances,
    build_dash_analytical_summary,
    build_dash_field_qa,
    build_dash_lab_qa,
    build_dash_open_issues,
    export_dashboard_json,
)


def test_select_prior_picks_latest_before_current():
    """Per well, the prior row is the latest EventDate strictly before the
    current event — not whichever row is last in iteration order."""
    current = [{"LocationID": "MW-01", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-01", "EventDate": "2026-03-15", "GWE_ft": 100.0},
        {"LocationID": "MW-01", "EventDate": "2025-12-15", "GWE_ft": 99.0},
        # A later/equal-to-current row must be ignored as a "prior".
        {"LocationID": "MW-01", "EventDate": "2026-06-15", "GWE_ft": 100.5},
    ]
    prior = select_prior_water_levels(all_wl, current)
    assert len(prior) == 1
    assert prior[0]["EventDate"] == "2026-03-15"  # latest strictly-before


def test_select_prior_explicit_event_date_restricts_candidates():
    current = [{"LocationID": "MW-01", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-01", "EventDate": "2026-03-15", "GWE_ft": 100.0},
        {"LocationID": "MW-01", "EventDate": "2025-12-15", "GWE_ft": 99.0},
    ]
    prior = select_prior_water_levels(all_wl, current, prior_event_id="2025-12-15")
    assert len(prior) == 1
    assert prior[0]["EventDate"] == "2025-12-15"


def test_site_status_active_events_counts_wide_rows():
    wide = [{"LocationID": "MW-01"}, {"LocationID": "MW-02"},
            {"LocationID": "MW-03"}]
    qa_err = [{"Severity": "ERROR", "Category": "x"}]
    rows = build_dash_site_status(wide, qa_err, "H281", "2026Q2")
    assert len(rows) == 1
    assert rows[0]["ActiveEvents"] == 3
    assert rows[0]["OpenQAIssues"] == 1
    assert rows[0]["SiteID"] == "H281"
    assert "EventID" not in rows[0]
    assert "site grain" in build_dash_site_status.__doc__


def test_event_status_partial_lab_results_not_received():
    samples = [{"LocationID": "MW-01", "SampleID": "S1"},
               {"LocationID": "MW-02", "SampleID": "S2"}]
    results = [{"LocationID": "MW-01", "AnalyteName": "Benzene"}]  # only MW-01
    rows = build_dash_event_status(samples, results, "H281", "2026Q2")
    assert rows[0]["WellsSampled"] == 2
    assert rows[0]["LabReceived"] == 0  # partial -> not fully received


# Prior rows come from Env_WaterLevels, whose elevation column is
# GroundwaterElevation_ft — NOT the Env_CurrentWaterLevelEvent spelling
# (GWE_ft) the current rows use. These fixtures deliberately use the real
# source spelling: written with GWE_ft they agreed with #466 and passed while
# the production path produced NULL deltas and "Unknown" trends everywhere.
_PRIOR_GWE = "GroundwaterElevation_ft"


def test_prior_column_name_matches_env_waterlevels_schema():
    """Pin the fixture spelling to the schema so this cannot drift back."""
    from autogis.core.envmon.gdb_schema import TABLE_SCHEMAS
    assert _PRIOR_GWE in {c[0] for c in TABLE_SCHEMAS["Env_WaterLevels"]}
    assert "GWE_ft" not in {c[0] for c in TABLE_SCHEMAS["Env_WaterLevels"]}


def test_well_status_delta():
    cur = [{"LocationID": "MW-01", "GWE_ft": 100.5, "Status": "measured"}]
    prior = [{"LocationID": "MW-01", _PRIOR_GWE: 100.0}]
    rows = build_dash_well_status(cur, prior, "H281", "2026Q2")
    assert abs(rows[0]["GWEDelta_ft"] - 0.5) < 1e-9


def test_gw_level_summary_rising_trend():
    cur = [{"LocationID": "MW-01", "GWE_ft": 100.5}]
    prior = [{"LocationID": "MW-01", _PRIOR_GWE: 100.0}]
    rows = build_dash_gw_level_summary(cur, prior, "H281", "2026Q2")
    assert rows[0]["Trend"] == "Rising"
    assert abs(rows[0]["Delta_ft"] - 0.5) < 1e-9


def test_prior_water_levels_flow_from_selector_to_delta():
    """End-to-end at the real seam: Env_WaterLevels rows -> selector ->
    builder. The selector renames nothing, so the builder must read the
    source table's own column name (#466)."""
    cur = [{"LocationID": "MW-01", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-01", "EventDate": "2026-03-15", _PRIOR_GWE: 100.0},
        {"LocationID": "MW-01", "EventDate": "2025-12-15", _PRIOR_GWE: 99.0},
    ]
    prior = select_prior_water_levels(all_wl, cur)
    rows = build_dash_gw_level_summary(cur, prior, "H281", "2026Q2")
    assert rows[0]["PriorGWE_ft"] == 100.0
    assert abs(rows[0]["Delta_ft"] - 0.5) < 1e-9
    assert rows[0]["Trend"] == "Rising"


def test_gw_level_summary_falling_and_stable():
    cur = [{"LocationID": "A", "GWE_ft": 99.0}, {"LocationID": "B", "GWE_ft": 100.05}]
    prior = [{"LocationID": "A", _PRIOR_GWE: 100.0},
             {"LocationID": "B", _PRIOR_GWE: 100.0}]
    rows = {r["LocationID"]: r for r in
            build_dash_gw_level_summary(cur, prior, "H281", "2026Q2")}
    assert rows["A"]["Trend"] == "Falling"
    assert rows["B"]["Trend"] == "Stable"


def test_current_exceedances_filters_exceedances_only():
    results = [
        {"LocationID": "MW-01", "AnalyteName": "Benzene", "ExceedsScreeningLevel": 1,
         "ResultNumeric": 12.0, "Units": "ug/L"},
        {"LocationID": "MW-02", "AnalyteName": "Toluene", "ExceedsScreeningLevel": 0,
         "ResultNumeric": 1.0, "Units": "ug/L"},
    ]
    rows = build_dash_current_exceedances(results, "H281", "2026Q2")
    assert len(rows) == 1
    assert rows[0]["Analyte"] == "Benzene"


def test_analytical_summary_one_row_per_result():
    results = [
        {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultNumeric": 12.0,
         "Units": "ug/L", "IsDetected": 1, "ExceedsScreeningLevel": 1},
        {"LocationID": "MW-02", "AnalyteName": "Toluene", "ResultNumeric": 0.0,
         "Units": "ug/L", "IsDetected": 0, "ExceedsScreeningLevel": 0},
    ]
    rows = build_dash_analytical_summary(results, "H281", "2026Q2")
    assert len(rows) == 2
    benz = next(r for r in rows if r["Analyte"] == "Benzene")
    assert benz["IsExceedance"] == 1


def test_field_qa_filters_null_analyte():
    qa = [
        {"Category": "missing_well", "AnalyteName": "", "LocationID": "MW-01",
         "Message": "no well", "Severity": "ERROR"},
        {"Category": "lab_issue", "AnalyteName": "Benzene", "LocationID": "MW-02",
         "Message": "lab", "Severity": "WARNING"},
    ]
    rows = build_dash_field_qa(qa, "H281", "2026Q2")
    assert len(rows) == 1
    assert rows[0]["LocationID"] == "MW-01"


def test_lab_qa_filters_nonnull_analyte():
    qa = [
        {"Category": "missing_well", "AnalyteName": "", "LocationID": "MW-01",
         "Message": "no well", "Severity": "ERROR"},
        {"Category": "lab_issue", "AnalyteName": "Benzene", "LocationID": "MW-02",
         "Message": "lab", "Severity": "WARNING"},
    ]
    rows = build_dash_lab_qa(qa, "H281", "2026Q2")
    assert len(rows) == 1
    assert rows[0]["Analyte"] == "Benzene"


def test_open_issues_grouped_by_domain_severity_description():
    qa = [
        {"Category": "a", "Severity": "ERROR", "Message": "boom", "LocationID": ""},
        {"Category": "a", "Severity": "ERROR", "Message": "boom", "LocationID": ""},
        {"Category": "b", "Severity": "WARNING", "Message": "meh", "LocationID": ""},
    ]
    rows = build_dash_open_issues(qa, "H281", "2026Q2")
    # Two distinct (Domain, Severity, Description) groups.
    assert len(rows) == 2


def test_mart_summary_is_json_serializable():
    s = MartSummary(site_id="H281", event_id="2026Q2", built_at="2026-06-29",
                    tables_updated=["Dash_SiteStatus"],
                    row_counts={"Dash_SiteStatus": 1})
    d = dataclasses.asdict(s)
    assert d["row_counts"]["Dash_SiteStatus"] == 1


def test_export_dashboard_json_matches_refresh_dashboard_input(tmp_path):
    tables = {
        "Dash_WellStatus": [{"SiteName": "Café", "SiteID": "S1"}],
        "Dash_SiteStatus": [],
    }

    paths = export_dashboard_json(tables, tmp_path)

    assert paths == [
        tmp_path / "Dash_SiteStatus.json",
        tmp_path / "Dash_WellStatus.json",
    ]
    loaded = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in tmp_path.glob("Dash_*.json")
    }
    assert loaded == tables
    well_path = tmp_path / "Dash_WellStatus.json"
    first_bytes = well_path.read_bytes()
    assert "Café".encode() in first_bytes

    # Re-exporting equivalent data with different insertion order overwrites
    # the prior artifact without changing its deterministic bytes.
    export_dashboard_json({
        "Dash_SiteStatus": [],
        "Dash_WellStatus": [{"SiteID": "S1", "SiteName": "Café"}],
    }, tmp_path)
    assert well_path.read_bytes() == first_bytes
    assert not list(tmp_path.glob("*.tmp"))


def test_export_dashboard_json_preserves_existing_file_on_replace_failure(
    tmp_path, monkeypatch,
):
    target = tmp_path / "Dash_SiteStatus.json"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(
        "autogis.core.envmon.dashboard_data_mart.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        export_dashboard_json({"Dash_SiteStatus": [{"SiteID": "S1"}]}, tmp_path)

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("*.tmp"))


def test_export_dashboard_json_rejects_unsafe_table_name(tmp_path):
    with pytest.raises(ValueError, match="Invalid dashboard table name"):
        export_dashboard_json({"../Dash_Bad": []}, tmp_path)

    assert not list(tmp_path.iterdir())


def test_export_dashboard_json_serializes_before_writing(tmp_path):
    with pytest.raises(ValueError, match="Out of range float values"):
        export_dashboard_json({"Dash_BadValue": [{"Result": float("nan")}]},
                              tmp_path)

    assert not list(tmp_path.iterdir())


def test_export_dashboard_json_rejects_stale_dash_file(tmp_path):
    stale = tmp_path / "Dash_FormerTable.json"
    stale.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Dash_FormerTable.json"):
        export_dashboard_json({"Dash_SiteStatus": []}, tmp_path)

    assert stale.read_text(encoding="utf-8") == "[]\n"
    assert not (tmp_path / "Dash_SiteStatus.json").exists()
