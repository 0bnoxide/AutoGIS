"""Tests for autogis/core/envmon/compare_drone_surfaces.py (arcpy-free logic)."""
import pytest

from autogis.core.envmon.compare_drone_surfaces import (
    CHANGE, NO_CHANGE, classify_diff, summarize_diffs, validate_baseline_args,
)


def test_validate_baseline_args_rejects_both():
    with pytest.raises(ValueError, match="exactly one baseline"):
        validate_baseline_args("PROD-1", "surface.xml")


def test_validate_baseline_args_rejects_neither():
    with pytest.raises(ValueError, match="exactly one baseline"):
        validate_baseline_args(None, None)


def test_validate_baseline_args_accepts_product_id():
    validate_baseline_args("PROD-1", None)


def test_validate_baseline_args_accepts_landxml():
    validate_baseline_args(None, "surface.xml")


def test_classify_diff_within_lod_is_no_change():
    assert classify_diff(0.1, lod_threshold_ft=0.2) == NO_CHANGE


def test_classify_diff_beyond_lod_is_change():
    assert classify_diff(0.5, lod_threshold_ft=0.2) == CHANGE
    assert classify_diff(-0.5, lod_threshold_ft=0.2) == CHANGE


def test_classify_diff_at_threshold_boundary_is_no_change():
    assert classify_diff(0.2, lod_threshold_ft=0.2) == NO_CHANGE


def test_summarize_diffs_counts_and_stats():
    summary = summarize_diffs([0.1, 0.5, -0.6, 0.0], lod_threshold_ft=0.2)
    assert summary.count == 4
    assert summary.change_count == 2
    assert summary.no_change_count == 2
    assert summary.max_diff_ft == pytest.approx(0.6)
    assert summary.mean_diff_ft == pytest.approx(0.0)


def test_summarize_diffs_empty_list():
    summary = summarize_diffs([], lod_threshold_ft=0.2)
    assert summary.count == 0
