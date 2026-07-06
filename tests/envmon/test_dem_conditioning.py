"""Tests for autogis/core/envmon/dem_conditioning.py (arcpy-free logic only)."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.dem_conditioning import (
    DEMConditioningConfig, build_config, products_to_generate, validate_config,
)


def test_build_config_defaults_are_all_off():
    config = build_config()
    assert config == DEMConditioningConfig(
        fill_voids=False, fill_voids_max_pixels=9, smooth=None,
        with_slope=False, with_contours=False)


def test_build_config_bare_fill_voids_defaults_to_9px():
    config = build_config(fill_voids=9)
    assert config.fill_voids is True
    assert config.fill_voids_max_pixels == 9


def test_build_config_explicit_fill_voids_value():
    config = build_config(fill_voids=25)
    assert config.fill_voids is True
    assert config.fill_voids_max_pixels == 25


def test_build_config_smooth_and_opt_ins():
    config = build_config(smooth="gaussian", with_slope=True, with_contours=True)
    assert config.smooth == "gaussian"
    assert config.with_slope is True
    assert config.with_contours is True


def test_products_to_generate_always_includes_dem_and_hillshade():
    assert products_to_generate(DEMConditioningConfig()) == [
        "conditioned_dem", "hillshade"]


def test_products_to_generate_opt_ins_appended_in_order():
    config = DEMConditioningConfig(with_slope=True, with_contours=True)
    assert products_to_generate(config) == [
        "conditioned_dem", "hillshade", "slope", "contours"]


def test_validate_config_rejects_non_positive_fill_voids_max_pixels():
    qa = QACollector()
    validate_config(DEMConditioningConfig(fill_voids=True, fill_voids_max_pixels=0), qa)
    assert any(r.category == "invalid_fill_voids_max_pixels" for r in qa.records)


def test_validate_config_rejects_unknown_smooth_method():
    qa = QACollector()
    validate_config(DEMConditioningConfig(smooth="bogus"), qa)
    assert any(r.category == "invalid_smooth_method" for r in qa.records)


def test_validate_config_accepts_defaults():
    qa = QACollector()
    validate_config(DEMConditioningConfig(), qa)
    assert qa.records == []
