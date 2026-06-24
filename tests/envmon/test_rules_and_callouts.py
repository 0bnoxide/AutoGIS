"""Inspector, current-event rule engine, and callout geometry/collision."""

import pytest

from autogis.core.envmon.excel_workbook_inspector import (inspect_workbook_structure,
                                      propose_parser_profile)
from autogis.core.envmon.build_current_event import (apply_depth_rule, apply_duplicate_rule,
                                 build_wide_rows, sanitize_field_name,
                                 select_samples)
from autogis.core.envmon.callout_templates import build_callout_rows
from autogis.core.envmon.callout_geometry import (build_callout_geometry, compute_box_size,
                              map_units_per_point)
from autogis.core.envmon.callout_collision import (CalloutRequest, detect_callout_collisions,
                               place_callouts, PM_AUTO_COLLISION_WARNING,
                               PM_AUTO_NO_COLLISION, PM_OVERRIDE_LOCKED)
from autogis.core.common.config import FigureSpec


# ---------------------------------------------------------------- inspector
def test_inspector_profiles_every_sheet(workbook, qa):
    report = inspect_workbook_structure(workbook, qa)
    assert set(report["sheets"]) == {"GW Table 2", "Table 3", "Metals Table",
                                     "RPD"}
    gw = report["sheets"]["GW Table 2"]
    assert gw["merged_ranges"], "merged group header must be reported"
    draft = propose_parser_profile(report, "DRAFT_TEST")
    assert draft["profile_id"] == "DRAFT_TEST"
    assert all("_TODO" in s for s in draft["sheets"]), \
        "draft profiles must demand human review"


def test_propose_parser_profile_guesses_analyte_columns(workbook, qa):
    report = inspect_workbook_structure(workbook, qa)
    draft = propose_parser_profile(report, "DRAFT_TEST")
    for sheet in draft["sheets"]:
        cols = sheet["analyte_columns"]
        assert cols is not None, (
            f"sheet {sheet['sheet_name']!r}: analyte_columns should be a "
            f"heuristic guess, not None"
        )
        assert "from" in cols and "to" in cols, (
            f"analyte_columns must be a {{from, to}} dict, got {cols!r}"
        )
        assert cols["from"] <= cols["to"], (
            f"from column must not be after to column: {cols!r}"
        )


# ---------------------------------------------------------------- rules
def _row(loc, sid, dt, an, num, det=True, exc=False, dup=False,
         parent="", depth="", dtop=None):
    return {"LocationID": loc, "SampleID": sid, "SampleDate": dt,
            "AnalyteCanonicalName": an, "NumericValue": num,
            "IsDetected": det, "IsNonDetect": not det,
            "ExceedsScreening": exc, "IsFieldDuplicate": dup,
            "ParentSampleID": parent, "DepthIntervalText": depth,
            "DepthTopFt": dtop, "DisplayText": str(num) if num else "<1.0",
            "Units": "ug/L", "DisplayColorClass": "DETECTED",
            "ScreeningLevelValue": 5.0, "Matrix": "GW"}


def test_select_latest_per_location(qa):
    rows = [_row("MW-1", "S1", "2026-01-15", "Benzene", 1.0),
            _row("MW-1", "S2", "2026-04-15", "Benzene", 2.0),
            _row("MW-2", "S3", "2026-04-15", "Benzene", 3.0)]
    out = select_samples(rows, "latest_per_location", qa)
    assert {(r["LocationID"], r["SampleID"]) for r in out} == \
        {("MW-1", "S2"), ("MW-2", "S3")}


def test_select_max_detected_falls_back_with_qa(qa):
    rows = [_row("MW-1", "S1", "2026-01-15", "Benzene", None, det=False),
            _row("MW-1", "S2", "2026-04-15", "Benzene", None, det=False)]
    out = select_samples(rows, "max_detected_per_location", qa)
    assert len(out) == 1 and out[0]["SampleID"] == "S2"
    assert any(r.category == "max_rule_no_candidates" for r in qa.records)


def test_duplicate_prefer_parent(qa):
    rows = [_row("MW-1", "S1", "2026-04-15", "Benzene", 2.0),
            _row("MW-1", "S1-DUP", "2026-04-15", "Benzene", 2.4, dup=True,
                 parent="S1")]
    out = apply_duplicate_rule(rows, "prefer_parent", qa)
    assert [r["SampleID"] for r in out] == ["S1"]


def test_duplicate_average_detect_pair_warns(qa):
    rows = [_row("MW-1", "S1", "2026-04-15", "Benzene", 2.0),
            _row("MW-1", "S1-DUP", "2026-04-15", "Benzene", 4.0, dup=True,
                 parent="S1")]
    out = apply_duplicate_rule(rows, "average_parent_and_duplicate", qa)
    assert out[0]["NumericValue"] == pytest.approx(3.0)
    assert any(r.category == "averaged_parent_duplicate"
               and r.severity == "WARNING" for r in qa.records)


def test_duplicate_average_nondetect_pair_uses_parent(qa):
    rows = [_row("MW-1", "S1", "2026-04-15", "Benzene", None, det=False),
            _row("MW-1", "S1-DUP", "2026-04-15", "Benzene", 4.0, dup=True,
                 parent="S1")]
    out = apply_duplicate_rule(rows, "average_parent_and_duplicate", qa)
    assert out[0]["SampleID"] == "S1"
    assert out[0]["NumericValue"] is None
    assert any(r.category == "average_rule_nondetect_pair"
               for r in qa.records)


def test_depth_rules(qa):
    rows = [_row("SB-1", "A", "2026-04-15", "Benzene", 1.0, depth="0-2",
                 dtop=0.0),
            _row("SB-1", "B", "2026-04-15", "Benzene", 9.0, depth="4-6",
                 dtop=4.0)]
    assert len(apply_depth_rule(rows, "all_depths", qa)) == 2
    sh = apply_depth_rule(rows, "shallowest", qa)
    assert [r["DepthIntervalText"] for r in sh] == ["0-2"]
    dp = apply_depth_rule(rows, "deepest", qa)
    assert [r["DepthIntervalText"] for r in dp] == ["4-6"]
    mx = apply_depth_rule(rows, "max_per_analyte", qa)
    assert mx[0]["NumericValue"] == 9.0


def test_build_wide_rows_flags(qa, adict):
    rows = [_row("MW-5", "S5", "2026-04-15", "Benzene", 6.4, exc=True),
            _row("MW-5", "S5", "2026-04-15", "TPH", 120.0),
            _row("MW-2", "S2", "2026-04-15", "Benzene", None, det=False)]
    wide = build_wide_rows(rows, ["Benzene", "TPH"], qa)
    by = {w["LocationID"]: w for w in wide}
    assert by["MW-5"]["HasExceedance"] and by["MW-5"]["HasDetection"]
    assert by["MW-2"]["HasOnlyNonDetects"]
    assert by["MW-2"]["HasMissingRequiredAnalytes"]   # TPH absent
    assert "MW-5" in by["MW-5"]["LabelText_Fallback"]


def test_sanitize_field_name_unique_and_safe():
    used = set()
    a = sanitize_field_name("C5-C8 Aliphatics", used)
    b = sanitize_field_name("C5 C8 Aliphatics", used)
    c = sanitize_field_name("1,2-DCA", used)
    assert a != b
    assert all(s[0].isalpha() or s[0] == "_" for s in (a, b, c))
    assert all(ch.isalnum() or ch == "_" for s in (a, b, c) for ch in s)


# ------------------------------------------------------ geometry/collision
SPEC = FigureSpec(data={
    "figure_spec_id": "T", "callout_template": {"template_id": "CKG_GW"},
    "analytes": ["Benzene", "TPH"],
})


def _record(loc):
    return {"LocationID": loc, "SampleID": loc + "-S",
            "SampleDate": "2026-04-15", "DepthIntervalText": "",
            "results": {
                "Benzene": {"DisplayText": "6.4", "DisplayColorClass":
                            "EXCEEDANCE", "IsDetected": True},
                "TPH": {"DisplayText": "<50", "DisplayColorClass":
                        "NONDETECT", "IsDetected": False}}}


def test_ckg_table_structure(adict):
    t = build_callout_rows(_record("MW-5"), SPEC, adict, ["Benzene", "TPH"])
    assert t.n_rows == 3                      # title + 2 analytes
    assert t.cells[0].text == "MW-5"
    texts = [c.text for c in t.cells]
    assert "6.4" in texts and "<50" in texts


def test_box_size_and_geometry(adict):
    t = build_callout_rows(_record("MW-5"), SPEC, adict, ["Benzene", "TPH"])
    w, h, _, _ = compute_box_size(t, 1200, "feet", 6)
    assert w > 0 and h > 0
    g = build_callout_geometry(t, 1200, "feet", 6, origin=(100.0, 200.0))
    assert g.origin == (100.0, 200.0)
    assert len(g.box_corners) == 5            # closed ring
    assert g.gridlines and g.cell_anchors
    assert map_units_per_point(1200, "feet") == pytest.approx(1200 / 72 / 12)


def _req(cid, pt, w=20.0, h=10.0, **kw):
    return CalloutRequest(callout_id=cid, location_id=cid, source_point=pt,
                          box_width=w, box_height=h, **kw)


def test_collision_detected_and_resolved():
    # Two far-apart points: no collision
    far = place_callouts([_req("A", (0, 0)), _req("B", (500, 500))],
                         None, 2.0, 5.0)
    assert all(p.placement_method == PM_AUTO_NO_COLLISION for p in far)
    # Same point: engine must separate them via quadrants
    near = place_callouts([_req("A", (0, 0)), _req("B", (0, 0))],
                          None, 2.0, 5.0)
    rects = {p.callout_id: (p.origin[0], p.origin[1],
                            p.origin[0] + 20, p.origin[1] + 10)
             for p in near}
    a, b = rects["A"], rects["B"]
    overlap = not (a[2] <= b[0] or b[2] <= a[0] or
                   a[3] <= b[1] or b[3] <= a[1])
    assert not overlap, "engine left two callouts overlapping"


def test_locked_override_is_never_moved():
    res = place_callouts(
        [_req("A", (0, 0), override_origin=(1.0, 1.0), locked=True),
         _req("B", (0, 0))], None, 2.0, 5.0)
    a = next(p for p in res if p.callout_id == "A")
    assert a.origin == (1.0, 1.0)
    assert a.placement_method == PM_OVERRIDE_LOCKED


def test_all_candidates_collide_warns_not_drops():
    # Ten callouts on one point inside a tiny extent: somebody must end up
    # flagged, but every callout must still be placed.
    reqs = [_req(f"C{i}", (0, 0)) for i in range(10)]
    res = place_callouts(reqs, (-30, -15, 30, 15), 2.0, 5.0)
    assert len(res) == len(reqs)              # never drop a callout
    assert any(p.placement_method == PM_AUTO_COLLISION_WARNING for p in res)


def test_collision_detection_function():
    from autogis.core.envmon.callout_collision import PlacementResult
    placed = [
        PlacementResult(callout_id=k, location_id=k, origin=(x0, y0),
                        rect=(x0, y0, x1, y1), quadrant="NE",
                        placement_method=PM_AUTO_NO_COLLISION,
                        collision_score=0.0, collided_with=[])
        for k, (x0, y0, x1, y1) in
        {"A": (0, 0, 10, 10), "B": (5, 5, 15, 15),
         "C": (50, 50, 60, 60)}.items()]
    reports = detect_callout_collisions(placed, point_buffers={})
    ids = {(r.a_id, r.b_id) for r in reports if r.b_kind == "CALLOUT"}
    assert ("A", "B") in ids or ("B", "A") in ids
    assert not any("C" in pair for pair in ids)
    # point-buffer overlap is also reported
    reports2 = detect_callout_collisions(
        placed, point_buffers={"P1": (8, 8, 12, 12)})
    assert any(r.b_kind == "POINT_BUFFER" for r in reports2)


# ------------------------------------------------- assemble integration
def test_assemble_callouts_with_override_and_missing_point(qa, adict):
    from autogis.core.envmon.build_figure_dataset import assemble_callouts
    wide = [
        {"LocationID": "MW-1", "SampleID": "S1", "SampleDate": "2026-04-15",
         "DepthIntervalText": "", "results": _record("MW-1")["results"]},
        {"LocationID": "MW-2", "SampleID": "S2", "SampleDate": "2026-04-15",
         "DepthIntervalText": "", "results": _record("MW-2")["results"]},
        {"LocationID": "MW-9", "SampleID": "S9", "SampleDate": "2026-04-15",
         "DepthIntervalText": "", "results": _record("MW-9")["results"]},
    ]
    pts = {"MW-1": (100.0, 100.0), "MW-2": (105.0, 100.0)}  # MW-9 missing
    overrides = {"MW-1": {"origin": (300.0, 300.0), "locked": True,
                          "preferred_quadrant": None}}
    spec = FigureSpec(data={
        "figure_spec_id": "T2", "reference_scale": 1200,
        "callout_template": {"template_id": "CKG_GW",
                             "base_font_points": 6},
        "analytes": ["Benzene", "TPH"]})
    out = assemble_callouts(wide, pts, spec, adict, qa,
                            extent=None, map_units="feet",
                            overrides=overrides)
    # MW-9 dropped WITH a QA error, never silently
    assert {c["location_id"] for c in out} == {"MW-1", "MW-2"}
    assert any(r.category == "callout_location_missing_point"
               and r.severity == "ERROR" for r in qa.records)
    mw1 = next(c for c in out if c["location_id"] == "MW-1")
    assert mw1["placement"].origin == (300.0, 300.0)
    assert mw1["placement"].placement_method == PM_OVERRIDE_LOCKED
    # every callout has a leader from its source point
    for c in out:
        assert c["geometry"].leader is not None
