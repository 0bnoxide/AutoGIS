"""Tests for autogis/core/envmon/compare_drone_surfaces.py (arcpy-free logic)."""
import os

import pytest

from autogis.core.envmon.compare_drone_surfaces import (
    CHANGE, NO_CHANGE, classify_diff, summarize_diffs, validate_baseline_args,
    validate_diff_output, validate_output_not_input,
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


def test_validate_diff_output_rejects_landxml_baseline():
    with pytest.raises(ValueError, match="two DEMs"):
        validate_diff_output("out.tif", "surface.xml")


def test_validate_diff_output_allows_two_dem_mode():
    # diff raster requested, product-ID baseline (no landxml) -> fine
    validate_diff_output("out.tif", None)
    validate_diff_output("out.tif", "")


def test_validate_diff_output_noop_without_output():
    # no diff raster requested -> landxml baseline is unaffected
    validate_diff_output("", "surface.xml")
    validate_diff_output(None, "surface.xml")


def test_validate_output_not_input_rejects_primary():
    with pytest.raises(ValueError, match="input DEM"):
        validate_output_not_input(
            r"C:\gdb.gdb\dem_a", r"C:\gdb.gdb\dem_a", r"C:\gdb.gdb\dem_b")


@pytest.mark.skipif(os.name != "nt",
                    reason="normcase case/sep folding is Windows-only; the "
                           "tool only runs on Windows/arcpy anyway")
def test_validate_output_not_input_rejects_baseline_case_and_sep_insensitive():
    # different casing + forward slashes must still be caught (Windows)
    with pytest.raises(ValueError, match="input DEM"):
        validate_output_not_input(
            "C:/GDB.gdb/DEM_B", r"C:\gdb.gdb\dem_a", r"C:\gdb.gdb\dem_b")


def test_validate_output_not_input_allows_distinct_path():
    validate_output_not_input(
        r"C:\gdb.gdb\CompareDiff", r"C:\gdb.gdb\dem_a", r"C:\gdb.gdb\dem_b")


def test_validate_output_not_input_noop_without_output():
    # no output requested -> nothing to collide
    validate_output_not_input("", r"C:\gdb.gdb\dem_a")
    validate_output_not_input(None, r"C:\gdb.gdb\dem_a")


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
