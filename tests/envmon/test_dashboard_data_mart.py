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


def _captured_warnings(fn):
    """Run `fn`, returning the module logger's WARNING text.

    Not caplog: `get_logger` sets `propagate = False` (#433), so capture via
    the root logger is at the mercy of pytest-internal behaviour for
    non-propagating loggers. Attaching to the logger under test is what the
    assertion actually means.
    """
    import logging

    from autogis.core.envmon import dashboard_data_mart as mart

    records = []

    class _Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Grab(level=logging.WARNING)
    mart.LOG.addHandler(handler)
    try:
        result = fn()
    finally:
        mart.LOG.removeHandler(handler)
    return result, "\n".join(records)


def test_select_prior_same_date_tie_is_order_independent():
    """Two rows for one well on one date must not be settled by cursor order.

    `arcpy.da.SearchCursor` guarantees no ordering, so a strict `>` tie-break
    let PriorGWE_ft / Delta_ft / Trend swing between runs over identical data
    (#473). Same input set, both orders, same answer.
    """
    current = [{"LocationID": "MW-2", "EventDate": "2026-06-01", "GWE_ft": 50.0}]
    all_wl = [
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 49.0,
         "SourceRow": 11},
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 48.0,
         "SourceRow": 42},
    ]
    forward = select_prior_water_levels(all_wl, current)
    reverse = select_prior_water_levels(list(reversed(all_wl)), current)
    assert len(forward) == len(reverse) == 1
    assert forward[0]["GWE_ft"] == reverse[0]["GWE_ft"]
    # The rule is deliberately arbitrary-but-fixed (highest SourceRow, then
    # highest elevation) -- NOT "last import wins", which this seam cannot
    # implement: ImportBatchID is a uuid4 hex with no chronology, and the
    # chronological ImportDateTime lives on a table this function never sees.
    # Pinned so the arbitrary choice cannot drift unnoticed.
    assert forward[0]["SourceRow"] == 42


def test_prior_pick_key_does_not_rest_on_importbatchid():
    """ImportBatchID is `uuid.uuid4().hex[:16].upper()` — lexical order over
    it is a coin flip with respect to import time. Reading it as provenance
    would dress that coin flip up as a policy, so it must not move the
    answer."""
    current = [{"LocationID": "MW-2", "EventDate": "2026-06-01", "GWE_ft": 50.0}]
    base = [
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 49.0,
         "SourceRow": 11, "ImportBatchID": "FFFFFFFFFFFFFFFF"},
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 48.0,
         "SourceRow": 42, "ImportBatchID": "0000000000000000"},
    ]
    # swapping the batch ids must not change which row is chosen
    swapped = [dict(base[0], ImportBatchID="0000000000000000"),
               dict(base[1], ImportBatchID="FFFFFFFFFFFFFFFF")]
    assert (select_prior_water_levels(base, current)[0]["SourceRow"]
            == select_prior_water_levels(swapped, current)[0]["SourceRow"]
            == 42)


def test_select_prior_tie_without_provenance_is_still_stable():
    """No ImportBatchID / SourceRow anywhere: the answer must still not depend
    on input order. All four key components are nullable in Env_WaterLevels."""
    current = [{"LocationID": "MW-2", "EventDate": "2026-06-01", "GWE_ft": 50.0}]
    all_wl = [
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 49.0},
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 48.0},
    ]
    forward = select_prior_water_levels(all_wl, current)
    reverse = select_prior_water_levels(list(reversed(all_wl)), current)
    assert forward[0]["GWE_ft"] == reverse[0]["GWE_ft"]


def test_select_prior_tie_is_disclosed():
    """A duplicated measurement date is itself something a reviewer should
    see — resolving it silently is half the defect (#473). The message must
    also not claim a provenance rule the seam cannot implement."""
    current = [{"LocationID": "MW-2", "EventDate": "2026-06-01", "GWE_ft": 50.0}]
    all_wl = [
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 49.0},
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 48.0},
    ]
    _, text = _captured_warnings(
        lambda: select_prior_water_levels(all_wl, current))
    assert "MW-2" in text and "2026-02-01" in text
    assert "arbitrary" in text        # says what it is, not "last import wins"
    assert "import" not in text.lower()


def test_select_prior_tie_disclosure_is_itself_order_independent():
    """A duplicated date that is later superseded must be disclosed either
    way. Compared pairwise against the running best, [A1, A2, B] warned and
    [A1, B, A2] did not — reporting that depends on cursor order is the exact
    defect this function stopped having (gitar review, PR #494)."""
    current = [{"LocationID": "MW-2", "EventDate": "2026-06-01", "GWE_ft": 50.0}]
    a1 = {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 49.0}
    a2 = {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 48.0}
    b = {"LocationID": "MW-2", "EventDate": "2026-03-01", "GWE_ft": 47.0}
    for order in ([a1, a2, b], [a1, b, a2], [b, a1, a2]):
        prior, text = _captured_warnings(
            lambda o=order: select_prior_water_levels(o, current))
        assert prior[0]["EventDate"] == "2026-03-01"   # B still wins
        assert "2026-02-01" in text, f"tie not disclosed for {order}"


def test_select_prior_latest_date_still_beats_a_newer_import():
    """The tiebreak must only ever decide ties: an older EventDate imported
    later must not displace the genuinely-latest prior reading."""
    current = [{"LocationID": "MW-2", "EventDate": "2026-06-01", "GWE_ft": 50.0}]
    all_wl = [
        {"LocationID": "MW-2", "EventDate": "2026-02-01", "GWE_ft": 49.0,
         "ImportBatchID": "2026-05-01T00:00:00"},
        {"LocationID": "MW-2", "EventDate": "2026-03-01", "GWE_ft": 47.0,
         "ImportBatchID": "2026-03-02T00:00:00"},
    ]
    prior = select_prior_water_levels(all_wl, current)
    assert prior[0]["EventDate"] == "2026-03-01"


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


def test_prior_selection_skips_rows_with_no_elevation():
    """#464 gave Survey123 water levels a real EventDate. Those rows carry a
    DTW but no TOC, so they out-date the workbook row and won the prior
    lookup — collapsing every Delta_ft to NULL and every Trend to "Unknown",
    the exact symptom #466 fixed, re-entering by a different door. Neither
    change is wrong alone; git could not see the interaction."""
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2026-03-15", _PRIOR_GWE: 100.0},
        {"LocationID": "MW-1", "EventDate": "2026-04-15",
         _PRIOR_GWE: None, "DepthToWater_ft": 12.5},   # Survey123, no TOC
    ]
    prior = select_prior_water_levels(all_wl, cur)
    assert [p["EventDate"] for p in prior] == ["2026-03-15"]

    row = build_dash_gw_level_summary(cur, prior, "H281", "2026Q2")[0]
    assert row["PriorGWE_ft"] == 100.0
    assert abs(row["Delta_ft"] - 0.5) < 1e-9
    assert row["Trend"] == "Rising"


def test_prior_selection_yields_nothing_when_no_row_has_an_elevation():
    """Genuinely no prior elevation -> no prior. Unknown is the right answer
    here, so the skip must not invent one."""
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [{"LocationID": "MW-1", "EventDate": "2026-04-15",
               _PRIOR_GWE: None}]
    assert select_prior_water_levels(all_wl, cur) == []
    row = build_dash_gw_level_summary(cur, [], "H281", "2026Q2")[0]
    assert row["Trend"] == "Unknown"


@pytest.mark.parametrize("unusable", ["N/A", "ND", "   ", "not measured"])
def test_prior_selection_skips_present_but_unparseable_elevations(unusable):
    """A presence test (`in (None, "")`) let "N/A"/"ND"/whitespace through, so
    the symptom returned. _prior_gwe_by_location already funnels through _num,
    so the two seams would disagree about what counts as an elevation."""
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2026-03-15", _PRIOR_GWE: 100.0},
        {"LocationID": "MW-1", "EventDate": "2026-04-15", _PRIOR_GWE: unusable},
    ]
    prior = select_prior_water_levels(all_wl, cur)
    assert [p["EventDate"] for p in prior] == ["2026-03-15"]
    assert build_dash_gw_level_summary(
        cur, prior, "H281", "2026Q2")[0]["Trend"] == "Rising"


def test_prior_selection_keeps_a_datum_relative_zero():
    """0.0 is a physically possible elevation; the skip must not eat it."""
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 0.5}]
    all_wl = [{"LocationID": "MW-1", "EventDate": "2026-03-15", _PRIOR_GWE: 0.0}]
    prior = select_prior_water_levels(all_wl, cur)
    assert len(prior) == 1
    assert build_dash_gw_level_summary(
        cur, prior, "H281", "2026Q2")[0]["PriorGWE_ft"] == 0.0


def test_shadowed_newer_prior_is_disclosed(caplog):
    """The delta can now span a different pair of events than the two most
    recent, and Dash_* has no prior-date column to show it."""
    import logging
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2024-01-01", _PRIOR_GWE: 90.0},
        {"LocationID": "MW-1", "EventDate": "2026-05-01", _PRIOR_GWE: None},
    ]
    with caplog.at_level(logging.INFO):
        select_prior_water_levels(all_wl, cur)
    assert "prior-water-level" in caplog.text
    assert "2026-05-01" in caplog.text and "2024-01-01" in caplog.text


def test_no_disclosure_for_a_row_that_was_never_a_prior_candidate(caplog):
    """The skip was recorded BEFORE the candidate filter, so the current
    event's own DTW-only row was announced as a "shadowed prior" — which
    post-#464 is every well, every run. A disclosure channel that is wrong by
    default trains operators to ignore it, which is worse than the gap it
    discloses."""
    import logging
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2026-03-15", _PRIOR_GWE: 99.0},
        {"LocationID": "MW-1", "EventDate": "2026-06-15", _PRIOR_GWE: None},
    ]
    with caplog.at_level(logging.INFO):
        prior = select_prior_water_levels(all_wl, cur)
    assert [p["EventDate"] for p in prior] == ["2026-03-15"]
    assert "prior-water-level" not in caplog.text


def test_no_disclosure_for_a_skip_outside_an_explicit_prior_date(caplog):
    """Same rule on the explicit-date branch: a skipped row on an unrelated
    date was never a candidate for the date the caller named."""
    import logging
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2026-03-15", _PRIOR_GWE: 99.0},
        {"LocationID": "MW-1", "EventDate": "2026-05-01", _PRIOR_GWE: None},
    ]
    with caplog.at_level(logging.INFO):
        select_prior_water_levels(all_wl, cur, prior_event_id="2026-03-15")
    assert "prior-water-level" not in caplog.text


def test_usable_gwe_ft_survives_a_junk_primary_spelling():
    """_row_gwe fell back only when the primary was absent, so junk under
    GroundwaterElevation_ft discarded a usable GWE_ft — the two-seams-disagree
    problem closed at the caller and left open in the helper."""
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [{"LocationID": "MW-1", "EventDate": "2026-03-15",
               _PRIOR_GWE: "N/A", "GWE_ft": 99.0}]
    prior = select_prior_water_levels(all_wl, cur)
    assert len(prior) == 1
    row = build_dash_gw_level_summary(cur, prior, "H281", "2026Q2")[0]
    assert row["PriorGWE_ft"] == 99.0


def test_null_location_id_among_skipped_rows_does_not_crash(caplog):
    """LocationID is nullable and a SearchCursor yields NULL as None, so one
    NULL beside one real id made the disclosure's bare sorted() raise
    "'<' not supported between NoneType and str" — aborting the entire mart
    build. A crash this batch introduced, in a column the schema allows."""
    import logging
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2024-01-01", _PRIOR_GWE: 90.0},
        {"LocationID": "MW-1", "EventDate": "2026-05-01", _PRIOR_GWE: None},
        {"LocationID": None, "EventDate": "2026-05-01", _PRIOR_GWE: None},
    ]
    with caplog.at_level(logging.INFO):
        prior = select_prior_water_levels(all_wl, cur)   # must not raise
    assert [p["EventDate"] for p in prior] == ["2024-01-01"]
    assert "prior-water-level" in caplog.text


def test_explicit_prior_date_with_a_null_location_id_does_not_crash():
    """Same shape on the explicit-date branch, which is where it first bit."""
    cur = [{"LocationID": "MW-1", "EventDate": "2026-06-15", "GWE_ft": 100.5}]
    all_wl = [
        {"LocationID": "MW-1", "EventDate": "2026-03-15", _PRIOR_GWE: None},
        {"LocationID": None, "EventDate": "2026-03-15", _PRIOR_GWE: None},
    ]
    assert select_prior_water_levels(all_wl, cur, "2026-03-15") == []
