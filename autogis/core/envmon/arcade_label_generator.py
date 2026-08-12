"""arcade_label_generator.py — Arcade label expression generator (Tool 5.4).

Generates Arcade label expression strings for ArcGIS Pro callout layers.
Output is a JSON file (array of objects) ready to paste or import into
ArcGIS Pro layer label settings.

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


@dataclass
class ArcadeLabelSpec:
    """One Arcade label expression for a single analyte + expression type."""

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
    """Return Arcade that renders a result value with units, or ND text.

    Example output (Arcade code):
        var v = $feature.ResultValue;
        if (IsEmpty(v) || v == "ND") { return "ND"; }
        return Text(v, "#,##0.00") + " " + $feature.ReportedUnits;
    """
    return (
        f'var v = $feature.{value_field};\n'
        f'if (IsEmpty(v) || v == "{nd_text}") {{ return "{nd_text}"; }}\n'
        f'return Text(v, "#,##0.00") + " " + $feature.{units_field};'
    )


def build_exceedance_callout_expression(
    value_field: str,
    sl_field: str,
    units_field: str,
    *,
    nd_text: str = "ND",
    exceed_suffix: str = "**",
) -> str:
    """Return Arcade that appends '**' when the result exceeds the screening level.

    Example output (Arcade code):
        var v = $feature.ResultValue;
        var sl = $feature.ScreeningLevel;
        if (IsEmpty(v) || v == "ND") { return "ND"; }
        var num = Number(v);
        if (!IsEmpty(sl) && num > Number(sl)) {
            return Text(num, "#,##0.00") + " " + $feature.ReportedUnits + "**";
        }
        return Text(num, "#,##0.00") + " " + $feature.ReportedUnits;
    """
    return (
        f'var v = $feature.{value_field};\n'
        f'var sl = $feature.{sl_field};\n'
        f'if (IsEmpty(v) || v == "{nd_text}") {{ return "{nd_text}"; }}\n'
        f'var num = Number(v);\n'
        f'if (!IsEmpty(sl) && num > Number(sl)) {{\n'
        f'    return Text(num, "#,##0.00") + " " + $feature.{units_field} + "{exceed_suffix}";\n'
        f'}}\n'
        f'return Text(num, "#,##0.00") + " " + $feature.{units_field};'
    )


def _build_nd_callout_expression(
    value_field: str,
    *,
    nd_text: str = "ND",
) -> str:
    """Return Arcade that shows 'ND' label only (no numeric value shown).

    Used for ND-only callout layers so detected results are suppressed.
    """
    return (
        f'var v = $feature.{value_field};\n'
        f'if (IsEmpty(v) || v == "{nd_text}") {{ return "{nd_text}"; }}\n'
        f'return "";'
    )


def _build_well_id_expression(analyte_field: str) -> str:
    """Return Arcade that shows the location/well ID field only."""
    return f'return $feature.{analyte_field};'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_arcade_labels(
    analytes: list[str],
    *,
    field_prefix: str = "",
) -> list[ArcadeLabelSpec]:
    """Generate one ArcadeLabelSpec per analyte per expression type.

    Args:
        analytes: List of canonical analyte names (e.g. ["Benzene", "PCE"]).
        field_prefix: Optional prefix for field names (e.g. "Env_"). Prepended
            to value_field, units_field, and sl_field names.

    Returns:
        List of ArcadeLabelSpec objects (may be empty when analytes is empty).
    """
    if not analytes:
        return []

    specs: list[ArcadeLabelSpec] = []

    for analyte in analytes:
        # Derive field names from the analyte name + prefix
        fields = derive_label_fields(analyte, field_prefix)
        value_field = fields.value_field
        units_field = fields.units_field
        sl_field = fields.sl_field
        id_field = fields.id_field
        layer_base = fields.layer_base

        # 1. RESULT_WITH_UNITS
        specs.append(ArcadeLabelSpec(
            layer_name=f"{layer_base}_Result",
            expression_type=LabelExpressionType.RESULT_WITH_UNITS,
            analyte_field=id_field,
            value_field=value_field,
            units_field=units_field,
            sl_field=None,
            expression=build_result_label_expression(value_field, units_field),
        ))

        # 2. EXCEEDANCE_CALLOUT
        specs.append(ArcadeLabelSpec(
            layer_name=f"{layer_base}_Exceedance",
            expression_type=LabelExpressionType.EXCEEDANCE_CALLOUT,
            analyte_field=id_field,
            value_field=value_field,
            units_field=units_field,
            sl_field=sl_field,
            expression=build_exceedance_callout_expression(
                value_field, sl_field, units_field
            ),
        ))

        # 3. ND_CALLOUT
        specs.append(ArcadeLabelSpec(
            layer_name=f"{layer_base}_ND",
            expression_type=LabelExpressionType.ND_CALLOUT,
            analyte_field=id_field,
            value_field=value_field,
            units_field=units_field,
            sl_field=None,
            expression=_build_nd_callout_expression(value_field),
        ))

        # 4. WELL_ID_ONLY (well-ID-only label; emitted per analyte since each
        # analyte gets its own layer, though the expression logic is identical)
        specs.append(ArcadeLabelSpec(
            layer_name=f"{layer_base}_WellID",
            expression_type=LabelExpressionType.WELL_ID_ONLY,
            analyte_field=id_field,
            value_field=value_field,
            units_field=units_field,
            sl_field=None,
            expression=_build_well_id_expression(id_field),
        ))

    return specs


def write_label_expressions(specs: list[ArcadeLabelSpec], out_path: Path) -> None:
    """Serialise a list of ArcadeLabelSpec objects to a JSON file.

    Each entry in the output array has:
        - layer_name: str
        - expression_type: str
        - analyte_field: str
        - value_field: str
        - units_field: str
        - sl_field: str | null
        - arcade_expression: str

    Args:
        specs: List of ArcadeLabelSpec objects from generate_arcade_labels().
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
            "arcade_expression": s.expression,
        }
        for s in specs
    ]

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
