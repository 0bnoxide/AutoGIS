"""label_expression_common.py — shared field-name derivation for label expression
generators (Arcade + Python).

Field-naming convention MUST stay identical across expression-language variants so
both point at the same GDB fields.

No arcpy dependency. stdlib + dataclasses only.
"""
from __future__ import annotations

from dataclasses import dataclass


class LabelExpressionType:
    """String constants for label expression variants (shared across languages)."""

    RESULT_WITH_UNITS: str = "RESULT_WITH_UNITS"
    EXCEEDANCE_CALLOUT: str = "EXCEEDANCE_CALLOUT"
    ND_CALLOUT: str = "ND_CALLOUT"
    WELL_ID_ONLY: str = "WELL_ID_ONLY"


@dataclass
class LabelFields:
    """GDB field names derived for one analyte."""

    layer_base: str
    id_field: str
    value_field: str
    units_field: str
    sl_field: str


def derive_label_fields(analyte: str, field_prefix: str = "") -> LabelFields:
    """Derive GDB field names for one analyte + optional prefix.

    Shared by both label generators — the Arcade and Python variants MUST agree on
    field names for a given analyte, since they label the same GDB layer.
    """
    safe_name = analyte.replace(" ", "_").replace(",", "").replace("/", "_")
    return LabelFields(
        layer_base=safe_name,
        id_field=f"{field_prefix}LocationID",
        value_field=f"{field_prefix}{safe_name}_Value",
        units_field=f"{field_prefix}{safe_name}_Units",
        sl_field=f"{field_prefix}{safe_name}_SL",
    )
