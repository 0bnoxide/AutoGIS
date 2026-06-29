# GenerateArcadeLabelExpressions Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateArcadeLabelExpressions (Tool 5.4)
**Priority:** MEDIUM — labels are the fallback when callout features aren't generated

---

## Problem

Not every figure gets full callout features; many maps (and all AGOL web maps) rely on
Arcade label expressions. Today those expressions are hand-written per layer and drift
out of sync with the figure spec and analyte dictionary. There is no tool that turns a
figure spec into ready-to-paste Arcade expressions + the field mapping they assume.

---

## Approach

**Chosen:** A headless text generator. Read the figure spec (already a config artifact
in `autogis/config/`) and the analyte dictionary, and emit Arcade expression `.txt`
files plus a field-mapping JSON describing which fields each expression references.
Templates cover the common label kinds: water-level label, compact analytical label,
exceedance-emphasis label, and a generic key-value label. Pure string generation — no
arcpy needed to *produce* the expression text (arcpy only ever *consumes* it inside Pro).

**Rejected: writing labels onto a layer here.** Applying the expression to a layer is an
arcpy/Pro action (and an AGOL action for web maps). This tool emits the expression text
and the field contract; `UpdateLayoutDynamicText`/Pro or `UpdateAGOLWebMapFromFigureSpec`
apply it.

**Rejected: free-form template authoring.** A fixed template set keyed off the figure
spec keeps expressions consistent and analyte-dictionary-driven; custom needs get a new
named template, not ad-hoc strings.

This stays arcpy-free (ADR-0002) and runs in CI/cloud.

---

## Architecture

```
autogis/
  core/envmon/
    arcade_labels.py          ← NEW (pure string/JSON generation)
  config/                     ← figure specs (EXISTS, read-only input)
  adapters/
    cli.py                    ← add gen-arcade-labels command (headless)
tests/envmon/
  test_arcade_labels.py       ← NEW
```

---

## Public API (`arcade_labels.py`)

```python
ARCADE_TEMPLATES = (
    "water_level", "compact_analytical", "exceedance_emphasis", "key_value",
)

@dataclass
class ArcadeExpression:
    name: str
    template: str
    expression: str           # the Arcade source text
    fields_used: list[str]    # field names referenced

def build_expression(
    template: str,
    *,
    figure_spec: dict,
    analyte_dict: dict | None = None,
) -> ArcadeExpression:
    """Render one Arcade expression from a figure spec."""

def write_expressions(
    expressions: list[ArcadeExpression],
    out_dir: Path,
) -> list[Path]:
    """Write one .txt per expression + a field_mapping.json."""
```

---

## CLI Command

```
autogis envmon gen-arcade-labels \
  --figure-spec <figure_spec.yaml> \
  --templates water_level,compact_analytical \
  --out-dir <arcade/> \
  [--analyte-dict <analytes.yaml>]
```

Headless. Output `.txt` files are pasted into Pro/AGOL label expressions.

---

## Test Strategy

`tests/envmon/test_arcade_labels.py` — arcpy-free:

1. `water_level` template references the configured elevation field.
2. `compact_analytical` lists every analyte field from the figure spec in `fields_used`.
3. `exceedance_emphasis` includes a conditional on the exceedance flag field.
4. Unknown template name → ValueError.
5. `write_expressions` emits one `.txt` per expression.
6. `field_mapping.json` lists `fields_used` for every expression.
7. Expression text is valid non-empty Arcade (smoke: contains `$feature`).
