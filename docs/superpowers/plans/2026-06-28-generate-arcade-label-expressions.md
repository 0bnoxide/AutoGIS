# GenerateArcadeLabelExpressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `GenerateArcadeLabelExpressions` — generate Arcade label expression strings for ArcGIS Pro layers from site config and analyte list, written to a JSON file, so users can import consistent callout expressions instead of hand-writing Arcade per site.

**Architecture:**
- New: `autogis/core/envmon/arcade_label_generator.py`
- Modify: `autogis/adapters/cli.py` — add `generate-arcade-labels` command (CLOUD)
- Modify: `autogis/runtime/capabilities.py` — register `"generate-arcade-labels": Runtime.CLOUD`
- New: `tests/envmon/test_arcade_label_generator.py`

## Global Constraints

- Arcpy-free. stdlib + json + dataclasses only.
- `core/` and `adapters/` import without arcpy or arcgis present.
- Run tests with: `python -m pytest -q`.
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group.
- Output is a JSON array, not a workbook — no openpyxl.

---

### Task 1: Core `arcade_label_generator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_arcade_label_generator.py`:

```python
"""Tests for arcade_label_generator module (Tool 5.4)."""
import json
from pathlib import Path

import pytest

from autogis.core.envmon.arcade_label_generator import (
    LabelExpressionType,
    ArcadeLabelSpec,
    build_result_label_expression,
    build_exceedance_callout_expression,
    generate_arcade_labels,
    write_label_expressions,
)


# ---------------------------------------------------------------------------
# build_result_label_expression
# ---------------------------------------------------------------------------

def test_result_expression_contains_nd_branch():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ND" in expr


def test_result_expression_contains_value_field():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ResultValue" in expr


def test_result_expression_contains_units_field():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert "ReportedUnits" in expr


def test_result_expression_is_string():
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    assert isinstance(expr, str)
    assert len(expr) > 0


def test_result_expression_custom_nd_text():
    expr = build_result_label_expression("Val", "Units", nd_text="<MDL")
    assert "<MDL" in expr


def test_result_expression_contains_format_call():
    """Arcade Text() or numeric format should appear for the value path."""
    expr = build_result_label_expression("ResultValue", "ReportedUnits")
    # Must include either Text() formatting or numeric concatenation
    assert "Text(" in expr or "+" in expr


# ---------------------------------------------------------------------------
# build_exceedance_callout_expression
# ---------------------------------------------------------------------------

def test_exceedance_expression_contains_double_asterisk():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "**" in expr


def test_exceedance_expression_contains_value_field():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "ResultValue" in expr


def test_exceedance_expression_contains_sl_field():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert "ScreeningLevel" in expr


def test_exceedance_expression_is_string():
    expr = build_exceedance_callout_expression(
        "ResultValue", "ScreeningLevel", "ReportedUnits"
    )
    assert isinstance(expr, str)
    assert len(expr) > 0


# ---------------------------------------------------------------------------
# generate_arcade_labels
# ---------------------------------------------------------------------------

def test_generate_labels_three_analytes_min_three_specs():
    analytes = ["Benzene", "Toluene", "PCE"]
    specs = generate_arcade_labels(analytes)
    assert len(specs) >= 3


def test_generate_labels_returns_arcade_label_spec_instances():
    specs = generate_arcade_labels(["Benzene"])
    for s in specs:
        assert isinstance(s, ArcadeLabelSpec)


def test_generate_labels_with_field_prefix():
    specs = generate_arcade_labels(["Benzene"], field_prefix="Env_")
    for s in specs:
        assert "Env_" in s.value_field or "Env_" in s.analyte_field


def test_generate_labels_spec_has_expression():
    specs = generate_arcade_labels(["Benzene"])
    for s in specs:
        assert isinstance(s.expression, str)
        assert len(s.expression) > 0


def test_generate_labels_spec_has_layer_name():
    specs = generate_arcade_labels(["Benzene"])
    for s in specs:
        assert isinstance(s.layer_name, str)
        assert len(s.layer_name) > 0


def test_generate_labels_expression_types_present():
    """At least RESULT_WITH_UNITS and ND_CALLOUT types should appear."""
    specs = generate_arcade_labels(["Benzene"])
    types_found = {s.expression_type for s in specs}
    assert LabelExpressionType.RESULT_WITH_UNITS in types_found


def test_generate_labels_empty_analytes():
    specs = generate_arcade_labels([])
    assert specs == []


# ---------------------------------------------------------------------------
# write_label_expressions
# ---------------------------------------------------------------------------

def test_write_produces_json_file(tmp_path):
    specs = generate_arcade_labels(["Benzene", "Toluene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    assert out.exists()


def test_written_json_is_parseable(tmp_path):
    specs = generate_arcade_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_written_json_has_expected_keys(tmp_path):
    specs = generate_arcade_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) > 0
    entry = data[0]
    assert "layer_name" in entry
    assert "expression_type" in entry
    assert "arcade_expression" in entry


def test_written_json_arcade_expression_is_string(tmp_path):
    specs = generate_arcade_labels(["Benzene"])
    out = tmp_path / "labels.json"
    write_label_expressions(specs, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for entry in data:
        assert isinstance(entry["arcade_expression"], str)
        assert len(entry["arcade_expression"]) > 0
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_arcade_label_generator.py -v
```

Expected: all fail with `ModuleNotFoundError` / `ImportError`.

- [ ] **Step 3: Create `autogis/core/envmon/arcade_label_generator.py`**

```python
"""arcade_label_generator.py — Arcade label expression generator (Tool 5.4).

Generates Arcade label expression strings for ArcGIS Pro callout layers.
Output is a JSON file (array of objects) ready to paste or import into
ArcGIS Pro layer label settings.

No arcpy dependency. stdlib + dataclasses only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class LabelExpressionType:
    """String constants for Arcade label expression variants."""

    RESULT_WITH_UNITS: str = "RESULT_WITH_UNITS"
    EXCEEDANCE_CALLOUT: str = "EXCEEDANCE_CALLOUT"
    ND_CALLOUT: str = "ND_CALLOUT"
    WELL_ID_ONLY: str = "WELL_ID_ONLY"


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
    units_field: str,
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
        safe_name = analyte.replace(" ", "_").replace(",", "").replace("/", "_")
        value_field = f"{field_prefix}{safe_name}_Value"
        units_field = f"{field_prefix}{safe_name}_Units"
        sl_field = f"{field_prefix}{safe_name}_SL"
        id_field = f"{field_prefix}LocationID"
        layer_base = safe_name

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
            expression=_build_nd_callout_expression(value_field, units_field),
        ))

        # 4. WELL_ID_ONLY (shared across all analytes; one per analyte pass)
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
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_arcade_label_generator.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit core module**

```bash
git add autogis/core/envmon/arcade_label_generator.py \
        tests/envmon/test_arcade_label_generator.py
git commit -m "feat(envmon): arcade_label_generator — Arcade label expression builder (Tool 5.4)"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add command to `autogis/adapters/cli.py`**

```python
@envmon.command("generate-arcade-labels")
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
def generate_arcade_labels_cmd(analytes_str, field_prefix, out, report):
    """Tool 5.4: generate Arcade label expressions for ArcGIS Pro layers (headless)."""
    from autogis.core.common.qa import QACollector, SEV_INFO
    from autogis.core.envmon.arcade_label_generator import (
        generate_arcade_labels, write_label_expressions,
    )

    analytes = [a.strip() for a in analytes_str.split(",") if a.strip()]
    if not analytes:
        raise click.UsageError("--analytes must contain at least one analyte name.")

    specs = generate_arcade_labels(analytes, field_prefix=field_prefix)
    write_label_expressions(specs, Path(out))

    qa = QACollector()
    qa.add(
        SEV_INFO, "arcade_labels_written",
        f"{len(specs)} expression(s) for {len(analytes)} analyte(s) → {out}",
    )
    click.echo(
        f"Written {len(specs)} Arcade expression(s) for {len(analytes)} "
        f"analyte(s) to: {out}"
    )
    _render_qa(qa, report, "error")
```

- [ ] **Step 2: Register in `autogis/runtime/capabilities.py`**

Add to `TOOLS` dict:

```python
"generate-arcade-labels": Runtime.CLOUD,  # tool 5.4
```

- [ ] **Step 3: Add help-text test to test file**

Add to `tests/envmon/test_arcade_label_generator.py`:

```python
def test_generate_arcade_labels_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as autogis_cli
    result = CliRunner().invoke(autogis_cli, ["envmon", "--help"])
    assert "generate-arcade-labels" in result.output
```

- [ ] **Step 4: Full suite**

```
python -m pytest -q
```

Expected: all PASS (no regressions).

- [ ] **Step 5: Commit CLI wiring**

```bash
git add autogis/adapters/cli.py \
        autogis/runtime/capabilities.py \
        tests/envmon/test_arcade_label_generator.py
git commit -m "feat(cli): add generate-arcade-labels command (Tool 5.4)"
```

---

## Run commands

```bash
# TDD step 1: verify tests fail before module exists
python -m pytest tests/envmon/test_arcade_label_generator.py -v

# TDD step 2: after creating arcade_label_generator.py
python -m pytest tests/envmon/test_arcade_label_generator.py -v

# TDD step 3: full suite after CLI wiring
python -m pytest -q

# Manual smoke test
python -c "
from autogis.core.envmon.arcade_label_generator import generate_arcade_labels, write_label_expressions
from pathlib import Path
specs = generate_arcade_labels(['Benzene', 'PCE', 'Toluene'])
write_label_expressions(specs, Path('/tmp/arcade_labels.json'))
print(f'{len(specs)} specs written')
"

# CLI smoke test
python -m autogis envmon generate-arcade-labels \
    --analytes "Benzene,PCE,Toluene" \
    --field-prefix "Env_" \
    --out /tmp/arcade_labels.json
```
