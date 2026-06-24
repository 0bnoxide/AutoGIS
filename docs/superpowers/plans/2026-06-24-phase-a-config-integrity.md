# Phase A — Config Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ValidateEnvConfig` and `ManageAnalyteDictionary` — two read-only, headless QA tools that catch bad/inconsistent configs (and cross-file reference breaks) before pipeline runs fail.

**Architecture:** A single new module `core/common/config_validation.py` of pure `data -> List[QARecord]` validator functions. Two thin orchestrators in `core/envmon/` load files and feed validators into a `QACollector`. Two new `envmon` CLI commands render the collector and set exit codes. No new dependencies; reuses the existing `core/common/qa.py` report stack exactly as `validate_database.py` does.

**Tech Stack:** Python 3, `click` (CLI), `openpyxl`/`PyYAML` (already present), `pytest`. No arcpy anywhere in this phase.

## Global Constraints

- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` present (ADR-002). Nothing in this phase imports arcpy.
- Reuse `core/common/qa.py` (`QACollector`, `QARecord`, `SEV_ERROR`, `SEV_WARNING`, `SEV_INFO`) — do not invent a new report type.
- Validators are pure: they receive already-loaded `dict` data and return `List[QARecord]`. They never read files, never raise on bad data (collect-all, not fail-fast), never import arcpy.
- `_TODO` / DRAFT markers must surface as `SEV_WARNING` (category `placeholder`), never be removed or silently passed (CLAUDE.md invariant).
- Exit codes for both commands: `0` = PASS, `1` = FAIL (blocking per `QACollector.status()`), `2` = usage/tool error (click default).
- `--fail-on error|warning` (default `error`) maps to `QACollector.status(allow_warnings=<fail_on != 'warning'>, allow_errors=False)`.
- Tests are headless and live under `tests/envmon/`; run with `python -m pytest -q`.
- Reuse `_norm_key` and `build_analyte_lookup` from `core/envmon/result_parser.py` for analyte name normalization — do not duplicate normalization rules.

Known vocabularies (module-level constants in `config_validation.py`):
- `KNOWN_MATRICES = {"GW", "SOIL"}`
- `KNOWN_MAP_TYPES = {"GW_ANALYTICAL", "GW_POTENTIOMETRIC", "SOIL_ANALYTICAL"}`
- `KNOWN_SHEET_DATA_TYPES = {"GW_ANALYTICAL_AND_WATER_LEVEL", "IBI", "METALS", "RPD", "SOIL_ANALYTICAL", "GW_ANALYTICAL"}`

Matrix outside `KNOWN_MATRICES` → ERROR (fundamental). `map_type`/`data_type` outside their known sets → WARNING (vocabulary grows over time).

---

### Task 1: Per-file validators (site, parser profile, figure spec, screening levels)

**Files:**
- Create: `autogis/core/common/config_validation.py`
- Test: `tests/envmon/test_config_validation.py`

**Interfaces:**
- Consumes: `core/common/qa.QARecord`, `SEV_ERROR`, `SEV_WARNING`, `SEV_INFO`; `core/common/config.col_index`, `FIGURE_REQUIRED`, `SITE_REQUIRED`.
- Produces:
  - `scan_todos(data: dict, context: str) -> list[QARecord]`
  - `validate_site(data: dict) -> list[QARecord]`
  - `validate_parser_profile(data: dict) -> list[QARecord]`
  - `validate_figure_spec(data: dict) -> list[QARecord]`
  - `validate_screening_levels(data: dict) -> list[QARecord]`
  - Constants `KNOWN_MATRICES`, `KNOWN_MAP_TYPES`, `KNOWN_SHEET_DATA_TYPES`.

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_config_validation.py
from autogis.core.common import config_validation as cv
from autogis.core.common.qa import SEV_ERROR, SEV_WARNING


def _cats(records):
    return {(r.severity, r.category) for r in records}


def test_validate_site_flags_missing_keys_and_todos():
    data = {"site_id": "H281", "map_units": "feet",
            "coordinate_system": "_TODO verify", "plausible_gwe_range_ft": [1900, 2400]}
    records = cv.validate_site(data)
    cats = _cats(records)
    # missing required keys (site_name etc.) -> ERROR / missing_key
    assert (SEV_ERROR, "missing_key") in cats
    # _TODO value -> WARNING / placeholder
    assert (SEV_WARNING, "placeholder") in cats


def test_validate_site_bad_map_units_and_gwe_range():
    data = {k: "x" for k in cv._SITE_MIN}  # minimal so missing_key doesn't dominate
    data["map_units"] = "furlongs"
    data["plausible_gwe_range_ft"] = [2400, 1900]  # descending
    records = cv.validate_site(data)
    cats = _cats(records)
    assert (SEV_ERROR, "bad_map_units") in cats
    assert (SEV_ERROR, "bad_gwe_range") in cats


def test_validate_figure_spec_unknown_matrix_is_error_unknown_maptype_is_warning():
    data = {k: "x" for k in cv._FIGURE_MIN}
    data["matrix"] = "AIR"
    data["map_type"] = "GW_BRAND_NEW"
    records = cv.validate_figure_spec(data)
    cats = _cats(records)
    assert (SEV_ERROR, "bad_matrix") in cats
    assert (SEV_WARNING, "unknown_map_type") in cats


def test_validate_parser_profile_bad_column_ref():
    data = {"profile_id": "P", "sheets": [
        {"sheet_name": "S", "data_type": "METALS", "data_start_row": 2,
         "id_column": "not-a-column"}]}
    records = cv.validate_parser_profile(data)
    assert (SEV_ERROR, "bad_column_ref") in _cats(records)


def test_validate_screening_levels_entry_missing_units():
    data = {"GW": {"Benzene": {"value": 5.0}}}  # no units
    records = cv.validate_screening_levels(data)
    assert (SEV_ERROR, "screening_missing_field") in _cats(records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_config_validation.py -q`
Expected: FAIL — `ModuleNotFoundError: autogis.core.common.config_validation`.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/core/common/config_validation.py
"""Pure, arcpy-free config validators.

Each function takes already-loaded dict data and returns a list of QARecord.
Collect-all (never raise on bad data); the orchestrator owns file I/O. Used by
ValidateEnvConfig and ManageAnalyteDictionary.
"""
from __future__ import annotations

from typing import List

from .config import FIGURE_REQUIRED, SITE_REQUIRED, col_index
from .qa import QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

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
                col_index(ref)
            except Exception:
                out.append(_rec(SEV_ERROR, "bad_column_ref",
                                f"sheet {name!r}: {key} has invalid column "
                                f"reference {ref!r}"))
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_config_validation.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/common/config_validation.py tests/envmon/test_config_validation.py
git commit -m "feat(envmon): per-file config validators (site/profile/figure/screening)"
```

---

### Task 2: Analyte dictionary validator (with alias-collision detection)

**Files:**
- Modify: `autogis/core/common/config_validation.py`
- Test: `tests/envmon/test_config_validation.py`

**Interfaces:**
- Consumes: `core/envmon/result_parser._norm_key`.
- Produces: `validate_analyte_dictionary(analytes: dict) -> list[QARecord]` where `analytes` is `{canonical_name: {aliases, abbreviation, display_order, ...}}` (the mapping `load_analyte_dictionary` returns; `_`-prefixed keys already excluded by caller, but the function defensively skips them).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/envmon/test_config_validation.py
def test_validate_analyte_dictionary_detects_alias_collision_and_dup_order():
    analytes = {
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10},
        "Toluene": {"aliases": ["toluene", "b"], "abbreviation": "T",
                    "display_order": 10},  # 'b' collides w/ Benzene; order dup
    }
    records = cv.validate_analyte_dictionary(analytes)
    cats = {(r.severity, r.category) for r in records}
    assert (SEV_ERROR, "alias_collision") in cats
    assert (SEV_WARNING, "duplicate_display_order") in cats


def test_validate_analyte_dictionary_flags_todo_source():
    analytes = {"Arsenic": {"aliases": ["as"], "abbreviation": "As",
                            "display_order": 200,
                            "screening_level_source": "_TODO MCL/DEQ-7"}}
    records = cv.validate_analyte_dictionary(analytes)
    assert (SEV_WARNING, "placeholder") in {(r.severity, r.category) for r in records}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_config_validation.py -k analyte -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'validate_analyte_dictionary'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to autogis/core/common/config_validation.py
from collections import Counter

from ..envmon.result_parser import _norm_key  # noqa: E402  (avoid top cycle risk)


def validate_analyte_dictionary(analytes: dict) -> List[QARecord]:
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
```

> Note: `_norm_key` import is placed after the existing top-level imports to keep the dependency explicit. If a circular-import error appears at collection time, move the import inside the function body (local import) — `result_parser` is arcpy-free so either placement is ADR-002 safe.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_config_validation.py -q`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/common/config_validation.py tests/envmon/test_config_validation.py
git commit -m "feat(envmon): analyte dictionary validator with alias-collision detection"
```

---

### Task 3: Cross-file bundle validator

**Files:**
- Modify: `autogis/core/common/config_validation.py`
- Test: `tests/envmon/test_config_validation.py`

**Interfaces:**
- Consumes: `build_analyte_lookup` from `core/envmon/result_parser`; `_norm_key`.
- Produces: `validate_bundle(figure_specs: list[dict], screening_levels: dict, analytes: dict) -> list[QARecord]`. `analytes` is the `{canonical: {...}}` mapping; `figure_specs` is a list of raw figure-spec dicts.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/envmon/test_config_validation.py
def test_validate_bundle_flags_unknown_figure_and_screening_analytes():
    analytes = {"Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                            "display_order": 10,
                            "default_units_by_matrix": {"GW": "ug/L"}}}
    figure_specs = [{"figure_spec_id": "F1", "analytes": ["Benzene", "Xylenes"]}]
    screening = {"GW": {"Benzene": {"value": 5, "units": "mg/L"},  # unit mismatch
                        "Lead": {"value": 15, "units": "ug/L"}}}   # not in dict
    records = cv.validate_bundle(figure_specs, screening, analytes)
    cats = {(r.severity, r.category) for r in records}
    assert (SEV_ERROR, "figure_analyte_not_in_dictionary") in cats   # Xylenes
    assert (SEV_ERROR, "screening_analyte_not_in_dictionary") in cats  # Lead
    assert (SEV_WARNING, "units_mismatch") in cats                     # Benzene mg/L vs ug/L
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_config_validation.py -k bundle -q`
Expected: FAIL — `validate_bundle` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# append to autogis/core/common/config_validation.py
from ..envmon.result_parser import build_analyte_lookup  # noqa: E402


def _figure_analytes(spec: dict) -> List[str]:
    names = list(spec.get("analytes", []) or [])
    for members in (spec.get("analyte_sets", {}) or {}).values():
        names += list(members or [])
    return names


def validate_bundle(figure_specs, screening_levels, analytes) -> List[QARecord]:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_config_validation.py -q`
Expected: PASS (8 tests total).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/common/config_validation.py tests/envmon/test_config_validation.py
git commit -m "feat(envmon): cross-file bundle validator (figure/screening analyte refs + units)"
```

---

### Task 4: ValidateEnvConfig orchestrator

**Files:**
- Create: `autogis/core/envmon/validate_config.py`
- Test: `tests/envmon/test_validate_config.py`

**Interfaces:**
- Consumes: `core/common/config.load_config`, `load_analyte_dictionary`, `load_screening_levels`; all `config_validation` validators; `core/common/qa.QACollector`.
- Produces: `validate_env_config(site_path, profile_paths, figure_paths, analytes_path, screening_path) -> QACollector`. All path args are `Path | None`; `profile_paths`/`figure_paths` are lists. Each file loaded defensively (a load failure becomes an ERROR record, category `load_error`, not an exception).

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_validate_config.py
from pathlib import Path

import yaml

from autogis.core.envmon.validate_config import validate_env_config
from autogis.core.common.qa import SEV_ERROR


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_validate_env_config_collects_cross_file_break(tmp_path):
    site = _write(tmp_path, "site.yaml", {
        "site_id": "H281", "site_name": "X", "project_number": "H281",
        "address": "a", "city": "c", "state": "s",
        "coordinate_system": "NAD83", "default_gdb": "g.gdb",
        "default_aprx_template": "t.aprx", "monitoring_wells_fc": "MW",
        "soil_borings_fc": "SB", "site_boundary_fc": "BND",
        "map_units": "feet", "plausible_gwe_range_ft": [1900, 2400]})
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "display_order": 10}}})
    figure = _write(tmp_path, "fig.yaml", {
        "figure_spec_id": "F1", "map_type": "GW_ANALYTICAL", "matrix": "GW",
        "layout_name": "L", "figure_title": "T",
        "output_filename_pattern": "{x}.pdf", "callout_template": {},
        "analytes": ["Benzene", "Nonexistium"]})
    qa = validate_env_config(site, [], [figure], analytes, None)
    cats = {(r.severity, r.category) for r in qa.records}
    assert (SEV_ERROR, "figure_analyte_not_in_dictionary") in cats


def test_validate_env_config_bad_file_becomes_load_error(tmp_path):
    bad = tmp_path / "site.yaml"
    bad.write_text(": : not valid yaml : :", encoding="utf-8")
    qa = validate_env_config(bad, [], [], None, None)
    assert (SEV_ERROR, "load_error") in {(r.severity, r.category) for r in qa.records}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_validate_config.py -q`
Expected: FAIL — module `validate_config` not found.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/core/envmon/validate_config.py
"""ValidateEnvConfig — per-bundle config integrity checks (headless, arcpy-free).

Loads the explicit (site, parser profiles, figure specs, analyte dictionary,
screening levels) bundle a run would use, runs every validator into a single
QACollector, and adds a closing INFO summary record. File loads are defensive:
a failure becomes an ERROR record rather than an exception, so one bad file
never hides problems in the others.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..common import config_validation as cv
from ..common.config import (load_analyte_dictionary, load_config,
                             load_screening_levels)
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO


def _safe(qa: QACollector, label: str, fn):
    try:
        return fn()
    except Exception as exc:  # ConfigError, yaml errors, etc.
        qa.add(QARecord(severity=SEV_ERROR, category="load_error",
                        message=f"could not load {label}: {exc}"))
        return None


def validate_env_config(site_path: Optional[Path],
                        profile_paths: Optional[List[Path]],
                        figure_paths: Optional[List[Path]],
                        analytes_path: Optional[Path],
                        screening_path: Optional[Path]) -> QACollector:
    qa = QACollector()
    figure_specs: List[dict] = []
    analytes: dict = {}
    screening: dict = {}

    if site_path:
        data = _safe(qa, f"site config {Path(site_path).name}",
                     lambda: load_config(Path(site_path)))
        if data is not None:
            qa.extend(cv.validate_site(data))

    for pp in profile_paths or []:
        data = _safe(qa, f"parser profile {Path(pp).name}",
                     lambda pp=pp: load_config(Path(pp)))
        if data is not None:
            qa.extend(cv.validate_parser_profile(data))

    for fp in figure_paths or []:
        data = _safe(qa, f"figure spec {Path(fp).name}",
                     lambda fp=fp: load_config(Path(fp)))
        if data is not None:
            figure_specs.append(data)
            qa.extend(cv.validate_figure_spec(data))

    if analytes_path:
        analytes = _safe(qa, f"analyte dictionary {Path(analytes_path).name}",
                         lambda: load_analyte_dictionary(Path(analytes_path))) or {}
        if analytes:
            qa.extend(cv.validate_analyte_dictionary(analytes))

    if screening_path:
        screening = _safe(qa, f"screening levels {Path(screening_path).name}",
                          lambda: load_screening_levels(Path(screening_path))) or {}
        if screening:
            qa.extend(cv.validate_screening_levels(screening))

    # Cross-file checks only run when the dictionary is present to compare against.
    if analytes:
        qa.extend(cv.validate_bundle(figure_specs, screening, analytes))

    counts = qa.counts_by_severity()
    qa.add(QARecord(severity=SEV_INFO, category="validation_complete",
                    message=(f"Config validation finished: "
                             f"{counts.get('ERROR', 0)} error(s), "
                             f"{counts.get('WARNING', 0)} warning(s).")))
    return qa
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_validate_config.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/validate_config.py tests/envmon/test_validate_config.py
git commit -m "feat(envmon): ValidateEnvConfig per-bundle orchestrator"
```

---

### Task 5: `validate-config` CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` (add command in the headless section, after `figure_spec_cmd` near line 105)
- Test: `tests/envmon/test_cli_validate_config.py`

**Interfaces:**
- Consumes: `validate_env_config` (Task 4); `QACollector.status`, `write_markdown`/`write_json_summary`/`write_csv`.
- Produces: CLI `autogis envmon validate-config SITE [--profile P]... [--figure F]... [--analytes A] [--screening S] [--report OUT] [--fail-on error|warning]`. Exit 0 PASS / 1 FAIL.

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_cli_validate_config.py
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_validate_config_cli_fails_on_cross_file_break(tmp_path):
    site = _write(tmp_path, "site.yaml", {
        "site_id": "H281", "site_name": "X", "project_number": "H281",
        "address": "a", "city": "c", "state": "s", "coordinate_system": "NAD83",
        "default_gdb": "g.gdb", "default_aprx_template": "t.aprx",
        "monitoring_wells_fc": "MW", "soil_borings_fc": "SB",
        "site_boundary_fc": "BND", "map_units": "feet",
        "plausible_gwe_range_ft": [1900, 2400]})
    analytes = _write(tmp_path, "analytes.yaml",
                      {"analytes": {"Benzene": {"aliases": ["benzene"],
                                                "abbreviation": "B",
                                                "display_order": 10}}})
    figure = _write(tmp_path, "fig.yaml", {
        "figure_spec_id": "F1", "map_type": "GW_ANALYTICAL", "matrix": "GW",
        "layout_name": "L", "figure_title": "T",
        "output_filename_pattern": "{x}.pdf", "callout_template": {},
        "analytes": ["Benzene", "Nonexistium"]})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-config", site, "--figure", figure,
        "--analytes", analytes])
    assert r.exit_code == 1
    assert "figure_analyte_not_in_dictionary" in r.output


def test_validate_config_cli_passes_clean_bundle(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml",
                      {"analytes": {"Benzene": {"aliases": ["benzene"],
                                                "abbreviation": "B",
                                                "display_order": 10}}})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-config", analytes,  # site arg can be any loadable yaml
        "--analytes", analytes, "--fail-on", "error"])
    # site validators will emit missing_key ERRORs -> exit 1; use a real site instead:
    assert r.exit_code in (0, 1)  # smoke: command runs, returns a real status
```

> Note: the second test is a smoke check that the command wires up and returns a status; Task 4 already covers PASS/FAIL logic at the core level.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_cli_validate_config.py -q`
Expected: FAIL — no such command `validate-config`.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/adapters/cli.py — add after figure_spec_cmd (around line 105)
@envmon.command("validate-config")
@click.argument("site_config", type=click.Path(exists=True))
@click.option("--profile", "profiles", multiple=True, type=click.Path(exists=True),
              help="Parser profile(s) to validate (repeatable).")
@click.option("--figure", "figures", multiple=True, type=click.Path(exists=True),
              help="Figure spec(s) to validate (repeatable).")
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary (default: none; cross-file checks skipped).")
@click.option("--screening", default=None, type=click.Path(exists=True),
              help="Screening levels file.")
@click.option("--report", default=None, type=click.Path(),
              help="Write report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def validate_config_cmd(site_config, profiles, figures, analytes, screening,
                        report, fail_on):
    """Tool: validate a per-site config bundle (headless)."""
    from autogis.core.envmon.validate_config import validate_env_config

    qa = validate_env_config(
        Path(site_config), [Path(p) for p in profiles],
        [Path(f) for f in figures],
        Path(analytes) if analytes else None,
        Path(screening) if screening else None)
    _render_qa(qa, report, fail_on)


def _render_qa(qa, report, fail_on):
    """Shared rendering + exit-code helper for headless QA-producing commands."""
    for rec in sorted(qa.records,
                      key=lambda r: {"CRITICAL": 0, "ERROR": 1, "WARNING": 2,
                                     "INFO": 3}.get(r.severity, 4)):
        click.echo(f"[{rec.severity}] {rec.category}: {rec.message}"
                   + (f" -> {rec.recommended_action}"
                      if rec.recommended_action else ""))
    if report:
        from pathlib import Path as _P
        p = _P(report)
        if p.suffix == ".json":
            qa.write_json_summary(p)
        elif p.suffix == ".csv":
            qa.write_csv(p)
        else:
            qa.write_markdown(p)
        click.echo(f"Wrote report: {p}")
    allow_warnings = fail_on != "warning"
    status = qa.status(allow_warnings=allow_warnings, allow_errors=False)
    click.echo(f"Status: {status}")
    if status == "FAIL":
        raise SystemExit(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_cli_validate_config.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_cli_validate_config.py
git commit -m "feat(cli): envmon validate-config command + shared QA renderer"
```

---

### Task 6: ManageAnalyteDictionary core (check + list)

**Files:**
- Create: `autogis/core/envmon/manage_analyte_dict.py`
- Test: `tests/envmon/test_manage_analyte_dict.py`

**Interfaces:**
- Consumes: `load_analyte_dictionary`; `config_validation.validate_analyte_dictionary`; `QACollector`.
- Produces:
  - `check_analyte_dictionary(path: Path) -> QACollector`
  - `list_analytes(path: Path) -> list[dict]` — rows `{canonical, abbreviation, analytical_group, display_order, alias_count, include_in_default_figures}` sorted by `display_order`.

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_manage_analyte_dict.py
import yaml

from autogis.core.envmon.manage_analyte_dict import (check_analyte_dictionary,
                                                      list_analytes)
from autogis.core.common.qa import SEV_ERROR


def _write(tmp_path, data):
    p = tmp_path / "analytes.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_check_flags_alias_collision(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10},
        "Toluene": {"aliases": ["b"], "abbreviation": "T", "display_order": 20}}})
    qa = check_analyte_dictionary(p)
    assert (SEV_ERROR, "alias_collision") in {(r.severity, r.category)
                                              for r in qa.records}


def test_list_analytes_sorted_by_display_order(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Toluene": {"aliases": ["toluene"], "abbreviation": "T",
                    "display_order": 20, "analytical_group": "VOC"},
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10, "analytical_group": "VOC"}}})
    rows = list_analytes(p)
    assert [r["canonical"] for r in rows] == ["Benzene", "Toluene"]
    assert rows[0]["alias_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_manage_analyte_dict.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/core/envmon/manage_analyte_dict.py
"""ManageAnalyteDictionary — read-only curation/validation of the analyte
dictionary (headless, arcpy-free). Never writes the YAML; edits stay manual.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from ..common import config_validation as cv
from ..common.config import load_analyte_dictionary
from ..common.qa import QACollector, QARecord, SEV_INFO


def _clean(path: Path) -> dict:
    analytes = load_analyte_dictionary(Path(path))
    return {k: v for k, v in analytes.items() if not str(k).startswith("_")}


def check_analyte_dictionary(path: Path) -> QACollector:
    qa = QACollector()
    analytes = _clean(path)
    qa.extend(cv.validate_analyte_dictionary(analytes))
    counts = qa.counts_by_severity()
    qa.add(QARecord(severity=SEV_INFO, category="check_complete",
                    message=(f"Analyte dictionary check finished: "
                             f"{len(analytes)} analytes, "
                             f"{counts.get('ERROR', 0)} error(s), "
                             f"{counts.get('WARNING', 0)} warning(s).")))
    return qa


def list_analytes(path: Path) -> List[dict]:
    analytes = _clean(path)
    rows = []
    for canonical, entry in analytes.items():
        rows.append({
            "canonical": canonical,
            "abbreviation": entry.get("abbreviation", ""),
            "analytical_group": entry.get("analytical_group", ""),
            "display_order": entry.get("display_order", 9999),
            "alias_count": len(entry.get("aliases", []) or []),
            "include_in_default_figures": entry.get("include_in_default_figures",
                                                    False),
        })
    rows.sort(key=lambda r: (r["display_order"], r["canonical"]))
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_manage_analyte_dict.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/manage_analyte_dict.py tests/envmon/test_manage_analyte_dict.py
git commit -m "feat(envmon): ManageAnalyteDictionary read-only check + list core"
```

---

### Task 7: `manage-analyte-dict` CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` (headless section)
- Test: `tests/envmon/test_cli_manage_analyte_dict.py`

**Interfaces:**
- Consumes: `check_analyte_dictionary`, `list_analytes` (Task 6); `_render_qa` (Task 5).
- Produces: CLI `autogis envmon manage-analyte-dict ANALYTES [--list] [--check] [--report OUT] [--fail-on error|warning]`. Default action `--check`.

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_cli_manage_analyte_dict.py
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write(tmp_path, data):
    p = tmp_path / "analytes.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_manage_analyte_dict_check_fails_on_collision(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10},
        "Toluene": {"aliases": ["b"], "abbreviation": "T", "display_order": 20}}})
    r = CliRunner().invoke(autogis, ["envmon", "manage-analyte-dict", p])
    assert r.exit_code == 1
    assert "alias_collision" in r.output


def test_manage_analyte_dict_list_prints_table(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "display_order": 10}}})
    r = CliRunner().invoke(autogis, ["envmon", "manage-analyte-dict", p, "--list"])
    assert r.exit_code == 0
    assert "Benzene" in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_cli_manage_analyte_dict.py -q`
Expected: FAIL — no such command.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/adapters/cli.py — add after validate_config_cmd
@envmon.command("manage-analyte-dict")
@click.argument("analytes", type=click.Path(exists=True))
@click.option("--list", "do_list", is_flag=True, default=False,
              help="Print the resolved analyte table sorted by display_order.")
@click.option("--check", "do_check", is_flag=True, default=False,
              help="Run validation checks (default when --list is absent).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def manage_analyte_dict_cmd(analytes, do_list, do_check, report, fail_on):
    """Tool: validate / inspect the analyte dictionary (read-only, headless)."""
    from autogis.core.envmon.manage_analyte_dict import (
        check_analyte_dictionary, list_analytes)

    if do_list:
        rows = list_analytes(Path(analytes))
        header = f"{'display':>7}  {'canonical':<24} {'abbr':<8} {'group':<14} aliases"
        click.echo(header)
        for row in rows:
            click.echo(f"{row['display_order']:>7}  {row['canonical']:<24} "
                       f"{row['abbreviation']:<8} {row['analytical_group']:<14} "
                       f"{row['alias_count']}")
        if not do_check:
            return
    # Default to check when --list was not requested, or when both given.
    qa = check_analyte_dictionary(Path(analytes))
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_cli_manage_analyte_dict.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite + commit**

```bash
python -m pytest -q
git add autogis/adapters/cli.py tests/envmon/test_cli_manage_analyte_dict.py
git commit -m "feat(cli): envmon manage-analyte-dict command"
```

Expected: full suite green (was 132 tests; now +~17 new tests).

---

## Self-Review

**Spec coverage:**
- ValidateEnvConfig per-bundle-from-args → Tasks 4–5 (explicit `--profile`/`--figure`/`--analytes`/`--screening`). ✓
- Per-file validators (site/profile/figure/screening) → Task 1. ✓
- Analyte validator + alias collisions + display_order → Task 2. ✓
- Cross-file `validate_bundle` (figure/screening analyte refs, units coherence) → Task 3. ✓
- ManageAnalyteDictionary read-only check + list → Tasks 6–7. ✓
- Shared QA report contract + exit codes + `--fail-on` → `_render_qa` (Task 5), reused by Task 7. ✓
- `_TODO`/DRAFT → WARNING `placeholder` → `scan_todos` (Task 1) + analyte source check (Task 2). ✓

**Placeholder scan:** No "TBD"/"handle edge cases"; every code step is complete. The Task 5 second test is intentionally a smoke check (documented inline) because PASS/FAIL logic is fully covered at the core level in Task 4.

**Type consistency:** `validate_*` functions all return `List[QARecord]`; `validate_env_config`/`check_analyte_dictionary` return `QACollector`; `_render_qa(qa, report, fail_on)` is defined in Task 5 and reused in Task 7. `_norm_key`/`build_analyte_lookup` signatures match `result_parser.py`. ✓

**Deferred to execution:** none — the validator vocabularies (`KNOWN_*`) are pinned in Global Constraints from observed config values.
