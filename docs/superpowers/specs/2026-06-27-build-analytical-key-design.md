# BuildAnalyticalKey Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** BuildAnalyticalKey (Phase 3.3 / Tool 5.5)
**Priority:** MEDIUM-HIGH (figure quality — maps without a proper key are incomplete deliverables)

---

## Problem

Environmental figures require an analytical key (legend table) that lists: analyte
abbreviation, display name, units, and the result-status color symbols (exceedance,
detection, nondetect, not sampled). This is currently produced manually in the APRX or
as a static table — it falls out of sync with the analyte dictionary and screening
level changes. No automated path exists.

---

## Approach

**Chosen:** New `analytical_key.py` module with `build_analytical_key()` → `CalloutTable`
(reusing the existing `CellSpec`/`CalloutTable` dataclasses from `callout_templates.py`
since they already carry the `display_color_class` and flag fields that map directly to
legend symbols). A separate `Env_AnalyticalKey` feature class is written by a LOCAL
function, sibling to `assemble_callouts` in the figure pipeline.

**Rejected: Static text element in APRX.** No version control; breaks when analytes
change.

**Rejected: New grid data structure.** `CellSpec`/`CalloutTable` is already exactly
what's needed — same row/col grid with text, style class, and color class. Reusing it
means the callout rendering layer can eventually render the key with the same code.

---

## Architecture

```
autogis/
  core/envmon/
    analytical_key.py        ← NEW (arcpy-free computation + LOCAL write)
  adapters/
    cli.py                   ← add build-analytical-key subcommand (LOCAL)
tests/envmon/
  test_analytical_key.py     ← NEW, arcpy-free
```

---

## Key Layout

```
Row 1:  [Header] "Analytical Key — {matrix} — {event_date}"
Row 2:  [Column headers] Abbr | Name | Units | ▲ Exceed | ● Detect | ○ ND | — N/S
Row 3+: One row per analyte in display_order from analyte dictionary
        [LABEL] abbr | [LABEL] canonical_name | [LABEL] units
        [EXCEEDANCE] ▲ | [DETECTED] ● | [NONDETECT] ○ | [NOT_SAMPLED] —
```

Symbol cells use the same `display_color_class` values (`EXCEEDANCE`, `DETECTED`,
`NONDETECT`, `NOT_SAMPLED`) so the callout renderer applies the same CSS/symbology.

---

## Public API (`analytical_key.py`)

```python
def build_analytical_key(
    figure_spec,                  # FigureSpec — provides analyte_list()
    analyte_dictionary: dict,
    matrix: str,
    event_date: Optional[str] = None,
) -> "CalloutTable":
    """
    Pure Python — returns a CalloutTable with one row per analyte.
    Uses CellSpec from callout_templates.
    """

def write_analytical_key(    # pragma: no cover — requires arcpy
    gdb_path: str,
    site_id: str,
    figure_spec_id: str,
    key_table: "CalloutTable",
) -> None:
    """Write key rows to Env_AnalyticalKey feature class."""

def format_key_text(key_table: "CalloutTable") -> str:
    """ASCII table for CLI preview."""
```

---

## Feature Class Schema

`Env_AnalyticalKey` is NOT currently in TABLE_SCHEMAS. Add it in `gdb_schema.py`:

```python
"Env_AnalyticalKey": [
    ("SiteID", T, 32), ("FigureSpecID", T, 64), ("EventDate", DT, None),
    ("Matrix", T, 16), ("DisplayOrder", L, None),
    ("AnalyteAbbr", T, 16), ("AnalyteName", T, 64),
    ("Units", T, 32), ("ScreeningLevel", D, None),
    ("ScreeningSource", T, 64),
    ("HasExceedance", SH, None), ("HasDetection", SH, None),
    ("HasNonDetect", SH, None), ("HasNotSampled", SH, None)],
```

---

## Integration with Figure Pipeline

In `build_figure_dataset.py`, after `assemble_callouts()` call:

```python
if write_analytical_key:
    from .analytical_key import build_analytical_key, write_analytical_key as _write_key
    key = build_analytical_key(figure_spec, analyte_dictionary, matrix, event_date)
    _write_key(gdb_path, site_id, figure_spec_id, key)
```

---

## Test Strategy

`tests/envmon/test_analytical_key.py` — all arcpy-free:

1. `build_analytical_key()` returns a `CalloutTable` with `n_rows >= 2` (header + at least one analyte)
2. Each analyte in `figure_spec.analyte_list()` appears as one data row
3. Result row has `display_color_class == "EXCEEDANCE"` for the exceedance symbol cell
4. `format_key_text()` output contains analyte abbreviation
5. Header row text contains matrix name
6. `build_analytical_key()` with empty analyte list → header only, no crash
7. Cell for `display_color_class == "NONDETECT"` has `is_nondetect = True`
