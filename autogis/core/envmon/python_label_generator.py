"""python_label_generator.py — Python label expression generator (Tool 5.4b).

Generates Esri "Python" label-expression source (`def FindLabel(...): ...`,
bracketed [FieldName] references) for ArcGIS Pro layers whose label class uses the
'Python' expressionEngine instead of Arcade. Mirrors arcade_label_generator.py's
expression-type taxonomy and JSON shape so the two tools stay interchangeable for a
given layer.

No arcpy dependency. stdlib + dataclasses only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autogis.core.envmon.label_expression_common import (
    LabelExpressionType, derive_label_fields,
)

EXPRESSION_ENGINE = "Python"


@dataclass
class PythonLabelSpec:
    """One Python label expression for a single analyte + expression type."""

    layer_name: str
    expression_type: str
    analyte_field: str
    value_field: str
    units_field: str
    sl_field: Optional[str]
    expression: str


# ---------------------------------------------------------------------------
# Expression builders
# ---------------------------------------------------------------------------

def build_result_label_expression(
    value_field: str,
    units_field: str,
    *,
    nd_text: str = "ND",
) -> str:
    """Return Esri Python label-expression source for a result value with units.

    Arcade's Text()/Number() never raise on non-numeric input (Number() yields NaN
    instead) — a Python FindLabel that lets float() raise on a qualified value like
    "0.5 J" or "<0.5" would instead leave that feature unlabeled in Pro. The
    try/except mirrors Arcade's leniency: fall back to the raw value if it isn't
    cleanly numeric, instead of crashing FindLabel.

    Example output (Python label-expression code, run via Pro's 'Python' engine):
        def FindLabel ( [ResultValue], [ReportedUnits] ):
            v = [ResultValue]
            if v is None or v == "" or v == "ND":
                return "ND"
            try:
                return "{:,.2f} {}".format(float(v), [ReportedUnits])
            except (TypeError, ValueError):
                return "{} {}".format(v, [ReportedUnits])
    """
    return (
        f'def FindLabel ( [{value_field}], [{units_field}] ):\n'
        f'    v = [{value_field}]\n'
        f'    if v is None or v == "" or v == "{nd_text}":\n'
        f'        return "{nd_text}"\n'
        f'    try:\n'
        f'        return "{{:,.2f}} {{}}".format(float(v), [{units_field}])\n'
        f'    except (TypeError, ValueError):\n'
        f'        return "{{}} {{}}".format(v, [{units_field}])'
    )


def build_exceedance_callout_expression(
    value_field: str,
    sl_field: str,
    units_field: str,
    *,
    nd_text: str = "ND",
    exceed_suffix: str = "**",
) -> str:
    """Return Esri Python label-expression source that appends '**' when the result
    exceeds the screening level.

    Same non-throwing rationale as build_result_label_expression: Arcade's Number()
    never raises (it yields NaN), so this falls back to the raw value if it isn't
    cleanly numeric rather than letting float() crash FindLabel and blank the label.
    A non-numeric/missing screening level just disables the exceedance check.

    Example output (Python label-expression code):
        def FindLabel ( [ResultValue], [ScreeningLevel], [ReportedUnits] ):
            v = [ResultValue]
            sl = [ScreeningLevel]
            if v is None or v == "" or v == "ND":
                return "ND"
            try:
                num = float(v)
            except (TypeError, ValueError):
                return "{} {}".format(v, [ReportedUnits])
            try:
                exceeds = sl not in (None, "") and num > float(sl)
            except (TypeError, ValueError):
                exceeds = False
            if exceeds:
                return "{:,.2f} {}**".format(num, [ReportedUnits])
            return "{:,.2f} {}".format(num, [ReportedUnits])
    """
    return (
        f'def FindLabel ( [{value_field}], [{sl_field}], [{units_field}] ):\n'
        f'    v = [{value_field}]\n'
        f'    sl = [{sl_field}]\n'
        f'    if v is None or v == "" or v == "{nd_text}":\n'
        f'        return "{nd_text}"\n'
        f'    try:\n'
        f'        num = float(v)\n'
        f'    except (TypeError, ValueError):\n'
        f'        return "{{}} {{}}".format(v, [{units_field}])\n'
        f'    try:\n'
        f'        exceeds = sl not in (None, "") and num > float(sl)\n'
        f'    except (TypeError, ValueError):\n'
        f'        exceeds = False\n'
        f'    if exceeds:\n'
        f'        return "{{:,.2f}} {{}}{exceed_suffix}".format(num, [{units_field}])\n'
        f'    return "{{:,.2f}} {{}}".format(num, [{units_field}])'
    )


def _build_nd_callout_expression(
    value_field: str,
    units_field: str,
    *,
    nd_text: str = "ND",
) -> str:
    """Return Esri Python label-expression source showing 'ND' label only (no
    numeric value shown). `units_field` is accepted for signature parity with the
    Arcade builder but unused, same as that builder.
    """
    return (
        f'def FindLabel ( [{value_field}] ):\n'
        f'    v = [{value_field}]\n'
        f'    if v is None or v == "" or v == "{nd_text}":\n'
        f'        return "{nd_text}"\n'
        f'    return ""'
    )


def _build_well_id_expression(analyte_field: str) -> str:
    """Return Esri Python label-expression source showing the location/well ID
    field only."""
    return (
        f'def FindLabel ( [{analyte_field}] ):\n'
        f'    return [{analyte_field}]'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_python_labels(
    analytes: list[str],
    *,
    field_prefix: str = "",
) -> list[PythonLabelSpec]:
    """Generate one PythonLabelSpec per analyte per expression type.

    Mirrors arcade_label_generator.generate_arcade_labels() field-for-field —
    see that function's docstring for parameter semantics.

    Args:
        analytes: List of canonical analyte names (e.g. ["Benzene", "PCE"]).
        field_prefix: Optional prefix for field names (e.g. "Env_").

    Returns:
        List of PythonLabelSpec objects (may be empty when analytes is empty).
    """
    if not analytes:
        return []

    specs: list[PythonLabelSpec] = []

    for analyte in analytes:
        fields = derive_label_fields(analyte, field_prefix)

        specs.append(PythonLabelSpec(
            layer_name=f"{fields.layer_base}_Result",
            expression_type=LabelExpressionType.RESULT_WITH_UNITS,
            analyte_field=fields.id_field,
            value_field=fields.value_field,
            units_field=fields.units_field,
            sl_field=None,
            expression=build_result_label_expression(fields.value_field, fields.units_field),
        ))

        specs.append(PythonLabelSpec(
            layer_name=f"{fields.layer_base}_Exceedance",
            expression_type=LabelExpressionType.EXCEEDANCE_CALLOUT,
            analyte_field=fields.id_field,
            value_field=fields.value_field,
            units_field=fields.units_field,
            sl_field=fields.sl_field,
            expression=build_exceedance_callout_expression(
                fields.value_field, fields.sl_field, fields.units_field
            ),
        ))

        specs.append(PythonLabelSpec(
            layer_name=f"{fields.layer_base}_ND",
            expression_type=LabelExpressionType.ND_CALLOUT,
            analyte_field=fields.id_field,
            value_field=fields.value_field,
            units_field=fields.units_field,
            sl_field=None,
            expression=_build_nd_callout_expression(fields.value_field, fields.units_field),
        ))

        specs.append(PythonLabelSpec(
            layer_name=f"{fields.layer_base}_WellID",
            expression_type=LabelExpressionType.WELL_ID_ONLY,
            analyte_field=fields.id_field,
            value_field=fields.value_field,
            units_field=fields.units_field,
            sl_field=None,
            expression=_build_well_id_expression(fields.id_field),
        ))

    return specs


def write_label_expressions(specs: list[PythonLabelSpec], out_path: Path) -> None:
    """Serialise a list of PythonLabelSpec objects to a JSON file.

    Each entry in the output array has:
        - layer_name: str
        - expression_type: str
        - analyte_field: str
        - value_field: str
        - units_field: str
        - sl_field: str | null
        - python_expression: str
        - expression_engine: str  ("Python" -- the labelClass.expressionEngine value)

    Args:
        specs: List of PythonLabelSpec objects from generate_python_labels().
        out_path: Destination .json file path (parent directories created if needed).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = [
        {
            "layer_name": s.layer_name,
            "expression_type": s.expression_type,
            "analyte_field": s.analyte_field,
            "value_field": s.value_field,
            "units_field": s.units_field,
            "sl_field": s.sl_field,
            "python_expression": s.expression,
            "expression_engine": EXPRESSION_ENGINE,
        }
        for s in specs
    ]

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
