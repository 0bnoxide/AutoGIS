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
(`Benzene` → `Env_Benzene_Value`/`_Units`/`_SL` + `Env_LocationID`) was extracted out of
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
