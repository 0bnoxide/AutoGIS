# GeneratePythonLabelExpressions Design

**Date:** 2026-07-01
**Status:** Approved
**Tool:** GeneratePythonLabelExpressions (Tool 5.4b)
**Priority:** LOW — sibling of the existing Arcade label generator (Tool 5.4)

---

## Problem

`autogis envmon generate-arcade-labels` (Tool 5.4) emits Arcade label expressions for
ArcGIS Pro layers. Not every layer/consumer uses the Arcade expression engine — a
layer's label class also supports a `'Python'` expression engine
(`labelClass.expressionEngine = 'Python'` via arcpy's CIM access), and some
existing/legacy layers are configured that way. There is no headless tool that emits
the equivalent Python label-expression source, so today those have to be hand-written
and can drift from the Arcade version and from the analyte dictionary.

Verified against Esri's documented Python label-expression format (`doc.esri.com`
"Specify text for labels" examples and the `LabelClass` arcpy reference — see Sources
below): a Python label expression is a `def FindLabel([Field1], [Field2], ...):`
function; fields are referenced as bracket tokens `[FieldName]` both in the parameter
list and, after assigning to a local variable (`S = [FieldName]`), in the body; the
function returns the label string. `expressionEngine` is set to the literal string
`'Python'` (not `'PYTHON3'` — Pro has no separate Python-2-era engine string despite
running under Python 3).

---

## Approach

**Chosen:** A new sibling CLI tool, `generate-python-labels`, that mirrors
`generate-arcade-labels` feature-for-feature (same 4 expression categories, same
`--analytes`/`--field-prefix`/`--out`/`--report` options) but emits Esri's Python
label-expression syntax — a `def FindLabel([Field], ...): ...` function body with
fields referenced via bracket tokens (`[FieldName]`), the format Pro's `'Python'`
label-class engine expects — instead of Arcade's `$feature.Field` syntax.

The field-naming convention that turns an analyte name into GDB field names
(`Benzene` → `Env_Benzene_Value`/`_Units`/`_SL` + `Env_LocationID`) is extracted out of
`arcade_label_generator.py` into a new shared module, `label_expression_common.py`,
and reused by both generators. This is a targeted refactor of existing code that
directly serves this feature: the Arcade and Python variants describe fields on the
*same* GDB layer, so if this naming convention drifts between the two tools, a layer
labeled with one and re-labeled with the other silently points at different fields.
Extracting it into one function makes that drift a type error, not a runtime surprise.
`LabelExpressionType` (the 4 category constants) moves alongside it for the same
reason — both tools classify expressions into the same 4 categories.

`arcade_label_generator.py`'s public API and output are unchanged by this refactor
(it now imports `LabelExpressionType`/`derive_label_fields` instead of inlining them);
existing tests are expected to pass unmodified.

**Rejected: single command with `--language arcade|python`.** Folding this into
`generate-arcade-labels` would change that tool's existing CLI contract and tests for
no real benefit — the two output artifacts are consumed differently (pasted into
different label-class engine settings) and the repo's existing convention is one CLI
verb per output artifact (see `run-history-report` / `run-history` as a precedent for
sibling commands sharing a roadmap ID with a letter suffix).

**Rejected: no engine metadata in the output.** Each Python label entry additionally
carries `"expression_engine": "Python"` (not present in the Arcade tool's output,
which doesn't need it — Arcade is the default engine). Whoever applies this JSON to a
layer needs to know which `labelClass.expressionEngine` value to set; without this
field that value would have to be hardcoded externally as "this file is always
Python", duplicating information the generator already knows.

This stays arcpy-free (ADR-0002) and runs in CI/cloud (`Runtime.CLOUD`).

---

## Architecture

```
autogis/
  core/envmon/
    label_expression_common.py  ← NEW (shared: LabelExpressionType, derive_label_fields)
    arcade_label_generator.py   ← MODIFIED (imports from label_expression_common)
    python_label_generator.py   ← NEW (PythonLabelSpec + 4 Python expression builders)
  adapters/
    cli.py                      ← add `generate-python-labels` command
  runtime/
    capabilities.py             ← register "generate-python-labels": Runtime.CLOUD
tests/envmon/
  test_python_label_generator.py  ← NEW
docs/adr/
  00NN-python-label-expression-generator.md  ← NEW
README.md                       ← 3 additions (capability table, CLI-runtime table,
                                   quick-reference command), placed next to the
                                   existing generate-arcade-labels entries
```

---

## Public API (`label_expression_common.py`)

```python
class LabelExpressionType:
    RESULT_WITH_UNITS: str = "RESULT_WITH_UNITS"
    EXCEEDANCE_CALLOUT: str = "EXCEEDANCE_CALLOUT"
    ND_CALLOUT: str = "ND_CALLOUT"
    WELL_ID_ONLY: str = "WELL_ID_ONLY"


@dataclass
class LabelFields:
    layer_base: str
    id_field: str
    value_field: str
    units_field: str
    sl_field: str


def derive_label_fields(analyte: str, field_prefix: str = "") -> LabelFields:
    """Derive GDB field names for one analyte. Shared by both label generators —
    the Arcade and Python variants MUST agree on field names for a given analyte."""
```

## Public API (`python_label_generator.py`)

```python
@dataclass
class PythonLabelSpec:
    layer_name: str
    expression_type: str
    analyte_field: str
    value_field: str
    units_field: str
    sl_field: Optional[str]
    expression: str


def build_result_label_expression(value_field: str, units_field: str, *, nd_text: str = "ND") -> str: ...
def build_exceedance_callout_expression(value_field: str, sl_field: str, units_field: str, *, nd_text: str = "ND", exceed_suffix: str = "**") -> str: ...

def generate_python_labels(analytes: list[str], *, field_prefix: str = "") -> list[PythonLabelSpec]:
    """One PythonLabelSpec per analyte per expression type (mirrors generate_arcade_labels)."""

def write_label_expressions(specs: list[PythonLabelSpec], out_path: Path) -> None:
    """Serialise to JSON. Each entry adds "expression_engine": "Python" versus the
    Arcade tool's output, and uses the key "python_expression" instead of
    "arcade_expression"."""
```

---

## CLI Command

```
autogis envmon generate-python-labels \
  --analytes "Benzene,PCE" \
  [--field-prefix Env_] \
  --out <labels.json> \
  [--report <qa.json>]
```

Headless (`Runtime.CLOUD`). Output JSON is pasted into a Pro layer's label class after
setting `expressionEngine` to `'Python'`.

---

## Test Strategy

`tests/envmon/test_python_label_generator.py` — arcpy-free, mirrors
`test_arcade_label_generator.py`:

1. Each builder's output contains `def FindLabel` and the referenced field(s) as
   bracket tokens.
2. `nd_text`/`exceed_suffix` are honored (same override tests as the Arcade version).
3. `generate_python_labels` returns ≥1 `PythonLabelSpec` per analyte per type, empty
   list for empty analytes.
4. `write_label_expressions` produces parseable JSON with `python_expression` and
   `expression_engine: "Python"` on every entry.
5. CLI `--help` lists `generate-python-labels`.
6. Cross-check: for the same analyte + field_prefix, `derive_label_fields` (used by
   both generators) produces identical `value_field`/`units_field`/`sl_field`/
   `id_field` — the guarantee the shared-helper extraction exists to enforce.

Existing `tests/envmon/test_arcade_label_generator.py` is expected to keep passing
unmodified after the refactor (behavior-preserving).
