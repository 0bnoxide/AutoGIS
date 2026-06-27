# ManageScreeningLevels Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** ManageScreeningLevels (Phase 2.5 / Tool 3.4)
**Priority:** HIGH (all analysis tools depend on correct screening levels)

---

## Problem

`screening_levels.yaml` is the secondary screening-level source used when a workbook
row has no inline RBSL. The current pipeline loads it via `load_screening_levels()`
but has no dedicated check that:

1. The YAML structure is valid (every entry has `value`, `units`, `source`).
2. The units are convertible (cross-referenced against the analyte dictionary per the
   `validate_units` logic).
3. Every analyte in the analyte dictionary that is sampled in a given matrix actually
   has a screening level entry (even if `value: null`).
4. `_TODO` placeholder sources are flagged before production use.
5. The effective date range is set (multi-regulatory source files need effective
   dates to avoid applying an old RBSL to new data).

Without this tool, a missing or mis-keyed screening level silently fails: the
importer flags `ExceedsScreeningLevel = null` for affected analytes, which produces
blank figures with no error.

---

## Approach

**Chosen:** Headless read-only validator — same shape as `validate_units` and
`manage_analyte_dict`: takes config file paths, returns `QACollector`, has a CLI
command. The screening levels YAML is the only config file that's per-site AND changes
with each regulatory update, so a dedicated check is warranted.

**Rejected: Folding into validate_config.** `validate_config` already chains five
validators; adding matrix-completeness checks there would make it significantly heavier
and harder to run standalone against just screening levels.

**Rejected: GDB-backed storage.** The roadmap (Phase 2.5 roadmap note) initially
suggested a GDB table. For now the YAML file is the source of truth — the GDB table
(`Env_ScreeningLevels`, which would require an arcpy tool) is Phase 3+ work. This tool
validates the YAML that feeds that future table.

---

## Architecture

```
autogis/
  core/envmon/
    manage_screening_levels.py   ← NEW
  adapters/
    cli.py                       ← add manage-screening-levels command
tests/envmon/
  test_manage_screening_levels.py ← NEW, arcpy-free
```

---

## Public API (`manage_screening_levels.py`)

```python
@dataclass
class ScreeningEntry:
    analyte: str
    matrix: str
    value: Optional[float]
    units: str
    source: str
    effective_date: Optional[str] = None

def load_screening_entries(path: Path) -> list[ScreeningEntry]:
    """Parse screening_levels.yaml into flat records for validation."""

def check_screening_levels(
    screening_path: Path,
    analytes_path: Optional[Path] = None,
) -> QACollector:
    """
    Validate screening levels file.

    Without analytes_path: structure + unit format + placeholder checks only.
    With analytes_path: also checks that every analyte in the dictionary has
    a screening level entry for each relevant matrix.
    """
```

---

## Check Logic

| Check | Severity | Category |
|---|---|---|
| Entry missing `value`, `units`, or `source` key | ERROR | `missing_entry_key` |
| `value` present but not numeric (and not null) | ERROR | `invalid_value` |
| `units` string not parseable by `UnitRegistry` | WARNING | `invalid_units` |
| `source` contains `_TODO` | WARNING | `placeholder_source` |
| `value` is null | WARNING | `null_value` (pre-production stubs) |
| Analyte in dictionary but absent from screening levels (any matrix) | WARNING | `analyte_not_covered` |
| Analyte units in screening levels differ from dictionary default, and no converter exists | ERROR | `unit_not_convertible` |

Analyte coverage check runs only when `analytes_path` is provided. It looks at
`analyte_dictionary[analyte]["default_units_by_matrix"]` to determine which matrices
to check.

---

## CLI Command

```python
@envmon.command("manage-screening-levels")
@click.argument("screening", type=click.Path(exists=True))
@click.option("--analytes", default=None, type=click.Path(exists=True))
@click.option("--list", "do_list", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def manage_screening_levels_cmd(screening, analytes, do_list, report, fail_on):
    """Validate and inspect the screening levels YAML (headless)."""
```

`--list` prints a table of analyte / matrix / value / units / source.

---

## Screening Levels YAML Schema (for documentation only)

```yaml
# screening_levels.yaml
# Matrices: GW, SOIL (must match Env_AnalyticalResults.Matrix)
screening_levels:
  GW:
    Benzene: {value: 5.0, units: ug/L, source: "MDEQ RBSL 2024", effective_date: "2024-01-01"}
    Toluene: {value: null, units: ug/L, source: "_TODO MDEQ RBSL"}
  SOIL:
    Benzene: {value: 0.1, units: mg/kg, source: "MDEQ RBSL 2024"}
```

`effective_date` is optional but triggers a WARNING if absent when `value` is not null
(production screening levels should be dated).

---

## Test Strategy

`tests/envmon/test_manage_screening_levels.py` — all arcpy-free:

1. Valid entry passes with no errors
2. Entry missing `units` key → ERROR `missing_entry_key`
3. Entry with `_TODO` source → WARNING `placeholder_source`
4. Entry with null value → WARNING `null_value`
5. Entry with invalid units string → WARNING `invalid_units`
6. With analytes dict: analyte present in dict but absent from screening → WARNING `analyte_not_covered`
7. Without analytes dict: analyte coverage check is skipped (no `analyte_not_covered` records)
8. `load_screening_entries()` returns one entry per analyte/matrix pair
9. `--list` flag output contains analyte names and matrix column
