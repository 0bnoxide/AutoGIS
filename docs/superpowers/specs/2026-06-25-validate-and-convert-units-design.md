# ValidateAndConvertUnits — design (2026-06-25)

## Problem

Units appear in every analytical config (analyte dictionary, screening levels) but
**nothing validates them today**. The screening/exceedance path compares raw numbers
with zero unit awareness:

- `autogis/core/envmon/result_parser.py:297` `evaluate_screening(parsed, screening_level)`
  does a bare `parsed.result_numeric > screening_level`.
- `autogis/core/envmon/table_normalizer.py:70-104`: a result column's `units` come from
  the workbook units row, but a screening level can come from config via
  `screening_for(...)`, which carries its **own** `units`. When the config screening
  unit differs from the result-column unit (e.g. result `mg/L`, config SL `ug/L`), the
  comparison is silently off by 1000× — a compliance-grade corruption of exceedance
  flags with no current guard.

The existing `config_validation.validate_bundle` (lines 228-236) has only a
string-equality `units_mismatch` WARNING: it cannot tell a convertible mismatch
(`ug/L` vs `mg/L`) from a dimensional impossibility (`mg/L` vs `mg/kg`).

## Scope (v1)

In scope:

1. A reusable, arcpy-free unit registry + converter (`core/common/units.py`).
2. A pure validator (`config_validation.validate_units`) that scans the analyte
   dictionary and screening-level configs for unit problems and emits QA records.
3. An orchestrator (`core/envmon/validate_units.py`) and a `validate-units` CLI
   subcommand, mirroring `validate-config` / `manage-analyte-dict`.

Out of scope (deliberate, leaves a tiny follow-up):

- **No change to the live screening path.** `evaluate_screening` and
  `table_normalizer` are untouched in v1. `convert()` and `same_dimension()` are
  shipped ready for that follow-up.
- Missing screening `value` (the current `_TODO` rows) — already covered by
  `validate_screening_levels`; this feature only validates the `units`.

## Architecture

| New/changed | File | Purpose |
|---|---|---|
| new | `autogis/core/common/units.py` | Built-in unit registry + pure `normalize_unit`/`convert`/`same_dimension`. |
| change | `autogis/core/common/config_validation.py` | Add `validate_units(analytes, screening) -> List[QARecord]`. |
| new | `autogis/core/envmon/validate_units.py` | Orchestrator `validate_units_config(analytes_path, screening_path) -> QACollector`. |
| change | `autogis/adapters/cli.py` | `validate-units` subcommand reusing `_render_qa`. |
| new | `tests/test_units.py` | Registry + converter unit tests. |
| new | `tests/envmon/test_validate_units.py` | Validator + orchestrator tests. |

All within ADR-001 (core + adapters), ADR-002 (arcpy-free core), ADR-003 (canonical
config locations). The registry lives in code, not config (decision below).

## The registry (`core/common/units.py`)

```python
class UnitError(ValueError):
    """Unknown unit or a cross-dimension conversion attempt."""

# canonical key -> (dimension, factor-to-dimension-base)
UNIT_REGISTRY = {
    "ng/L": ("aqueous", 0.001), "ug/L": ("aqueous", 1.0),
    "mg/L": ("aqueous", 1000.0), "g/L": ("aqueous", 1_000_000.0),
    "ug/kg": ("soil", 0.001), "mg/kg": ("soil", 1.0), "g/kg": ("soil", 1000.0),
}
```

Public functions:

- `normalize_unit(u) -> Optional[str]` — returns the canonical registry key or `None`.
  Strips surrounding whitespace, maps the micro signs `µ` (U+00B5) and `μ` (U+03BC) to
  `u`, and matches case-insensitively, so `µg/L`, `UG/L`, and `" ug/l "` all resolve to
  `ug/L`. Returns `None` for anything not in the registry (caller decides severity).
- `dimension_of(u) -> Optional[str]`.
- `same_dimension(a, b) -> bool` — both resolve and share a dimension.
- `convert(value, from_u, to_u) -> float` — raises `UnitError` when either unit is
  unknown or the two units are in different dimensions; otherwise returns
  `value * factor[from] / factor[to]`.

**`ppb`/`ppm` are deliberately excluded.** They are dimension-ambiguous (ppb = µg/L in
water but µg/kg in soil), so admitting them would defeat the cross-dimension guard.
They resolve to `None` → reported as `unknown_unit`, which is the safe behavior.

The registry is the single source of "explicit conversion rules": a conversion is
allowed iff both units are registered in the same dimension. Adding a unit is a
one-line registry edit.

## The validator (`config_validation.validate_units`)

Pure function over already-loaded dicts, returning `List[QARecord]` (collect-all,
never raise — consistent with its siblings):

```python
def validate_units(analytes: dict, screening: dict) -> List[QARecord]: ...
```

Emitted records:

- **`unknown_unit`** (ERROR) — any `units` string in screening levels, or any value in
  an analyte's `default_units_by_matrix`, that `normalize_unit` cannot resolve.
- **`cross_dimension`** (ERROR) — for a matrix/analyte present in both configs, the
  dictionary default unit and the screening unit resolve to **different dimensions**
  (the silent-corruption case).
- **`convertible_mismatch`** (WARNING) — same dimension, different unit (e.g. dict
  `ug/L` vs screening `mg/L`); the message states the conversion factor. This is the
  richer successor to the string-only `units_mismatch`.

Matching analyte names across the two configs reuses the existing analyte-lookup
(`build_analyte_lookup` / `_norm_key`) so aliases line up, consistent with
`validate_bundle`. Entries that are not dicts or not present in both configs are
simply skipped by this validator (other validators already flag malformed entries).

## Orchestrator + CLI

`core/envmon/validate_units.py`:

```python
def validate_units_config(analytes_path, screening_path) -> QACollector
```

- Uses the same `_safe()` defensive-load wrapper as `validate_config.py`: a bad file
  becomes a `load_error` ERROR, never an exception.
- Loads via `load_analyte_dictionary` / `load_screening_levels`, runs
  `validate_units`, and appends a closing INFO `validation_complete` summary with
  error/warning counts.

`adapters/cli.py` — new `validate-units` command:

```
validate-units --analytes PATH --screening PATH [--report PATH] [--fail-on error|warning]
```

Reuses the shared `_render_qa` helper for output and exit code. Both options are
required (there is nothing to cross-check with only one file).

## No conflict with existing checks

`validate_units` ships under its own `validate-units` command. `validate-config`'s
existing `units_mismatch` WARNING is left untouched, so no single run double-emits.

## Error handling & testing (TDD: red-green-refactor)

- Converter: happy-path conversions both directions; `UnitError` on unknown unit and
  on cross-dimension; `normalize_unit` spellings (`µ`/case/whitespace); `ppb`→`None`.
- Validator: a fixture exercising each category (`unknown_unit`, `cross_dimension`,
  `convertible_mismatch`) plus a clean bundle emitting nothing.
- Orchestrator: load-error path; closing INFO summary present.
- CLI: exit code honors `--fail-on` (smoke test via the QA renderer), consistent with
  the `validate-config` tests.

Tests join the existing arcpy-free suite (`python -m pytest -q`).
