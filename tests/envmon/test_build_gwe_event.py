"""Unit tests for build_gwe_event (Tool 4.1) — contour-event layer + flags."""
from autogis.core.envmon.build_gwe_event import build_gwe_event


def _wl(loc, gwe, status="OK", dtw=10.0, site="S1"):
    return {"site_id": site, "location_id": loc, "gwe_ft": gwe,
            "dtw_ft": dtw, "status": status, "measured_by": "field"}


def test_one_record_per_well_for_event():
    wls = [_wl("MW-1", 100.0), _wl("MW-2", 101.0)]
    res = build_gwe_event(wls, event_date="2026-06-15")
    locs = sorted(r.location_id for r in res.records)
    assert locs == ["MW-1", "MW-2"]
    assert all(r.event_date.isoformat() == "2026-06-15" for r in res.records)


def test_dry_nm_ns_excluded_from_contour():
    wls = [_wl("MW-1", 100.0, status="Dry"),
           _wl("MW-2", 100.5, status="NM"),
           _wl("MW-3", 100.2, status="NS"),
           _wl("MW-4", 100.1, status="OK")]
    res = build_gwe_event(wls, event_date="2026-06-15")
    by = {r.location_id: r for r in res.records}
    assert by["MW-1"].use_for_model is False
    assert by["MW-2"].use_for_model is False
    assert by["MW-3"].use_for_model is False
    assert by["MW-4"].use_for_model is True
    assert "Dry" in by["MW-1"].exclusion_reason


def test_anomalous_elevation_flagged_excluded_warns():
    # MW-9 is a gross outlier vs a tight cluster near 100.
    wls = [_wl(f"MW-{i}", 100.0 + i * 0.1) for i in range(6)]
    wls.append(_wl("MW-9", 500.0))
    res = build_gwe_event(wls, event_date="2026-06-15", anomaly_stdev=3.0)
    by = {r.location_id: r for r in res.records}
    assert by["MW-9"].use_for_model is False
    assert "anomal" in by["MW-9"].exclusion_reason.lower()
    assert res.anomalous >= 1
    assert any(rec.category == "anomalous_elevation" for rec in res.qa.records)


def test_explicit_exclude_list():
    wls = [_wl("MW-1", 100.0), _wl("MW-2", 100.1)]
    res = build_gwe_event(wls, event_date="2026-06-15",
                          exclude_locations={"MW-2"})
    by = {r.location_id: r for r in res.records}
    assert by["MW-2"].use_for_model is False
    assert "exclud" in by["MW-2"].exclusion_reason.lower()


def test_perched_well_separate_zone():
    wls = [_wl("MW-1", 100.0), _wl("MW-2", 100.1)]
    res = build_gwe_event(wls, event_date="2026-06-15",
                          perched_locations={"MW-1"})
    by = {r.location_id: r for r in res.records}
    assert by["MW-1"].use_for_model is False
    assert "perched" in by["MW-1"].exclusion_reason.lower()


def test_contour_points_count_matches():
    wls = [_wl("MW-1", 100.0), _wl("MW-2", 100.1, status="Dry"),
           _wl("MW-3", 100.2)]
    res = build_gwe_event(wls, event_date="2026-06-15")
    n_true = sum(1 for r in res.records if r.use_for_model)
    assert res.contour_points == n_true == 2


def test_fields_populated_for_every_record():
    wls = [_wl("MW-1", 100.0)]
    res = build_gwe_event(wls, event_date="2026-06-15")
    r = res.records[0]
    assert r.site_id == "S1"
    assert r.gwe_ft == 100.0
    assert r.dtw_ft == 10.0
    assert r.status == "OK"
    assert r.measured_by == "field"


def test_zero_elevation_is_a_real_datum_not_missing():
    """gwe_ft == 0.0 is a valid elevation; it must still be a contour point (#82 class)."""
    wls = [_wl("MW-1", 0.0), _wl("MW-2", 0.1), _wl("MW-3", -0.1)]
    res = build_gwe_event(wls, event_date="2026-06-15")
    by = {r.location_id: r for r in res.records}
    assert by["MW-1"].gwe_ft == 0.0
    assert by["MW-1"].use_for_model is True


def test_missing_elevation_excluded():
    """A well with no elevation (None) can't contour; excluded, not crashed."""
    wls = [_wl("MW-1", None), _wl("MW-2", 100.0)]
    res = build_gwe_event(wls, event_date="2026-06-15")
    by = {r.location_id: r for r in res.records}
    assert by["MW-1"].use_for_model is False
