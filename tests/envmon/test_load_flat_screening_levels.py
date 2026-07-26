"""Regression tests for issue #341: --screening-levels silently resolved
None against the shipped matrix-nested screening_levels.yaml, or raised a
raw TypeError instead of a clean error."""
from __future__ import annotations

from pathlib import Path

import pytest

from autogis.core.common.config import ConfigError, load_flat_screening_levels

CONFIG = Path(__file__).resolve().parent.parent.parent / "autogis" / "config"


def test_flat_legacy_shape_passes_through(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text("Benzene: 5\nToluene: 1000\n", encoding="utf-8")
    assert load_flat_screening_levels(p) == {"Benzene": 5.0, "Toluene": 1000.0}


def test_flat_shape_drops_null_values(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text("Benzene: 5\nTPH: null\n", encoding="utf-8")
    assert load_flat_screening_levels(p) == {"Benzene": 5.0}


def test_matrix_nested_shape_flattens(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text(
        "screening_levels:\n"
        "  GW:\n"
        "    Benzene: {value: 5, units: ug/L, source: x}\n"
        "  SOIL:\n"
        "    Arsenic: {value: null, units: mg/kg, source: x}\n",
        encoding="utf-8",
    )
    assert load_flat_screening_levels(p) == {"Benzene": 5.0}


def test_matrix_nested_conflicting_values_raises(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text(
        "screening_levels:\n"
        "  GW:\n"
        "    Benzene: {value: 5, units: ug/L, source: x}\n"
        "  SOIL:\n"
        "    Benzene: {value: 12, units: mg/kg, source: y}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="conflicting screening levels"):
        load_flat_screening_levels(p)


def test_matrix_nested_agreeing_values_do_not_raise(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text(
        "screening_levels:\n"
        "  GW:\n"
        "    Benzene: {value: 5, units: ug/L, source: x}\n"
        "  SOIL:\n"
        "    Benzene: {value: 5, units: mg/kg, source: y}\n",
        encoding="utf-8",
    )
    assert load_flat_screening_levels(p) == {"Benzene": 5.0}


def test_empty_file_raises_config_error(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_flat_screening_levels(p)


def test_shipped_screening_levels_yaml_resolves_real_values():
    """The exact harm in #341: the shipped file must resolve non-None,
    non-empty screening levels, not silently vanish."""
    sl = load_flat_screening_levels(
        CONFIG / "screening_levels" / "screening_levels.yaml")
    assert sl, "shipped screening_levels.yaml flattened to an empty mapping"
    assert sl.get("Benzene") == 5.0


def test_shipped_screening_levels_feed_build_max_result_dataset():
    from autogis.core.envmon.max_result_dataset import build_max_result_dataset

    sl = load_flat_screening_levels(
        CONFIG / "screening_levels" / "screening_levels.yaml")
    rows = [{"LocationID": "MW-01", "AnalyteName": "Benzene",
             "ResultValue": "50", "ResultQualifier": "", "ReportedUnits": "ug/L",
             "SampleDate": "2026-01-01", "SampleID": "S1"}]
    records = build_max_result_dataset(rows, screening_levels=sl)
    assert len(records) == 1
    assert records[0].screening_level == 5.0
    assert records[0].has_exceedance is True


def test_shipped_screening_levels_feed_build_exceedance_event():
    from autogis.core.envmon.build_exceedance_event import build_exceedance_event

    sl = load_flat_screening_levels(
        CONFIG / "screening_levels" / "screening_levels.yaml")
    rows = [{"LocationID": "MW-01", "AnalyteName": "Benzene",
             "ResultValue": "50", "ResultQualifier": "", "ReportedUnits": "ug/L",
             "SampleDate": "2026-01-01", "SampleID": "S1"}]
    records = build_exceedance_event(rows, sl)
    assert len(records) == 1
    assert records[0].screening_level == 5.0
    assert records[0].has_exceedance is True
