"""Unit tests for soil_interval_selector (Tool 4.8)."""
import pytest

from autogis.core.envmon.soil_interval_selector import select_intervals


def _row(loc, analyte, top, bottom, result, screening=None,
         confirmation=False):
    return {"location_id": loc, "analyte": analyte, "depth_top": top,
            "depth_bottom": bottom, "result_value": result,
            "screening_level": screening, "is_confirmation": confirmation}


def test_shallowest_keeps_min_top_per_location():
    rows = [_row("B-1", "Pb", 8, 10, 5), _row("B-1", "Pb", 2, 4, 9)]
    res = select_intervals(rows, rule="shallowest")
    assert len(res.selected) == 1
    assert res.selected[0].depth_top == 2


def test_deepest_keeps_max_bottom_per_location():
    rows = [_row("B-1", "Pb", 8, 10, 5), _row("B-1", "Pb", 2, 4, 9)]
    res = select_intervals(rows, rule="deepest")
    assert len(res.selected) == 1
    assert res.selected[0].depth_bottom == 10


def test_highest_result_per_location_analyte():
    rows = [_row("B-1", "Pb", 2, 4, 5), _row("B-1", "Pb", 8, 10, 12),
            _row("B-1", "As", 2, 4, 3)]
    res = select_intervals(rows, rule="highest_result")
    keep = {(s.location_id, s.analyte, s.result_value) for s in res.selected}
    assert ("B-1", "Pb", 12.0) in keep
    assert ("B-1", "As", 3.0) in keep
    assert ("B-1", "Pb", 5.0) not in keep


def test_highest_exceedance_ranks_by_ratio_not_raw():
    # Pb: 10 vs screening 100 -> ratio 0.1; As: 5 vs screening 1 -> ratio 5.
    rows = [_row("B-1", "Pb", 2, 4, 10, screening=100),
            _row("B-1", "As", 2, 4, 5, screening=1)]
    res = select_intervals(rows, rule="highest_exceedance")
    assert len(res.selected) == 1
    assert res.selected[0].analyte == "As"   # higher ratio, lower raw value


def test_interval_list_keeps_only_windowed_rows():
    rows = [_row("B-1", "Pb", 2, 4, 5), _row("B-1", "Pb", 8, 10, 5)]
    res = select_intervals(rows, rule="interval_list",
                           interval_list=[(2.0, 4.0)])
    assert len(res.selected) == 1
    assert res.selected[0].depth_top == 2


def test_confirmation_only_keeps_flagged_rows():
    rows = [_row("B-1", "Pb", 2, 4, 5, confirmation=True),
            _row("B-1", "Pb", 8, 10, 5, confirmation=False)]
    res = select_intervals(rows, rule="confirmation_only")
    assert len(res.selected) == 1
    assert res.selected[0].depth_top == 2


def test_rule_recorded_and_no_qualifying_interval_warns():
    rows = [_row("B-1", "Pb", 2, 4, 10)]  # no screening -> no ratio
    res = select_intervals(rows, rule="highest_exceedance")
    assert res.selected == [] or all(
        s.selection_rule == "highest_exceedance" for s in res.selected)
    assert any(r.category == "no_qualifying_interval" for r in res.qa.records)


def test_zero_screening_level_is_real_threshold():
    """screening 0.0 with a positive result is a max-ratio exceedance (#82 class)."""
    rows = [_row("B-1", "Pb", 2, 4, 10, screening=0.0),
            _row("B-1", "As", 2, 4, 9, screening=1.0)]
    res = select_intervals(rows, rule="highest_exceedance")
    assert len(res.selected) == 1
    assert res.selected[0].analyte == "Pb"   # ratio inf > 9
    assert res.selected[0].exceeds is True


def test_blank_location_id_skipped_with_warning():
    """Blank location_id must not collapse unrelated borings into one '' group."""
    rows = [_row("", "Pb", 2, 4, 5), _row("B-1", "Pb", 2, 4, 9),
            _row("B-1", "Pb", 8, 10, 3)]
    res = select_intervals(rows, rule="shallowest")
    assert all(s.location_id == "B-1" for s in res.selected)
    assert any(r.category == "blank_location_id" for r in res.qa.records)


def test_missing_depth_warns():
    rows = [_row("B-1", "Pb", None, None, 5)]
    res = select_intervals(rows, rule="all")
    assert any(r.category == "missing_depth" for r in res.qa.records)


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        select_intervals([], rule="bogus")
