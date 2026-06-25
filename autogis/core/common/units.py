"""Canonical unit registry and pure, arcpy-free unit conversion.

The registry IS the set of explicit conversion rules: a conversion is allowed
iff both units are registered in the same dimension. ``ppb``/``ppm`` are
deliberately excluded because they are dimension-ambiguous (ppb = ug/L in water
but ug/kg in soil) and would defeat the cross-dimension guard. Unknown units
resolve to ``None`` so callers can decide severity; ``convert`` raises.
"""
from __future__ import annotations

from typing import Optional

# canonical key -> (dimension, factor to the dimension's base unit)
UNIT_REGISTRY = {
    "ng/L": ("aqueous", 0.001), "ug/L": ("aqueous", 1.0),
    "mg/L": ("aqueous", 1000.0), "g/L": ("aqueous", 1_000_000.0),
    "ug/kg": ("soil", 0.001), "mg/kg": ("soil", 1.0), "g/kg": ("soil", 1000.0),
}

# lowercased-canonical -> canonical, for case-insensitive lookup.
_LOOKUP = {k.lower(): k for k in UNIT_REGISTRY}


class UnitError(ValueError):
    """Unknown unit or a cross-dimension conversion attempt."""


def normalize_unit(u) -> Optional[str]:
    """Return the canonical registry key for ``u`` or None.

    Strips whitespace, maps the micro signs U+00B5/U+03BC to 'u', and matches
    case-insensitively, so 'ug/L', 'UG/L', ' ug/l ' and 'µg/L' all map to 'ug/L'.
    """
    if u is None:
        return None
    key = str(u).strip().replace("µ", "u").replace("μ", "u").lower()
    return _LOOKUP.get(key)


def dimension_of(u) -> Optional[str]:
    canon = normalize_unit(u)
    return UNIT_REGISTRY[canon][0] if canon else None


def same_dimension(a, b) -> bool:
    da, db = dimension_of(a), dimension_of(b)
    return da is not None and da == db


def convert(value: float, from_u: str, to_u: str) -> float:
    """Convert ``value`` from ``from_u`` to ``to_u`` within one dimension.

    Raises UnitError when either unit is unknown or the two units are in
    different dimensions.
    """
    cf, ct = normalize_unit(from_u), normalize_unit(to_u)
    if cf is None:
        raise UnitError(f"unknown unit: {from_u!r}")
    if ct is None:
        raise UnitError(f"unknown unit: {to_u!r}")
    dim_f, factor_f = UNIT_REGISTRY[cf]
    dim_t, factor_t = UNIT_REGISTRY[ct]
    if dim_f != dim_t:
        raise UnitError(
            f"cannot convert {from_u!r} ({dim_f}) to {to_u!r} ({dim_t}): "
            f"different dimensions")
    return value * factor_f / factor_t
