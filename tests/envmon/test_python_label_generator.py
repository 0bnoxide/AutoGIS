"""Tests for python_label_generator module (Tool 5.4b)."""
import re

from autogis.core.envmon.python_label_generator import (
    build_result_label_expression,
    build_exceedance_callout_expression,
)


def _call_find_label(expr: str, **field_values):
    """Actually execute a generated Python label expression, the way Esri's
    'Python' label-expression engine does: each bracketed [FieldName] token is a
    stand-in for that field's runtime value. Strip the brackets to get a valid
    Python identifier, exec the resulting function, and call it positionally with
    the given field values in the order they first appear (matching FindLabel's
    declared parameter order) -- proving the generated source actually runs, not
    just that it contains the right substrings.
    """
    ordered_params = list(dict.fromkeys(re.findall(r'\[(\w+)\]', expr)))
    src = re.sub(r'\[(\w+)\]', r'\1', expr)
    namespace: dict = {}
    exec(src, namespace)
    args = [field_values[name] for name in ordered_params]
    return namespace["FindLabel"](*args)


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


def test_result_expression_executes_for_clean_numeric():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="1234.5", ReportedUnits="ug/L")
    assert result == "1,234.50 ug/L"


def test_result_expression_executes_for_nd():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="ND", ReportedUnits="ug/L")
    assert result == "ND"


def test_result_expression_does_not_raise_for_qualified_value():
    """Real result fields commonly carry qualifiers (e.g. '0.5 J', '<0.5').
    float() would raise ValueError on these -- FindLabel must not propagate that,
    or Pro silently drops the label for that feature."""
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="0.5 J", ReportedUnits="ug/L")
    assert result == "0.5 J ug/L"


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


def test_exceedance_expression_executes_when_exceeding():
    expr = build_exceedance_callout_expression("ResultValue", "ScreeningLevel", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="10", ScreeningLevel="5", ReportedUnits="ug/L")
    assert result == "10.00 ug/L**"


def test_exceedance_expression_executes_when_not_exceeding():
    expr = build_exceedance_callout_expression("ResultValue", "ScreeningLevel", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="3", ScreeningLevel="5", ReportedUnits="ug/L")
    assert result == "3.00 ug/L"


def test_exceedance_expression_does_not_raise_for_missing_sl():
    expr = build_exceedance_callout_expression("ResultValue", "ScreeningLevel", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="10", ScreeningLevel="", ReportedUnits="ug/L")
    assert result == "10.00 ug/L"


def test_exceedance_expression_does_not_raise_for_qualified_value():
    expr = build_exceedance_callout_expression("ResultValue", "ScreeningLevel", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="0.5 J", ScreeningLevel="5", ReportedUnits="ug/L")
    assert result == "0.5 J ug/L"


def test_exceedance_expression_does_not_raise_for_qualified_sl():
    expr = build_exceedance_callout_expression("ResultValue", "ScreeningLevel", "ReportedUnits")
    result = _call_find_label(expr, ResultValue="10", ScreeningLevel="TR", ReportedUnits="ug/L")
    assert result == "10.00 ug/L"


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


# ---------------------------------------------------------------------------
# write_label_expressions
# ---------------------------------------------------------------------------
import json

from autogis.core.envmon.python_label_generator import write_label_expressions


def test_write_produces_json_file(tmp_path):
    specs = generate_python_labels(["Benzene", "Toluene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    assert out.exists()


def test_written_json_is_parseable(tmp_path):
    specs = generate_python_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_written_json_has_expected_keys(tmp_path):
    specs = generate_python_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) > 0
    entry = data[0]
    assert "layer_name" in entry
    assert "expression_type" in entry
    assert "python_expression" in entry
    assert "expression_engine" in entry


def test_written_json_expression_engine_is_python(tmp_path):
    specs = generate_python_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for entry in data:
        assert entry["expression_engine"] == "Python"


def test_written_json_python_expression_is_string(tmp_path):
    specs = generate_python_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for entry in data:
        assert isinstance(entry["python_expression"], str)
        assert len(entry["python_expression"]) > 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def test_generate_python_labels_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as autogis_cli
    result = CliRunner().invoke(autogis_cli, ["envmon", "--help"])
    assert "generate-python-labels" in result.output


def test_generate_python_labels_cli_writes_file(tmp_path):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as autogis_cli
    out = tmp_path / "labels.json"
    result = CliRunner().invoke(
        autogis_cli,
        ["envmon", "generate-python-labels", "--analytes", "Benzene,PCE", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
