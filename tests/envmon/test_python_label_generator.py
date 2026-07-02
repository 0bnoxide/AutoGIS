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


# ---------------------------------------------------------------------------
# generate_python_labels
# ---------------------------------------------------------------------------
from autogis.core.envmon.python_label_generator import (
    PythonLabelSpec,
    LabelExpressionType,
    generate_python_labels,
)


def test_generate_labels_three_analytes_min_three_specs():
    analytes = ["Benzene", "Toluene", "PCE"]
    specs = generate_python_labels(analytes)
    assert len(specs) >= 3


def test_generate_labels_returns_python_label_spec_instances():
    specs = generate_python_labels(["Benzene"])
    for s in specs:
        assert isinstance(s, PythonLabelSpec)


def test_generate_labels_with_field_prefix():
    specs = generate_python_labels(["Benzene"], field_prefix="Env_")
    for s in specs:
        assert "Env_" in s.value_field or "Env_" in s.analyte_field


def test_generate_labels_spec_has_expression():
    specs = generate_python_labels(["Benzene"])
    for s in specs:
        assert isinstance(s.expression, str)
        assert len(s.expression) > 0


def test_generate_labels_spec_has_layer_name():
    specs = generate_python_labels(["Benzene"])
    for s in specs:
        assert isinstance(s.layer_name, str)
        assert len(s.layer_name) > 0


def test_generate_labels_expression_types_present():
    specs = generate_python_labels(["Benzene"])
    types_found = {s.expression_type for s in specs}
    assert LabelExpressionType.RESULT_WITH_UNITS in types_found


def test_generate_labels_empty_analytes():
    specs = generate_python_labels([])
    assert specs == []


def test_generate_labels_field_names_match_arcade_generator():
    """The shared derive_label_fields helper must keep both generators in sync."""
    from autogis.core.envmon.arcade_label_generator import generate_arcade_labels

    arcade_specs = generate_arcade_labels(["Benzene"], field_prefix="Env_")
    python_specs = generate_python_labels(["Benzene"], field_prefix="Env_")

    arcade_result = next(s for s in arcade_specs if s.expression_type == LabelExpressionType.RESULT_WITH_UNITS)
    python_result = next(s for s in python_specs if s.expression_type == LabelExpressionType.RESULT_WITH_UNITS)

    assert arcade_result.value_field == python_result.value_field
    assert arcade_result.units_field == python_result.units_field
    assert arcade_result.analyte_field == python_result.analyte_field
