"""Pure, arcpy-free config validators.

Each function takes already-loaded dict data and returns a list of QARecord.
Collect-all (never raise on bad data); the orchestrator owns file I/O. Used by
ValidateEnvConfig and ManageAnalyteDictionary.
"""
from __future__ import annotations

from collections import Counter
from typing import List

from .config import FIGURE_REQUIRED, SITE_REQUIRED, col_index
from .qa import QARecord, SEV_ERROR, SEV_WARNING

KNOWN_MATRICES = {"GW", "SOIL"}
KNOWN_MAP_TYPES = {"GW_ANALYTICAL", "GW_POTENTIOMETRIC", "SOIL_ANALYTICAL"}
KNOWN_SHEET_DATA_TYPES = {
    "GW_ANALYTICAL_AND_WATER_LEVEL", "IBI", "METALS", "RPD",
    "SOIL_ANALYTICAL", "GW_ANALYTICAL",
}

# Minimal key sets used by tests to isolate non-missing-key checks.
_SITE_MIN = SITE_REQUIRED + ["map_units", "plausible_gwe_range_ft"]
_FIGURE_MIN = FIGURE_REQUIRED + ["matrix", "map_type"]


def _rec(sev, cat, msg, action="", **ctx):
    return QARecord(severity=sev, category=cat, message=msg,
                    recommended_action=action, **ctx)


def scan_todos(data, context: str) -> List[QARecord]:
    """Walk nested dict/list values; flag any string containing '_TODO'."""
    out: List[QARecord] = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and "_TODO" in node:
            out.append(_rec(SEV_WARNING, "placeholder",
                            f"{context}: unresolved _TODO at {path}: {node!r}",
                            action="fill in before production use"))

    walk(data, "")
    return out


def _require(data, keys, context, out):
    for k in keys:
        if k not in data:
            out.append(_rec(SEV_ERROR, "missing_key",
                            f"{context}: missing required key {k!r}"))


def validate_site(data: dict) -> List[QARecord]:
    out: List[QARecord] = []
    _require(data, SITE_REQUIRED, "site config", out)
    mu = data.get("map_units")
    if mu is not None and mu not in ("feet", "meters"):
        out.append(_rec(SEV_ERROR, "bad_map_units",
                        f"site config: map_units must be 'feet' or 'meters', got {mu!r}"))
    rng = data.get("plausible_gwe_range_ft")
    if rng is not None:
        ok = (isinstance(rng, list) and len(rng) == 2
              and all(isinstance(x, (int, float)) for x in rng) and rng[0] < rng[1])
        if not ok:
            out.append(_rec(SEV_ERROR, "bad_gwe_range",
                            f"site config: plausible_gwe_range_ft must be "
                            f"[low, high] ascending numbers, got {rng!r}"))
    out += scan_todos(data, "site config")
    return out


def validate_parser_profile(data: dict) -> List[QARecord]:
    out: List[QARecord] = []
    _require(data, ["profile_id", "sheets"], "parser profile", out)
    for sd in data.get("sheets", []) or []:
        name = sd.get("sheet_name", "?")
        dt = sd.get("data_type")
        if dt is not None and dt not in KNOWN_SHEET_DATA_TYPES:
            out.append(_rec(SEV_WARNING, "unknown_data_type",
                            f"sheet {name!r}: unrecognized data_type {dt!r}"))
        for key in ("id_column", "sample_id_column", "date_column",
                    "depth_column", "dtw_column", "gwe_column", "mpe_column"):
            ref = sd.get(key)
            if ref is None:
                continue
            try:
                idx = col_index(ref)
            except Exception:
                out.append(_rec(SEV_ERROR, "bad_column_ref",
                                f"sheet {name!r}: {key} has invalid column "
                                f"reference {ref!r}"))
                continue
            if idx is not None and idx < 1:
                out.append(_rec(SEV_ERROR, "bad_column_ref",
                                f"sheet {name!r}: {key} column reference {ref!r} "
                                f"must be >= 1"))
    out += scan_todos(data, "parser profile")
    return out


def validate_figure_spec(data: dict) -> List[QARecord]:
    out: List[QARecord] = []
    _require(data, FIGURE_REQUIRED, "figure spec", out)
    matrix = data.get("matrix")
    if matrix is not None and matrix not in KNOWN_MATRICES:
        out.append(_rec(SEV_ERROR, "bad_matrix",
                        f"figure spec: matrix must be one of "
                        f"{sorted(KNOWN_MATRICES)}, got {matrix!r}"))
    mt = data.get("map_type")
    if mt is not None and mt not in KNOWN_MAP_TYPES:
        out.append(_rec(SEV_WARNING, "unknown_map_type",
                        f"figure spec: unrecognized map_type {mt!r}"))
    out += scan_todos(data, "figure spec")
    return out


def validate_screening_levels(data: dict) -> List[QARecord]:
    out: List[QARecord] = []
    for matrix, entries in (data or {}).items():
        if not isinstance(entries, dict):
            continue
        if matrix not in KNOWN_MATRICES:
            out.append(_rec(SEV_WARNING, "unknown_matrix",
                            f"screening levels: unrecognized matrix {matrix!r}"))
        for analyte, entry in entries.items():
            if not isinstance(entry, dict):
                out.append(_rec(SEV_ERROR, "screening_bad_entry",
                                f"screening {matrix}/{analyte}: entry must be a mapping"))
                continue
            for field in ("value", "units"):
                if field not in entry:
                    out.append(_rec(SEV_ERROR, "screening_missing_field",
                                    f"screening {matrix}/{analyte}: missing {field!r}",
                                    analyte_name=str(analyte)))
    out += scan_todos(data, "screening levels")
    return out


def validate_analyte_dictionary(analytes: dict) -> List[QARecord]:
    from ..envmon.result_parser import _norm_key  # local import to avoid circular dependency

    out: List[QARecord] = []
    seen_norm: dict[str, str] = {}     # _norm_key -> first canonical that claimed it
    order_counts: Counter = Counter()

    for canonical, entry in (analytes or {}).items():
        if str(canonical).startswith("_"):
            continue
        if not isinstance(entry, dict):
            out.append(_rec(SEV_ERROR, "analyte_bad_entry",
                            f"analyte {canonical!r}: entry must be a mapping",
                            analyte_name=str(canonical)))
            continue

        keys = {canonical} | set(entry.get("aliases", []) or [])
        abbrev = entry.get("abbreviation")
        if abbrev:
            keys.add(abbrev)
        for k in keys:
            nk = _norm_key(str(k))
            owner = seen_norm.get(nk)
            if owner is not None and owner != canonical:
                out.append(_rec(SEV_ERROR, "alias_collision",
                                f"alias/name {k!r} maps to both {owner!r} and "
                                f"{canonical!r}", analyte_name=str(canonical),
                                action="make aliases unique across analytes"))
            else:
                seen_norm[nk] = canonical

        order = entry.get("display_order")
        if order is not None:
            order_counts[order] += 1

        src = entry.get("screening_level_source")
        if isinstance(src, str) and "_TODO" in src:
            out.append(_rec(SEV_WARNING, "placeholder",
                            f"analyte {canonical!r}: screening_level_source has "
                            f"_TODO: {src!r}", analyte_name=str(canonical)))

    for order, n in order_counts.items():
        if n > 1 and order != 9999:   # 9999 is the default-unset sentinel
            out.append(_rec(SEV_WARNING, "duplicate_display_order",
                            f"display_order {order} used by {n} analytes"))
    return out


def _figure_analytes(spec: dict) -> List[str]:
    names = list(spec.get("analytes", []) or [])
    for members in (spec.get("analyte_sets", {}) or {}).values():
        names += list(members or [])
    return names


def validate_bundle(figure_specs, screening_levels, analytes) -> List[QARecord]:
    from ..envmon.result_parser import build_analyte_lookup, _norm_key  # local import to avoid circular dependency

    out: List[QARecord] = []
    clean = {k: v for k, v in (analytes or {}).items() if not str(k).startswith("_")}
    lookup = build_analyte_lookup(clean)   # {_norm_key: canonical}

    def known(name) -> bool:
        return _norm_key(str(name)) in lookup

    for spec in figure_specs or []:
        fid = spec.get("figure_spec_id", "?")
        for name in _figure_analytes(spec):
            if not known(name):
                out.append(_rec(SEV_ERROR, "figure_analyte_not_in_dictionary",
                                f"figure {fid!r}: analyte {name!r} not in analyte "
                                f"dictionary", analyte_name=str(name)))

    for matrix, entries in (screening_levels or {}).items():
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            if not known(name):
                out.append(_rec(SEV_ERROR, "screening_analyte_not_in_dictionary",
                                f"screening {matrix}/{name}: not in analyte "
                                f"dictionary", analyte_name=str(name)))
                continue
            canonical = lookup[_norm_key(str(name))]
            dict_units = ((clean.get(canonical, {}) or {})
                          .get("default_units_by_matrix", {}) or {}).get(matrix)
            scr_units = entry.get("units") if isinstance(entry, dict) else None
            if dict_units and scr_units and str(dict_units).strip().lower() != \
                    str(scr_units).strip().lower():
                out.append(_rec(SEV_WARNING, "units_mismatch",
                                f"screening {matrix}/{name}: units {scr_units!r} "
                                f"differ from dictionary default {dict_units!r}",
                                analyte_name=str(name)))
    return out
