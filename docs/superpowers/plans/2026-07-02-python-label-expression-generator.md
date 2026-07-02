# GeneratePythonLabelExpressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `autogis envmon generate-python-labels` (Tool 5.4b), a headless sibling of `generate-arcade-labels` (Tool 5.4) that emits Esri's Python label-expression syntax instead of Arcade, and fold in the README/ADR/CLAUDE.md documentation this PR also needs to carry.

**Architecture:** Extract the field-naming logic shared by both generators into `autogis/core/envmon/label_expression_common.py` (behavior-preserving refactor of `arcade_label_generator.py`), then add `autogis/core/envmon/python_label_generator.py` following the same shape as the Arcade module, wire it into the CLI and capability registry, and update docs.

**Tech Stack:** Python 3, stdlib + `dataclasses` + `json` only (no new dependency), `click` (existing CLI framework), `pytest`.

## Global Constraints

- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` present (ADR-0002) — every file this plan touches or creates stays in that set.
- No new dependency — stdlib + dataclasses only, matching `arcade_label_generator.py`.
- Field-naming convention (`derive_label_fields`) MUST produce byte-identical field names for the Arcade and Python variants given the same `(analyte, field_prefix)` — that parity is enforced by a test, not just by sharing code.
- Esri's `labelClass.expressionEngine` value for Python label expressions is the literal string `'Python'` (verified against `doc.esri.com` "Specify text for labels" examples and the arcpy `LabelClass` reference's `expressionEngine = 'Python'` example) — **not** `'PYTHON3'`. Use `"Python"` everywhere this plan emits that value.
- Esri Python label-expression syntax (verified from the same sources): a `def FindLabel([Field1], [Field2], ...):` function; fields are referenced as bracket tokens `[FieldName]` in both the parameter list and the body (commonly via `S = [FieldName]` then operating on `S`); the function returns the label string.
- Test command: `python -m pytest -q` (run from the worktree root — this session's worktree, not the shared main tree).
- Before creating the ADR file in Task 6, list `docs/adr/` and use the actual next-free number on `main` — a prior batch (ADR-0032) was renumbered after a collision from trusting a stale number.

---

### Task 1: Shared field-derivation module + behavior-preserving Arcade refactor

**Files:**
- Create: `autogis/core/envmon/label_expression_common.py`
- Create: `tests/envmon/test_label_expression_common.py`
- Modify: `autogis/core/envmon/arcade_label_generator.py`

**Interfaces:**
- Produces: `LabelExpressionType` (class with 4 string constants: `RESULT_WITH_UNITS`, `EXCEEDANCE_CALLOUT`, `ND_CALLOUT`, `WELL_ID_ONLY`), `LabelFields` (dataclass: `layer_base: str`, `id_field: str`, `value_field: str`, `units_field: str`, `sl_field: str`), `derive_label_fields(analyte: str, field_prefix: str = "") -> LabelFields`. Both `label_expression_common.py` and (via re-export) `arcade_label_generator.py` expose `LabelExpressionType`.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_label_expression_common.py`:

```python
"""Tests for label_expression_common module (shared by arcade + python label generators)."""
from autogis.core.envmon.label_expression_common import (
    LabelExpressionType,
    LabelFields,
    derive_label_fields,
)


def test_derive_label_fields_returns_label_fields_instance():
    result = derive_label_fields("Benzene")
    assert isinstance(result, LabelFields)


def test_derive_label_fields_value_field():
    result = derive_label_fields("Benzene")
    assert result.value_field == "Benzene_Value"


def test_derive_label_fields_units_field():
    result = derive_label_fields("Benzene")
    assert result.units_field == "Benzene_Units"


def test_derive_label_fields_sl_field():
    result = derive_label_fields("Benzene")
    assert result.sl_field == "Benzene_SL"


def test_derive_label_fields_id_field_no_prefix():
    result = derive_label_fields("Benzene")
    assert result.id_field == "LocationID"


def test_derive_label_fields_layer_base():
    result = derive_label_fields("Benzene")
    assert result.layer_base == "Benzene"


def test_derive_label_fields_with_field_prefix():
    result = derive_label_fields("Benzene", field_prefix="Env_")
    assert result.value_field == "Env_Benzene_Value"
    assert result.units_field == "Env_Benzene_Units"
    assert result.sl_field == "Env_Benzene_SL"
    assert result.id_field == "Env_LocationID"


def test_derive_label_fields_sanitizes_spaces_commas_slashes():
    result = derive_label_fields("cis-1,2-DCE/PCE")
    assert " " not in result.layer_base
    assert "," not in result.layer_base
    assert "/" not in result.layer_base


def test_label_expression_type_constants():
    assert LabelExpressionType.RESULT_WITH_UNITS == "RESULT_WITH_UNITS"
    assert LabelExpressionType.EXCEEDANCE_CALLOUT == "EXCEEDANCE_CALLOUT"
    assert LabelExpressionType.ND_CALLOUT == "ND_CALLOUT"
    assert LabelExpressionType.WELL_ID_ONLY == "WELL_ID_ONLY"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_label_expression_common.py -v`
Expected: FAIL (or ERROR) — `ModuleNotFoundError: No module named 'autogis.core.envmon.label_expression_common'`

- [ ] **Step 3: Create `label_expression_common.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_label_expression_common.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Refactor `arcade_label_generator.py` to use the shared module**

In `autogis/core/envmon/arcade_label_generator.py`:

Replace the imports block (currently `from __future__ import annotations` / `import json` / `from dataclasses import dataclass` / `from pathlib import Path` / `from typing import Optional`) by adding one import line after `from typing import Optional`:

```python
from autogis.core.envmon.label_expression_common import (
    LabelExpressionType, derive_label_fields,
)
```

Delete the inline `class LabelExpressionType:` definition (the block that currently defines `RESULT_WITH_UNITS`, `EXCEEDANCE_CALLOUT`, `ND_CALLOUT`, `WELL_ID_ONLY`) — it now comes from the import above.

In `generate_arcade_labels()`, replace this block:

```python
        # Derive field names from the analyte name + prefix
        safe_name = analyte.replace(" ", "_").replace(",", "").replace("/", "_")
        value_field = f"{field_prefix}{safe_name}_Value"
        units_field = f"{field_prefix}{safe_name}_Units"
        sl_field = f"{field_prefix}{safe_name}_SL"
        id_field = f"{field_prefix}LocationID"
        layer_base = safe_name
```

with:

```python
        # Derive field names from the analyte name + prefix
        fields = derive_label_fields(analyte, field_prefix)
        value_field = fields.value_field
        units_field = fields.units_field
        sl_field = fields.sl_field
        id_field = fields.id_field
        layer_base = fields.layer_base
```

The rest of `generate_arcade_labels()` (the four `specs.append(...)` blocks) is unchanged — it already references `value_field`/`units_field`/`sl_field`/`id_field`/`layer_base` as local names.

- [ ] **Step 6: Run the full existing Arcade test suite to confirm behavior is unchanged**

Run: `python -m pytest tests/envmon/test_arcade_label_generator.py -v`
Expected: PASS (all tests, unmodified from before this refactor — same count as before Step 5)

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/label_expression_common.py autogis/core/envmon/arcade_label_generator.py tests/envmon/test_label_expression_common.py
git commit -m "refactor(envmon): extract label field-name derivation into shared module"
```

---

### Task 2: Python label-expression builders

**Files:**
- Create: `autogis/core/envmon/python_label_generator.py`
- Create: `tests/envmon/test_python_label_generator.py`

**Interfaces:**
- Consumes: nothing from Task 1's public API yet (pure string builders).
- Produces: `build_result_label_expression(value_field: str, units_field: str, *, nd_text: str = "ND") -> str`, `build_exceedance_callout_expression(value_field: str, sl_field: str, units_field: str, *, nd_text: str = "ND", exceed_suffix: str = "**") -> str`, `_build_nd_callout_expression(value_field: str, units_field: str, *, nd_text: str = "ND") -> str`, `_build_well_id_expression(analyte_field: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_python_label_generator.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autogis.core.envmon.python_label_generator'`

- [ ] **Step 3: Create `python_label_generator.py` with the four builders**

```python
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

    Example output (Python label-expression code, run via Pro's 'Python' engine):
        def FindLabel ( [ResultValue], [ReportedUnits] ):
            v = [ResultValue]
            if v is None or v == "" or v == "ND":
                return "ND"
            return "{:,.2f} {}".format(float(v), [ReportedUnits])
    """
    return (
        f'def FindLabel ( [{value_field}], [{units_field}] ):\n'
        f'    v = [{value_field}]\n'
        f'    if v is None or v == "" or v == "{nd_text}":\n'
        f'        return "{nd_text}"\n'
        f'    return "{{:,.2f}} {{}}".format(float(v), [{units_field}])'
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

    Example output (Python label-expression code):
        def FindLabel ( [ResultValue], [ScreeningLevel], [ReportedUnits] ):
            v = [ResultValue]
            sl = [ScreeningLevel]
            if v is None or v == "" or v == "ND":
                return "ND"
            num = float(v)
            if sl not in (None, "") and num > float(sl):
                return "{:,.2f} {}**".format(num, [ReportedUnits])
            return "{:,.2f} {}".format(num, [ReportedUnits])
    """
    return (
        f'def FindLabel ( [{value_field}], [{sl_field}], [{units_field}] ):\n'
        f'    v = [{value_field}]\n'
        f'    sl = [{sl_field}]\n'
        f'    if v is None or v == "" or v == "{nd_text}":\n'
        f'        return "{nd_text}"\n'
        f'    num = float(v)\n'
        f'    if sl not in (None, "") and num > float(sl):\n'
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/python_label_generator.py tests/envmon/test_python_label_generator.py
git commit -m "feat(envmon): Python label-expression builders (Tool 5.4b, part 1)"
```

---

### Task 3: `generate_python_labels()` assembly function

**Files:**
- Modify: `autogis/core/envmon/python_label_generator.py`
- Modify: `tests/envmon/test_python_label_generator.py`

**Interfaces:**
- Consumes: `derive_label_fields` (Task 1), the four builders (Task 2), `PythonLabelSpec`, `LabelExpressionType`.
- Produces: `generate_python_labels(analytes: list[str], *, field_prefix: str = "") -> list[PythonLabelSpec]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_python_label_generator.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_python_labels'`

- [ ] **Step 3: Add `generate_python_labels()` to `python_label_generator.py`**

Append after the `_build_well_id_expression` function:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: PASS (19 tests)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/python_label_generator.py tests/envmon/test_python_label_generator.py
git commit -m "feat(envmon): generate_python_labels assembly function (Tool 5.4b, part 2)"
```

---

### Task 4: `write_label_expressions()` JSON serialization

**Files:**
- Modify: `autogis/core/envmon/python_label_generator.py`
- Modify: `tests/envmon/test_python_label_generator.py`

**Interfaces:**
- Consumes: `PythonLabelSpec`, `EXPRESSION_ENGINE` (both Task 2/3).
- Produces: `write_label_expressions(specs: list[PythonLabelSpec], out_path: Path) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_python_label_generator.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: FAIL — `ImportError: cannot import name 'write_label_expressions'`

- [ ] **Step 3: Add `write_label_expressions()` to `python_label_generator.py`**

Append at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: PASS (24 tests)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/python_label_generator.py tests/envmon/test_python_label_generator.py
git commit -m "feat(envmon): write_label_expressions JSON output (Tool 5.4b, part 3)"
```

---

### Task 5: CLI wiring + capability registration

**Files:**
- Modify: `autogis/adapters/cli.py:988` (immediately after the existing `generate_arcade_labels_cmd` function)
- Modify: `autogis/runtime/capabilities.py:44` (immediately after the `"generate-arcade-labels"` entry)
- Modify: `tests/envmon/test_python_label_generator.py`

**Interfaces:**
- Consumes: `generate_python_labels`, `write_label_expressions` (Task 3/4), `QACollector`/`SEV_INFO` (`autogis.core.common.qa`, already used by the Arcade command), `_render_qa` (already defined in `cli.py`, used by the Arcade command).
- Produces: `envmon generate-python-labels` CLI command; `TOOLS["generate-python-labels"] = Runtime.CLOUD`.

- [ ] **Step 1: Write the failing test**

Append to `tests/envmon/test_python_label_generator.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v -k generate_python_labels_in_help`
Expected: FAIL — `assert "generate-python-labels" in result.output` fails (command not registered)

- [ ] **Step 3: Add the CLI command to `cli.py`**

In `autogis/adapters/cli.py`, immediately after the end of `generate_arcade_labels_cmd` (the function ends with the `_render_qa(qa, report, "error")` call, currently around line 987, followed by a blank line before the next `@envmon.command`), insert:

```python
@envmon.command("generate-python-labels")
@click.option(
    "--analytes", "analytes_str", required=True,
    help="Comma-separated analyte names (e.g. 'Benzene,PCE,Toluene').",
)
@click.option(
    "--field-prefix", default="",
    help="Optional field name prefix (e.g. 'Env_').",
)
@click.option(
    "--out", required=True, type=click.Path(),
    help="Output JSON file path.",
)
@click.option(
    "--report", default=None, type=click.Path(),
    help="Optional QA report output path.",
)
def generate_python_labels_cmd(analytes_str, field_prefix, out, report):
    """Tool 5.4b: generate Python label expressions for ArcGIS Pro layers (headless)."""
    from autogis.core.common.qa import QACollector, SEV_INFO
    from autogis.core.envmon.python_label_generator import (
        generate_python_labels, write_label_expressions,
    )

    analytes = [a.strip() for a in analytes_str.split(",") if a.strip()]
    if not analytes:
        raise click.UsageError("--analytes must contain at least one analyte name.")

    specs = generate_python_labels(analytes, field_prefix=field_prefix)
    write_label_expressions(specs, Path(out))

    qa = QACollector()
    qa.add(
        SEV_INFO, "python_labels_written",
        f"{len(specs)} expression(s) for {len(analytes)} analyte(s) → {out}",
    )
    click.echo(
        f"Written {len(specs)} Python expression(s) for {len(analytes)} "
        f"analyte(s) to: {out}"
    )
    _render_qa(qa, report, "error")
```

- [ ] **Step 4: Register the tool in `capabilities.py`**

In `autogis/runtime/capabilities.py`, immediately after the line `"generate-arcade-labels": Runtime.CLOUD,  # tool 5.4`, insert:

```python
    "generate-python-labels": Runtime.CLOUD,  # tool 5.4b
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_python_label_generator.py -v`
Expected: PASS (26 tests)

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS, no failures, no new errors (count should be the prior full-suite total plus the 35 tests added in Tasks 1–5: 9 in `test_label_expression_common.py` + 26 in `test_python_label_generator.py`)

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/cli.py autogis/runtime/capabilities.py tests/envmon/test_python_label_generator.py
git commit -m "feat(envmon): wire generate-python-labels CLI command (Tool 5.4b)"
```

---

### Task 6: README additions + ADR

**Files:**
- Modify: `README.md` (three insertions, detailed below)
- Create: `docs/adr/00NN-python-label-expression-generator.md` (NN = next free number — see Step 1)

**Interfaces:** None (documentation only).

- [ ] **Step 1: Determine the next free ADR number**

Run: `ls docs/adr | grep -E '^[0-9]{4}-' | sort | tail -5`

Take the highest 4-digit prefix present and add 1 (as of this plan being written, the highest is `0033-boring-log-db-and-attachment-index.md`, so the next number would be `0034` — **re-check at execution time**, since other work may have merged since).

- [ ] **Step 2: Insert the capability-table row in README.md**

Find this line (in the capability registry table):

```
| GenerateArcadeLabelExpressions | 5.4 | `envmon generate-arcade-labels` |
```

Insert immediately after it:

```
| GeneratePythonLabelExpressions | 5.4b | `envmon generate-python-labels` |
```

- [ ] **Step 3: Insert the CLI-runtime table row in README.md**

Find this line (in the CLI-to-runtime mapping table):

```
| `autogis envmon generate-arcade-labels` | CLOUD | `core/envmon/arcade_label_generator.py` |
```

Insert immediately after it:

```
| `autogis envmon generate-python-labels` | CLOUD | `core/envmon/python_label_generator.py` |
```

- [ ] **Step 4: Insert the quick-reference command in README.md**

Find this line (in the "Analysis & cartography extras" quick-reference block):

```
autogis envmon generate-arcade-labels --analytes "Benzene,PCE" --out <labels.json>
```

Insert immediately after it:

```
autogis envmon generate-python-labels --analytes "Benzene,PCE" --out <labels.json>
```

- [ ] **Step 5: Create the ADR**

Create `docs/adr/00NN-python-label-expression-generator.md` (substituting the real number from Step 1 for `NN`, and updating the two in-body `ADR-0034` references below to match):

```markdown
# ADR-0034: GeneratePythonLabelExpressions — sibling of the Arcade label generator

**Status:** Accepted

**Date:** 2026-07-02

## Context

`GenerateArcadeLabelExpressions` (Tool 5.4, `autogis envmon generate-arcade-labels`)
emits Arcade label-expression JSON for ArcGIS Pro layers. Not every layer/consumer
uses the Arcade expression engine — a layer's label class also supports a `'Python'`
`expressionEngine` (verified against `doc.esri.com`'s "Specify text for labels"
examples and the arcpy `LabelClass` reference), and some existing/legacy layers are
configured that way. No headless tool emitted the equivalent Python label-expression
source, so it had to be hand-written and could drift from the Arcade version and from
the analyte dictionary.

## Decision

Added `GeneratePythonLabelExpressions` (Tool 5.4b, `autogis envmon
generate-python-labels`) as a new sibling CLI command — same 4 expression categories
(`RESULT_WITH_UNITS`, `EXCEEDANCE_CALLOUT`, `ND_CALLOUT`, `WELL_ID_ONLY`) and the same
`--analytes`/`--field-prefix`/`--out`/`--report` options as the Arcade tool, but
emitting Esri's Python label-expression syntax — a `def FindLabel([Field], ...): ...`
function body with fields referenced via bracket tokens (`[FieldName]`) — instead of
Arcade's `$feature.Field` syntax. Implementation: `autogis/core/envmon/
python_label_generator.py`, no arcpy imports, `Runtime.CLOUD`.

The field-naming convention that turns an analyte name into GDB field names
(`Benzene` → `Env_Benzene_Value`/`_Units`/`_SL` + `LocationID`) was extracted out of
`arcade_label_generator.py` into a new shared module,
`autogis/core/envmon/label_expression_common.py` (`LabelExpressionType`,
`derive_label_fields`), and both generators now import it. The Arcade and Python
variants describe fields on the *same* GDB layer, so if this naming convention drifted
between the two tools, a layer labeled with one and re-labeled with the other would
silently point at different fields; sharing one function makes that drift a type
error, not a runtime surprise. `arcade_label_generator.py`'s public API and output are
unchanged by this refactor.

Each Python label JSON entry additionally carries `"expression_engine": "Python"`
(the Arcade tool's output doesn't need this — Arcade is the default engine). Whoever
applies this JSON to a layer needs to know which `labelClass.expressionEngine` value
to set; without this field that value would have to be hardcoded externally.

## Consequences

### Positive consequences

- Layers/consumers using the `'Python'` expression engine get the same
  analyte-dictionary-driven, drift-free generation the Arcade tool already provides.
- The shared `label_expression_common.py` module makes future field-naming changes a
  one-place edit instead of a two-place edit that can silently diverge.
- Fully arcpy-free (ADR-0002) and unit-testable; no new dependency.

### Negative consequences

- Two label-expression JSON shapes now exist (`arcade_expression` vs.
  `python_expression` keys, and only the Python one carries `expression_engine`) —
  a consumer that wants to be engine-agnostic has to branch on which file it got.
- The generated Python source cannot be executed/validated outside ArcGIS Pro, so
  tests can only assert on expression *shape* (contains `def FindLabel`, contains the
  expected bracket tokens), not that Pro accepts it.

## Alternatives considered

1. **Single command with `--language arcade|python`:** Would change
   `generate-arcade-labels`'s existing CLI contract and tests for no real benefit —
   the two output artifacts are consumed differently (pasted into different
   label-class engine settings). The repo's existing convention is one CLI verb per
   output artifact (see `run-history-report` / `run-history`, Tool 10.1/10.1b, as a
   precedent for sibling commands sharing a roadmap ID with a letter suffix).
   Rejected.
2. **No `expression_engine` metadata in the output:** Leaves the engine choice
   implicit/external, duplicating information the generator already knows. Rejected.
3. **Duplicate the field-derivation logic instead of extracting a shared module:**
   Zero risk to the existing Arcade module, but the two tools' field-naming
   conventions could drift apart if one is edited without the other. Rejected in
   favor of the shared `label_expression_common.py` module, enforced by a
   field-name-parity test.

## Related decisions

- [ADR-0002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) —
  `python_label_generator.py` and `label_expression_common.py` uphold this invariant.
- `docs/superpowers/specs/2026-06-28-generate-arcade-label-expressions-design.md` —
  original design for the Arcade tool this one mirrors.
- `docs/superpowers/specs/2026-07-01-python-label-expression-generator-design.md` —
  design doc for this tool.
```

- [ ] **Step 6: Commit**

```bash
git add README.md docs/adr/00NN-python-label-expression-generator.md
git commit -m "docs(envmon): README + ADR for GeneratePythonLabelExpressions"
```

---

### Task 7: Phase-separation documentation (AI-assisted §11 / geostatistical Phase 5)

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP_STATUS_2026-06-27.md`
- Modify: `CLAUDE.md`

**Interfaces:** None (documentation only). This task is independent of Tasks 1–6's code — it strengthens existing "deferred"/"blocked" language into an explicit phase-gate policy so it isn't missed by a future session, per the user's request in this conversation.

- [ ] **Step 1: Strengthen the README "Not started" note**

In `README.md`, find this block (inside the `<details><summary>Not started — no spec or implementation plan</summary>` section):

```
**AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec, AIMapReviewChecklist
— all deferred pending LLM seam design

**Conditional / geostatistical (Phase 5):** 8 tools (kriging / EBK / surface modeling) — blocked on
architecture review; see `docs/CONDITIONAL_TOOLS_REVIEW.md`

</details>
```

Replace with:

```
**AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec, AIMapReviewChecklist
— all deferred pending LLM seam design

**Conditional / geostatistical (Phase 5):** 8 tools (kriging / EBK / surface modeling) — blocked on
architecture review; see `docs/CONDITIONAL_TOOLS_REVIEW.md`

**These two groups are a separate future development phase, not a backlog to pick from.**
Do not start implementation on any tool listed above without an explicit phase-gate
decision — the codebase is refined thoroughly first. See `CLAUDE.md` for the standing
policy.

</details>
```

- [ ] **Step 2: Add the pointer in `docs/ROADMAP_STATUS_2026-06-27.md`**

Find this block:

```
- **AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec,
  AIMapReviewChecklist (all deferred — need LLM seam design)
- **Conditional/geostatistical (Phase 5):** 8 deferred tools per
  `ROADMAP_UPDATE_2026-06-25.md` (kriging/EBK/surface modeling) — blocked on
  architecture review.
```

Replace with:

```
- **AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec,
  AIMapReviewChecklist (all deferred — need LLM seam design)
- **Conditional/geostatistical (Phase 5):** 8 deferred tools per
  `ROADMAP_UPDATE_2026-06-25.md` (kriging/EBK/surface modeling) — blocked on
  architecture review.
- **Both groups above are a separate future development phase, not a backlog to pick
  from** — see `CLAUDE.md` for the standing phase-gate policy.
```

- [ ] **Step 3: Add the policy section to `CLAUDE.md`**

In `CLAUDE.md`, find the end of the `## Key invariants` section — it currently ends with:

```
- Screening levels and the H281 parser profile are pre-production stubs — do not
  remove DRAFT banners or `_TODO` markers until verified against real data.
```

Insert a new section immediately after that bullet list (before the `## Decision records` heading):

```markdown

## Deferred tool groups — do not build without a phase-gate decision

Two roadmap groups are **out of scope until a deliberate phase-gate decision reopens
them.** Do not implement, spec, or fast-track any of these without the user
explicitly re-opening that group first:

- **AI-assisted (§11):** `AIDraftParserProfile`, `AIExplainQAReport`,
  `AIDraftFigureSpec`, `AIMapReviewChecklist` — deferred pending LLM seam design
  (`docs/superpowers/specs/2026-06-28-ai-assisted-tools-llm-seam-design.md`).
- **Conditional / geostatistical (Phase 5):** ~8 tools (kriging / EBK / surface
  modeling) — blocked on architecture review (`docs/CONDITIONAL_TOOLS_REVIEW.md`,
  `docs/superpowers/specs/2026-06-28-geostatistical-conditional-tools-design.md`).

These are a **separate future development phase**: the codebase gets refined
thoroughly first, before either group is even considered. Other roadmap batches have
been quietly fast-tracked before without a formal gate decision — treat
"deferred"/"blocked" on these two groups as binding until the user says otherwise,
not as a backlog to pick from when idle.
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ROADMAP_STATUS_2026-06-27.md CLAUDE.md
git commit -m "docs: mark AI-assisted (§11) and geostatistical (Phase 5) tools as a separate future phase"
```

---

### Task 8: Final verification, PR, and review follow-up

**Files:** None (verification + git/GitHub operations only).

- [ ] **Step 1: Run the full test suite one more time**

Run: `python -m pytest -q`
Expected: PASS, 0 failures.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin worktree-feat+envmon-python-labels
gh pr create --title "feat(envmon): add generate-python-labels (Tool 5.4b)" --body "$(cat <<'EOF'
## Summary
- New sibling tool `autogis envmon generate-python-labels` (Tool 5.4b) mirrors the Arcade label generator (Tool 5.4) but emits Esri's Python label-expression syntax (`def FindLabel([Field]): ...`)
- Shared field-name derivation extracted into `label_expression_common.py`, reused by both the Arcade and Python generators (parity enforced by test)
- README + new ADR document the tool; CLAUDE.md + README + ROADMAP_STATUS now explicitly mark the AI-assisted (§11) and geostatistical (Phase 5) tool groups as a separate future development phase, not a pickable backlog

## Test plan
- [x] `python -m pytest -q` passes locally
- [ ] Copilot PR review addressed
EOF
)"
```

- [ ] **Step 3: Poll for the automated PR review and address findings**

The `copilot-pull-request-reviewer` bot typically posts within ~2-3 minutes of PR creation (observed on PRs #119, #121, #122 in this repo). Poll with:

```bash
gh pr view --json reviews -q '.reviews[] | .author.login + " " + .submittedAt + " " + .state'
```

Once a review appears, fetch the comments (`{owner}`/`{repo}` are auto-filled by `gh`
from the current repo; the PR number comes from `gh pr view --json number`):

```bash
gh pr view --json comments -q '.comments[].body'
PR_NUMBER=$(gh pr view --json number -q .number)
gh api repos/{owner}/{repo}/pulls/$PR_NUMBER/comments -q '.[] | .path + ":" + (.line|tostring) + " " + .body'
```

For each actionable finding: fix it in a new commit (not `--amend`), push, and re-poll to confirm no new blocking comments. If a finding is out of scope or wrong, note why in a PR comment reply rather than silently ignoring it.

- [ ] **Step 4: Report completion**

Summarize to the user: PR URL, test count, and whether the Copilot review required any fixes.

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the shared-helper extraction + Arcade refactor from the design doc's "Approach" section. Tasks 2–4 cover the `python_label_generator.py` Public API section. Task 5 covers the CLI Command section. Task 6 covers the Architecture section's README/ADR line. Task 7 covers the user's separate phase-gate documentation request. Task 8 covers PR creation and the user's "poll for code review, fix" request. No spec section is uncovered.
- **Placeholder scan:** No TBD/TODO markers; every step has concrete code or exact commands. The one open value (ADR number) is resolved by an explicit `ls`/lookup step, not left as a placeholder to guess later.
- **Type consistency:** `PythonLabelSpec`, `LabelFields`, `LabelExpressionType`, `derive_label_fields`, `generate_python_labels`, `write_label_expressions`, `EXPRESSION_ENGINE` are used with the same names/signatures across Tasks 1–5 as defined when first introduced.
