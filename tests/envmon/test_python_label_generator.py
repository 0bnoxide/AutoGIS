"""Tests for python_label_generator module (Tool 5.4b)."""
from autogis.core.envmon.python_label_generator import (
    build_result_label_expression,
    build_exceedance_callout_expression,
)


# ---------------------------------------------------------------------------
# build_result_label_expression
# ---------------------------------------------------------------------------

def test_result_expression_contains_findlabel_def():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "def FindLabel" in expr


def test_result_expression_contains_value_field_bracket_token():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "[ResultValue]" in expr


def test_result_expression_contains_units_field_bracket_token():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "[ReportedUnits]" in expr


def test_result_expression_contains_nd_branch():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ND" in expr


def test_result_expression_custom_nd_text():
    expr = build_result_label_expression("Val", "Units", nd_text="<MDL")
    assert "<MDL" in expr


def test_result_expression_is_string():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert isinstance(expr, str)
    assert len(expr) > 0


# ---------------------------------------------------------------------------
# build_exceedance_callout_expression
# ---------------------------------------------------------------------------

def test_exceedance_expression_contains_findlabel_def():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "def FindLabel" in expr


def test_exceedance_expression_contains_double_asterisk():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "**" in expr


def test_exceedance_expression_contains_value_field_bracket_token():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "[ResultValue]" in expr


def test_exceedance_expression_contains_sl_field_bracket_token():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "[ScreeningLevel]" in expr


def test_exceedance_expression_is_string():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert isinstance(expr, str)
    assert len(expr) > 0
