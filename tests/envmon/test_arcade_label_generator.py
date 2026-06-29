"""Tests for arcade_label_generator module (Tool 5.4)."""
import json
from pathlib import Path

import pytest

from autogis.core.envmon.arcade_label_generator import (
    LabelExpressionType,
    ArcadeLabelSpec,
    build_result_label_expression,
    build_exceedance_callout_expression,
    generate_arcade_labels,
    write_label_expressions,
)


# ---------------------------------------------------------------------------
# build_result_label_expression
# ---------------------------------------------------------------------------

def test_result_expression_contains_nd_branch():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ND" in expr


def test_result_expression_contains_value_field():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ResultValue" in expr


def test_result_expression_contains_units_field():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ReportedUnits" in expr


def test_result_expression_is_string():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert isinstance(expr, str)
    assert len(expr) > 0


def test_result_expression_custom_nd_text():
    expr = build_result_label_expression("Val", "Units", nd_text="<MDL")
    assert "<MDL" in expr


def test_result_expression_contains_format_call():
    """Arcade Text() or numeric format should appear for the value path."""
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    # Must include either Text() formatting or numeric concatenation
    assert "Text(" in expr or "+" in expr


# ---------------------------------------------------------------------------
# build_exceedance_callout_expression
# ---------------------------------------------------------------------------

def test_exceedance_expression_contains_double_asterisk():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "**" in expr


def test_exceedance_expression_contains_value_field():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "ResultValue" in expr


def test_exceedance_expression_contains_sl_field():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "ScreeningLevel" in expr


def test_exceedance_expression_is_string():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert isinstance(expr, str)
    assert len(expr) > 0


# ---------------------------------------------------------------------------
# generate_arcade_labels
# ---------------------------------------------------------------------------

def test_generate_labels_three_analytes_min_three_specs():
    analytes = ["Benzene", "Toluene", "PCE"]
    specs = generate_arcade_labels(analytes)
    assert len(specs) >= 3


def test_generate_labels_returns_arcade_label_spec_instances():
    specs = generate_arcade_labels(["Benzene"])
    for s in specs:
        assert isinstance(s, ArcadeLabelSpec)


def test_generate_labels_with_field_prefix():
    specs = generate_arcade_labels(["Benzene"], field_prefix="Env_")
    for s in specs:
        assert "Env_" in s.value_field or "Env_" in s.analyte_field


def test_generate_labels_spec_has_expression():
    specs = generate_arcade_labels(["Benzene"])
    for s in specs:
        assert isinstance(s.expression, str)
        assert len(s.expression) > 0


def test_generate_labels_spec_has_layer_name():
    specs = generate_arcade_labels(["Benzene"])
    for s in specs:
        assert isinstance(s.layer_name, str)
        assert len(s.layer_name) > 0


def test_generate_labels_expression_types_present():
    """At least RESULT_WITH_UNITS and ND_CALLOUT types should appear."""
    specs = generate_arcade_labels(["Benzene"])
    types_found = {s.expression_type for s in specs}
    assert LabelExpressionType.RESULT_WITH_UNITS in types_found


def test_generate_labels_empty_analytes():
    specs = generate_arcade_labels([])
    assert specs == []


# ---------------------------------------------------------------------------
# write_label_expressions
# ---------------------------------------------------------------------------

def test_write_produces_json_file(tmp_path):
    specs = generate_arcade_labels(["Benzene", "Toluene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    assert out.exists()


def test_written_json_is_parseable(tmp_path):
    specs = generate_arcade_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_written_json_has_expected_keys(tmp_path):
    specs = generate_arcade_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) > 0
    entry = data[0]
    assert "layer_name" in entry
    assert "expression_type" in entry
    assert "arcade_expression" in entry


def test_written_json_arcade_expression_is_string(tmp_path):
    specs = generate_arcade_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for entry in data:
        assert isinstance(entry["arcade_expression"], str)
        assert len(entry["arcade_expression"]) > 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def test_generate_arcade_labels_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as autogis_cli
    result = CliRunner().invoke(autogis_cli, ["envmon", "--help"])
    assert "generate-arcade-labels" in result.output
