# ValidateAndConvertUnits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a headless, arcpy-free unit registry + converter and a `validate-units` tool that flags unknown, cross-dimension, and convertible-mismatch unit problems across the analyte dictionary and screening-level configs.

**Architecture:** A pure unit registry (`core/common/units.py`) provides `normalize_unit`/`convert`/`same_dimension`. A pure validator (`config_validation.validate_units`) consumes already-loaded config dicts and returns `QARecord`s. An orchestrator (`core/envmon/validate_units.py`) handles file I/O defensively and a `validate-units` CLI command renders results. The live screening path is untouched in v1.

**Tech Stack:** Python 3, `click` (CLI), `pytest`, `PyYAML` (test fixtures only). No arcpy/arcgis.

## Global Constraints

- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` present (ADR-002).
- New config-validation logic follows the existing pattern: pure functions returning `List[QARecord]`, collect-all, **never raise** on bad data; the orchestrator owns file I/O (ADR-001).
- Findings are emitted via `QACollector` / `QARecord` from `autogis/core/common/qa.py`. Severities: `SEV_INFO`, `SEV_WARNING`, `SEV_ERROR`, `SEV_CRITICAL`.
- Tests join the arcpy-free suite; run with `python -m pytest -q`.
- `ppb`/`ppm` are deliberately NOT registered (dimension-ambiguous) — they must resolve to `None`.
- Never mutate raw source units; v1 does not modify `result_parser.py` or `table_normalizer.py`.

---

## File Structure

- Create `autogis/core/common/units.py` — registry + `UnitError` + `normalize_unit`/`dimension_of`/`same_dimension`/`convert`.
- Modify `autogis/core/common/config_validation.py` — add `validate_units(analytes, screening)`.
- Create `autogis/core/envmon/validate_units.py` — orchestrator `validate_units_config(analytes_path, screening_path)`.
- Modify `autogis/adapters/cli.py` — add `validate-units` command (after `manage-analyte-dict`, before `_render_qa`).
- Create `tests/test_units.py` — registry/converter tests.
- Create `tests/envmon/test_validate_units.py` — validator + orchestrator tests.
- Create `tests/envmon/test_cli_validate_units.py` — CLI tests.

---

### Task 1: Unit registry + converter

**Files:**
- Create: `autogis/core/common/units.py`
- Test: `tests/test_units.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `UNIT_REGISTRY: dict[str, tuple[str, float]]` — canonical unit -> (dimension, factor-to-base).
  - `class UnitError(ValueError)`.
  - `normalize_unit(u) -> Optional[str]` — canonical key or `None`.
  - `dimension_of(u) -> Optional[str]`.
  - `same_dimension(a, b) -> bool`.
  - `convert(value: float, from_u: str, to_u: str) -> float` — raises `UnitError` on unknown unit or cross-dimension.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_units.py`:

```python
import pytest

from autogis.core.common.units import (
    UnitError, normalize_unit, dimension_of, same_dimension, convert)


def test_normalize_handles_micro_case_and_whitespace():
    assert normalize_unit(" ug/l ") == "ug/L"
    assert normalize_unit("UG/L") == "ug/L"
    assert normalize_unit("µg/L") == "ug/L"   # U+00B5 micro sign
    assert normalize_unit("μg/L") == "ug/L"   # U+03BC greek mu


def test_normalize_unknown_and_ambiguous_return_none():
    assert normalize_unit("ppb") is None
    assert normalize_unit("ppm") is None
    assert normalize_unit("qg/L") is None
    assert normalize_unit(None) is None


def test_dimension_and_same_dimension():
    assert dimension_of("mg/L") == "aqueous"
    assert dimension_of("mg/kg") == "soil"
    assert same_dimension("ug/L", "mg/L") is True
    assert same_dimension("mg/L", "mg/kg") is False
    assert same_dimension("ppb", "mg/L") is False


def test_convert_within_dimension_both_directions():
    assert convert(1.0, "mg/L", "ug/L") == 1000.0
    assert convert(1000.0, "ug/L", "mg/L") == 1.0
    assert convert(2.0, "mg/kg", "ug/kg") == 2000.0


def test_convert_unknown_unit_raises():
    with pytest.raises(UnitError):
        convert(1.0, "ppb", "ug/L")


def test_convert_cross_dimension_raises():
    with pytest.raises(UnitError):
        convert(1.0, "mg/L", "mg/kg")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_units.py -q`
Expected: FAIL (`ModuleNotFoundError: autogis.core.common.units`).

- [ ] **Step 3: Write the implementation**

Create `autogis/core/common/units.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_units.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/common/units.py tests/test_units.py
git commit -m "feat(common): canonical unit registry + arcpy-free converter"
```

---

### Task 2: `validate_units` config validator

**Files:**
- Modify: `autogis/core/common/config_validation.py`
- Test: `tests/envmon/test_validate_units.py` (validator portion)

**Interfaces:**
- Consumes: `units.normalize_unit`, `units.same_dimension`, `units.convert` (Task 1); existing `build_analyte_lookup`, `_norm_key` from `result_parser`; existing `_rec`, `SEV_ERROR`, `SEV_WARNING` in `config_validation`.
- Produces: `validate_units(analytes: dict, screening: dict) -> List[QARecord]`. Categories: `unknown_unit` (ERROR), `cross_dimension` (ERROR), `convertible_mismatch` (WARNING).

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_validate_units.py`:

```python
from autogis.core.common.config_validation import validate_units
from autogis.core.common.qa import SEV_ERROR, SEV_WARNING


def _cats(records):
    return {(r.severity, r.category) for r in records}


def _analytes(units_by_matrix):
    return {"Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                        "default_units_by_matrix": units_by_matrix}}


def test_unknown_screening_unit_is_error():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "qg/L"}}}
    assert (SEV_ERROR, "unknown_unit") in _cats(validate_units(analytes, screening))


def test_unknown_dictionary_unit_is_error():
    analytes = _analytes({"GW": "ppb"})
    assert (SEV_ERROR, "unknown_unit") in _cats(validate_units(analytes, {}))


def test_cross_dimension_is_error():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "mg/kg"}}}
    assert (SEV_ERROR, "cross_dimension") in _cats(validate_units(analytes, screening))


def test_convertible_mismatch_is_warning():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "mg/L"}}}
    cats = _cats(validate_units(analytes, screening))
    assert (SEV_WARNING, "convertible_mismatch") in cats
    assert (SEV_ERROR, "cross_dimension") not in cats


def test_matching_units_emit_nothing():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "ug/L"}}}
    assert validate_units(analytes, screening) == []


def test_missing_screening_units_skipped():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None}}}
    assert validate_units(analytes, screening) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_validate_units.py -q`
Expected: FAIL (`ImportError: cannot import name 'validate_units'`).

- [ ] **Step 3: Add the implementation**

Append to `autogis/core/common/config_validation.py` (after `validate_bundle`):

```python
def validate_units(analytes: dict, screening: dict) -> List[QARecord]:
    """Flag unknown, cross-dimension, and convertible-mismatch unit problems.

    Pure: consumes already-loaded dicts, returns records, never raises. Analyte
    names are matched across configs via the shared analyte lookup so aliases
    line up. Missing-units / not-in-dictionary cases are owned by the existing
    validators and skipped here.
    """
    from ..envmon.result_parser import build_analyte_lookup, _norm_key  # avoid circular import
    from .units import normalize_unit, same_dimension, convert

    out: List[QARecord] = []
    clean = {k: v for k, v in (analytes or {}).items() if not str(k).startswith("_")}
    lookup = build_analyte_lookup(clean)   # {_norm_key: canonical}

    # 1. Unknown units in analyte-dictionary defaults.
    for canonical, entry in clean.items():
        if not isinstance(entry, dict):
            continue
        for matrix, unit in (entry.get("default_units_by_matrix", {}) or {}).items():
            if normalize_unit(unit) is None:
                out.append(_rec(SEV_ERROR, "unknown_unit",
                                f"analyte {canonical!r} matrix {matrix}: "
                                f"unrecognized unit {unit!r}",
                                action="add the unit to the registry or fix the config",
                                analyte_name=str(canonical)))

    # 2. Screening units: unknown, then cross-check against the dict default.
    for matrix, entries in (screening or {}).items():
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            scr_u = entry.get("units")
            if scr_u is None:
                continue   # missing units owned by validate_screening_levels
            if normalize_unit(scr_u) is None:
                out.append(_rec(SEV_ERROR, "unknown_unit",
                                f"screening {matrix}/{name}: unrecognized unit "
                                f"{scr_u!r}",
                                action="add the unit to the registry or fix the config",
                                analyte_name=str(name)))
                continue
            canonical = lookup.get(_norm_key(str(name)))
            if canonical is None:
                continue   # not-in-dictionary owned by validate_bundle
            dict_u = ((clean.get(canonical, {}) or {})
                      .get("default_units_by_matrix", {}) or {}).get(matrix)
            if not dict_u or normalize_unit(dict_u) is None:
                continue   # nothing to compare / dict side already flagged
            if normalize_unit(dict_u) == normalize_unit(scr_u):
                continue
            if same_dimension(dict_u, scr_u):
                factor = convert(1.0, scr_u, dict_u)
                out.append(_rec(SEV_WARNING, "convertible_mismatch",
                                f"screening {matrix}/{name}: units {scr_u!r} differ "
                                f"from dictionary default {dict_u!r} "
                                f"(1 {scr_u} = {factor:g} {dict_u})",
                                action="confirm results and screening levels share a "
                                       "unit basis",
                                analyte_name=str(name)))
            else:
                out.append(_rec(SEV_ERROR, "cross_dimension",
                                f"screening {matrix}/{name}: units {scr_u!r} and "
                                f"dictionary default {dict_u!r} are different "
                                f"dimensions; values are not comparable",
                                action="fix the unit in one config",
                                analyte_name=str(name)))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_validate_units.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/common/config_validation.py tests/envmon/test_validate_units.py
git commit -m "feat(envmon): validate_units — unknown/cross-dimension/convertible checks"
```

---

### Task 3: Orchestrator `validate_units_config`

**Files:**
- Create: `autogis/core/envmon/validate_units.py`
- Test: `tests/envmon/test_validate_units.py` (orchestrator portion — append)

**Interfaces:**
- Consumes: `validate_config._safe` (existing defensive loader), `config.load_analyte_dictionary`, `config.load_screening_levels`, `config_validation.validate_units` (Task 2), `QACollector`/`QARecord`/`SEV_INFO`.
- Produces: `validate_units_config(analytes_path, screening_path) -> QACollector`. Always appends a closing `(SEV_INFO, "validation_complete")` record.

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_validate_units.py`:

```python
import yaml

from autogis.core.envmon.validate_units import validate_units_config
from autogis.core.common.qa import SEV_INFO


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_orchestrator_flags_cross_dimension(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {
        "GW": {"Benzene": {"value": None, "units": "mg/kg"}}}})
    qa = validate_units_config(analytes, screening)
    cats = {(r.severity, r.category) for r in qa.records}
    assert (SEV_ERROR, "cross_dimension") in cats
    assert (SEV_INFO, "validation_complete") in cats


def test_orchestrator_bad_file_becomes_load_error(tmp_path):
    bad = tmp_path / "analytes.yaml"
    bad.write_text(": : not valid yaml : :", encoding="utf-8")
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {}})
    qa = validate_units_config(bad, screening)
    assert (SEV_ERROR, "load_error") in {(r.severity, r.category) for r in qa.records}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_validate_units.py -q`
Expected: FAIL (`ModuleNotFoundError: autogis.core.envmon.validate_units`).

- [ ] **Step 3: Write the implementation**

Create `autogis/core/envmon/validate_units.py`:

```python
"""ValidateAndConvertUnits — config unit-integrity checks (headless, arcpy-free).

Loads the analyte dictionary and screening-level configs, runs the pure
``validate_units`` validator into a single QACollector, and adds a closing INFO
summary. File loads are defensive (a failure becomes an ERROR record rather than
an exception), reusing ``validate_config._safe``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..common import config_validation as cv
from ..common.config import load_analyte_dictionary, load_screening_levels
from ..common.qa import QACollector, QARecord, SEV_INFO
from .validate_config import _safe


def validate_units_config(analytes_path: Optional[Path],
                          screening_path: Optional[Path]) -> QACollector:
    qa = QACollector()
    analytes: dict = {}
    screening: dict = {}

    if analytes_path:
        analytes = _safe(qa, f"analyte dictionary {Path(analytes_path).name}",
                         lambda: load_analyte_dictionary(Path(analytes_path))) or {}
    if screening_path:
        screening = _safe(qa, f"screening levels {Path(screening_path).name}",
                          lambda: load_screening_levels(Path(screening_path))) or {}

    if analytes or screening:
        qa.extend(cv.validate_units(analytes, screening))

    counts = qa.counts_by_severity()
    qa.add(QARecord(severity=SEV_INFO, category="validation_complete",
                    message=(f"Unit validation finished: "
                             f"{counts.get('ERROR', 0)} error(s), "
                             f"{counts.get('WARNING', 0)} warning(s).")))
    return qa
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_validate_units.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/validate_units.py tests/envmon/test_validate_units.py
git commit -m "feat(envmon): validate_units_config orchestrator"
```

---

### Task 4: `validate-units` CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` (add command after `manage_analyte_dict_cmd`, before `_render_qa` at line 162)
- Test: `tests/envmon/test_cli_validate_units.py`

**Interfaces:**
- Consumes: `validate_units_config` (Task 3), existing `_render_qa`, the `envmon` click group.
- Produces: CLI `autogis envmon validate-units --analytes PATH --screening PATH [--report PATH] [--fail-on error|warning]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_cli_validate_units.py`:

```python
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_validate_units_cli_fails_on_cross_dimension(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {
        "GW": {"Benzene": {"value": None, "units": "mg/kg"}}}})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-units", "--analytes", analytes,
        "--screening", screening])
    assert r.exit_code == 1
    assert "cross_dimension" in r.output


def test_validate_units_cli_passes_clean(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {
        "GW": {"Benzene": {"value": None, "units": "ug/L"}}}})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-units", "--analytes", analytes,
        "--screening", screening, "--fail-on", "error"])
    assert r.exit_code == 0
    assert "Status: PASS" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_cli_validate_units.py -q`
Expected: FAIL (`Error: No such command 'validate-units'`, exit code 2).

- [ ] **Step 3: Add the command**

Insert into `autogis/adapters/cli.py` immediately after the `manage_analyte_dict_cmd` function ends (the blank line before `def _render_qa` at line 162):

```python
@envmon.command("validate-units")
@click.option("--analytes", required=True, type=click.Path(exists=True),
              help="Analyte dictionary (provides default_units_by_matrix).")
@click.option("--screening", required=True, type=click.Path(exists=True),
              help="Screening levels file.")
@click.option("--report", default=None, type=click.Path(),
              help="Write report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def validate_units_cmd(analytes, screening, report, fail_on):
    """Tool: validate analyte/screening units for convertibility (headless)."""
    from autogis.core.envmon.validate_units import validate_units_config

    qa = validate_units_config(Path(analytes), Path(screening))
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_cli_validate_units.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all prior tests + the 16 new ones; was 151, now 167).

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_cli_validate_units.py
git commit -m "feat(cli): envmon validate-units command"
```

---

## Self-Review

- **Spec coverage:** registry/converter (Task 1), `validate_units` with all three categories (Task 2), orchestrator with defensive load + closing INFO (Task 3), CLI with required `--analytes`/`--screening` and `_render_qa` (Task 4), `ppb`/`ppm` excluded (Task 1 tests), no live-path change (no task touches `result_parser`/`table_normalizer`). All spec sections map to a task.
- **Placeholder scan:** none — every code/test step is complete.
- **Type consistency:** `normalize_unit`/`convert`/`same_dimension` signatures match across Tasks 1-2; `validate_units(analytes, screening)` matches across Tasks 2-3; `validate_units_config(analytes_path, screening_path)` matches across Tasks 3-4. QA categories (`unknown_unit`, `cross_dimension`, `convertible_mismatch`, `load_error`, `validation_complete`) consistent across tasks and tests.
