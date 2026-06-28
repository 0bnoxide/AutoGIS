# BuildAnalyticalKey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `analytical_key.py` — `build_analytical_key()` returns a
`CalloutTable` (reusing existing `CellSpec`/`CalloutTable` from `callout_templates.py`)
and `write_analytical_key()` writes to a new `Env_AnalyticalKey` feature class.
See spec: `docs/superpowers/specs/2026-06-27-build-analytical-key-design.md`.

**Architecture:**
- Modify: `autogis/core/envmon/gdb_schema.py` — add `Env_AnalyticalKey` TABLE_SCHEMAS entry
- New: `autogis/core/envmon/analytical_key.py`
- Modify: `autogis/adapters/cli.py` — add `build-analytical-key` command (LOCAL)
- New: `tests/envmon/test_analytical_key.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- `build_analytical_key()` and `format_key_text()` are arcpy-free.
- `write_analytical_key()` is LOCAL, `# pragma: no cover`.
- Reuse `CellSpec`, `CalloutTable` from `callout_templates.py` — no new grid dataclass.
- Run tests with `python -m pytest -q`.

---

### Task 1: Add `Env_AnalyticalKey` to TABLE_SCHEMAS

**File:** `autogis/core/envmon/gdb_schema.py`

- [ ] **Step 1: Append entry to TABLE_SCHEMAS**

After `"Dash_ReportReadiness"` entry (the last entry), replace the closing `}` with:

```python
    "Dash_ReportReadiness": [
        ... existing fields ...
    ],

    # ------------------------------------------------------------------
    # Analytical key (legend table for figure layouts)
    # ------------------------------------------------------------------
    "Env_AnalyticalKey": [
        ("SiteID", T, 32), ("FigureSpecID", T, 64), ("EventDate", DT, None),
        ("Matrix", T, 16), ("DisplayOrder", L, None),
        ("AnalyteAbbr", T, 16), ("AnalyteName", T, 64),
        ("Units", T, 32), ("ScreeningLevel", D, None),
        ("ScreeningSource", T, 64),
        ("HasExceedance", SH, None), ("HasDetection", SH, None),
        ("HasNonDetect", SH, None), ("HasNotSampled", SH, None)],
}
```

- [ ] **Step 2: Update test_upgrade_schema.py** (update total count from 37 to 38)

In `tests/envmon/test_upgrade_schema.py`:
```python
def test_total_table_count():
    assert len(TABLE_SCHEMAS) == 38, (
        f"Expected 38 tables (37 + Env_AnalyticalKey), got {len(TABLE_SCHEMAS)}"
    )
```

Also add `"Env_AnalyticalKey"` to `NEW_TABLES` list.

- [ ] **Step 3: Run tests**

```
python -m pytest tests/envmon/test_upgrade_schema.py -v
```

- [ ] **Step 4: Commit**

```bash
git add autogis/core/envmon/gdb_schema.py tests/envmon/test_upgrade_schema.py
git commit -m "feat(gdb_schema): add Env_AnalyticalKey TABLE_SCHEMAS entry"
```

---

### Task 2: `analytical_key.py` + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_analytical_key.py`:

```python
from autogis.core.envmon.analytical_key import (
    build_analytical_key, format_key_text,
)
from autogis.core.envmon.callout_templates import CalloutTable, CellSpec

_FIGURE_SPEC_DATA = {
    "figure_spec_id": "FS-001",
    "site_id": "H281",
    "map_type": "GW_ANALYTICAL",
    "matrix": "GW",
    "analyte_display_order": ["Benzene", "Toluene"],
    "callout_template": {},
}

_ANALYTES = {
    "Benzene": {"canonical_name": "Benzene", "abbreviation": "BNZ",
                "display_order": 1, "default_units_by_matrix": {"GW": "ug/L"}},
    "Toluene": {"canonical_name": "Toluene", "abbreviation": "TOL",
                "display_order": 2, "default_units_by_matrix": {"GW": "ug/L"}},
}


class _MockFigureSpec:
    """Minimal mock so test doesn't need arcpy FigureSpec."""
    data = _FIGURE_SPEC_DATA
    def analyte_list(self, d):
        return [a for a in _FIGURE_SPEC_DATA["analyte_display_order"] if a in d]
    def get(self, k, default=None):
        return self.data.get(k, default)


def test_returns_callout_table():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW")
    assert isinstance(result, CalloutTable)


def test_has_at_least_two_rows():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW")
    assert result.n_rows >= 2   # header + at least one analyte row


def test_each_analyte_appears():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW")
    texts = {c.text for c in result.cells}
    assert "BNZ" in texts or "Benzene" in texts


def test_header_row_contains_matrix():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW", "2026-06-15")
    header_texts = [c.text for c in result.cells if c.row == 1]
    assert any("GW" in t for t in header_texts)


def test_exceedance_cell_has_color_class():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW")
    exc_cells = [c for c in result.cells if c.display_color_class == "EXCEEDANCE"]
    assert len(exc_cells) > 0


def test_nondetect_cell_has_flag():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW")
    nd_cells = [c for c in result.cells if c.display_color_class == "NONDETECT"]
    assert all(c.is_nondetect for c in nd_cells)


def test_empty_analyte_list_no_crash():
    class _Empty(_MockFigureSpec):
        def analyte_list(self, d): return []
    result = build_analytical_key(_Empty(), _ANALYTES, "GW")
    assert result.n_rows >= 1   # header only


def test_format_key_text_contains_abbr():
    result = build_analytical_key(_MockFigureSpec(), _ANALYTES, "GW")
    text = format_key_text(result)
    assert "BNZ" in text or "TOL" in text
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_analytical_key.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/analytical_key.py`**

```python
"""analytical_key.py — build the analytical legend key for figure layouts.

build_analytical_key() and format_key_text() are arcpy-free.
write_analytical_key() is LOCAL (arcpy), # pragma: no cover.
"""
from __future__ import annotations

from typing import Optional

from .callout_templates import CellSpec, CalloutTable, STYLE_TITLE, STYLE_LABEL, STYLE_RESULT

SYMBOL_EXCEEDANCE = "▲"
SYMBOL_DETECTED = "●"
SYMBOL_NONDETECT = "○"
SYMBOL_NOT_SAMPLED = "—"

# display_color_class values matching existing pipeline
_EXCEED = "EXCEEDANCE"
_DETECT = "DETECTED"
_ND = "NONDETECT"
_NS = "NOT_SAMPLED"


def build_analytical_key(
    figure_spec,
    analyte_dictionary: dict,
    matrix: str,
    event_date: Optional[str] = None,
) -> CalloutTable:
    analytes = figure_spec.analyte_list(analyte_dictionary)
    n_cols = 6   # Abbr | Name | Units | ▲ | ● | ○ | — → 6 cols (symbol cols share)
    n_rows = 2 + len(analytes)   # header row + column-label row + data rows
    table = CalloutTable(location_id="__analytical_key__",
                         sample_id="", n_rows=n_rows, n_cols=n_cols)

    # Row 1: header
    header_text = f"Analytical Key — {matrix}"
    if event_date:
        header_text += f" — {event_date}"
    table.cells.append(CellSpec(row=1, col=1, text=header_text,
                                style_class=STYLE_TITLE, col_span=n_cols,
                                is_header=True))

    # Row 2: column labels
    for col, (text, dcc) in enumerate([
        ("Abbr", ""), ("Analyte", ""), ("Units", ""),
        (SYMBOL_EXCEEDANCE, _EXCEED), (SYMBOL_DETECTED, _DETECT),
        (SYMBOL_NONDETECT, _ND), (SYMBOL_NOT_SAMPLED, _NS),
    ], 1):
        if col > n_cols:
            break
        table.cells.append(CellSpec(row=2, col=col, text=text,
                                    style_class=STYLE_LABEL, display_color_class=dcc,
                                    is_header=True))

    # Data rows
    for row_idx, analyte in enumerate(analytes, 3):
        info = analyte_dictionary.get(analyte, {})
        abbr = info.get("abbreviation", analyte[:8])
        units_map = info.get("default_units_by_matrix", {})
        units = units_map.get(matrix, "")
        table.cells.extend([
            CellSpec(row=row_idx, col=1, text=abbr, style_class=STYLE_LABEL,
                     is_analyte_name=True),
            CellSpec(row=row_idx, col=2, text=analyte, style_class=STYLE_LABEL),
            CellSpec(row=row_idx, col=3, text=units, style_class=STYLE_RESULT),
            CellSpec(row=row_idx, col=4, text=SYMBOL_EXCEEDANCE,
                     display_color_class=_EXCEED, is_exceedance=True, is_detected=True),
            CellSpec(row=row_idx, col=5, text=SYMBOL_DETECTED,
                     display_color_class=_DETECT, is_detected=True),
            CellSpec(row=row_idx, col=6, text=SYMBOL_NONDETECT,
                     display_color_class=_ND, is_nondetect=True),
        ])

    return table


def format_key_text(key_table: CalloutTable) -> str:
    by_row: dict[int, list[CellSpec]] = {}
    for c in key_table.cells:
        by_row.setdefault(c.row, []).append(c)
    lines = []
    for row in sorted(by_row):
        cells = sorted(by_row[row], key=lambda c: c.col)
        lines.append("  ".join(c.text for c in cells))
    return "\n".join(lines)


def write_analytical_key(   # pragma: no cover
    gdb_path: str,
    site_id: str,
    figure_spec_id: str,
    key_table: CalloutTable,
    event_date=None,
    matrix: str = "GW",
) -> None:
    import arcpy
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(_P(gdb_path) / "Env_AnalyticalKey")
    if not _ax.Exists(table):
        return
    # Truncate prior rows for this spec
    where = f"SiteID='{site_id}' AND FigureSpecID='{figure_spec_id}'"
    with _ax.da.UpdateCursor(table, ["OBJECTID"], where) as cur:
        for _ in cur:
            cur.deleteRow()
    # Write new rows (one per data row in the CalloutTable)
    data_rows: dict[int, dict] = {}
    for c in key_table.cells:
        if c.row < 3:
            continue
        r = data_rows.setdefault(c.row, {})
        if c.col == 1:
            r["abbr"] = c.text
        elif c.col == 2:
            r["name"] = c.text
        elif c.col == 3:
            r["units"] = c.text
    with _ax.da.InsertCursor(table,
                              ["SiteID", "FigureSpecID", "EventDate", "Matrix",
                               "DisplayOrder", "AnalyteAbbr", "AnalyteName", "Units"]) as cur:
        for i, (row_idx, r) in enumerate(sorted(data_rows.items())):
            cur.insertRow([site_id, figure_spec_id, event_date, matrix,
                           i + 1, r.get("abbr", ""), r.get("name", ""),
                           r.get("units", "")])
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_analytical_key.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/analytical_key.py tests/envmon/test_analytical_key.py
git commit -m "feat(envmon): analytical_key — build_analytical_key() using CellSpec/CalloutTable"
```

---

### Task 3: CLI command

- [ ] **Step 1: Add to `cli.py`** (LOCAL)

```python
@envmon.command("build-analytical-key")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("figure_spec", type=click.Path(exists=True))
@click.option("--analytes", required=True, type=click.Path(exists=True))
@click.option("--matrix", default="GW", show_default=True)
@click.option("--gdb", default=None, type=click.Path(),
              help="Write key to GDB (ArcGIS Pro).")
@click.option("--preview", is_flag=True, default=False, help="Print ASCII key.")
def build_analytical_key_cmd(site_config, figure_spec, analytes, matrix, gdb, preview):
    """Build the analytical legend key for a figure spec."""
    from autogis.core.common.config import load_analyte_dictionary, FigureSpec
    from autogis.core.envmon.analytical_key import (
        build_analytical_key, format_key_text, write_analytical_key)
    fs = FigureSpec.load(Path(figure_spec))
    analyte_dict = load_analyte_dictionary(Path(analytes))
    key = build_analytical_key(fs, analyte_dict, matrix)
    if preview:
        click.echo(format_key_text(key))
    if gdb:
        _guard("build-analytical-key")
        write_analytical_key(gdb, fs.get("site_id", ""), fs.get("figure_spec_id", ""),
                             key, matrix=matrix)
        click.echo(f"Analytical key written to {gdb}/Env_AnalyticalKey")
```

- [ ] **Step 2: Commit**

```bash
git add autogis/adapters/cli.py
git commit -m "feat(cli): add build-analytical-key command"
```
