# BuildAnalyticalKey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `BuildAnalyticalKey` (roadmap 5.5) — the analytical key/legend table for map layouts, generating analyte display names, units, screening levels, exceedance symbology notes, and a "Not Established" flag when levels are absent; headless output (xlsx/csv/markdown) plus an optional arcpy GDB table write via the adapter seam.

**Architecture:**
- New `autogis/core/envmon/build_analytical_key.py` owns the arcpy-free core: `AnalyticalKeyRow` dataclass, `build_analytical_key()` assembly function, and three format helpers (`format_key_markdown`, `write_key_csv`, `write_key_xlsx`). The GDB write stub (`write_analytical_key_gdb_table`) lives in the same file, gated by `# pragma: no cover` and a deferred `import arcpy`.
- `autogis/runtime/capabilities.py` gains one line: `"build-analytical-key": Runtime.HYBRID` (headless by default; `--gdb` path usable inside ArcGIS Pro CLI sessions).
- `autogis/adapters/cli.py` gains `envmon build-analytical-key` using the standard `--out PATH` idiom (format inferred from extension: `.xlsx/.csv/.md`; absent → markdown to stdout).

**Tech Stack:** Python 3.x, openpyxl, PyYAML, click; analyte dict and screening levels loaded by existing `load_analyte_dictionary` / `load_screening_levels` / `screening_for` helpers in `autogis.core.common.config`.

## Global Constraints

- `autogis/core/` and `autogis/adapters/` must import with **neither** `arcpy` **nor** `arcgis` present. All arcpy goes inside `write_analytical_key_gdb_table` behind `# pragma: no cover`.
- Run tests headless: `python -m pytest -q`.
- **`matrix` is a required parameter everywhere** — units (`GW: ug/L` vs `SOIL: mg/kg`) and screening level lookups are both keyed by matrix. A key without a fixed matrix is incoherent.
- **All screening values in the real config are `null` with `_TODO` sources** (deliberate DRAFT stubs). Tests use inline fixtures, not the real YAML files. The "null value" case is the *normal* case; it must produce a `level_established=False` row and render as `NE` ("Not Established"), not blank.
- Emit a `draft_flag=True` mark whenever the screening source contains `"_TODO"` or the value is `None`, reusing the `_TODO` detection pattern from `manage_screening_levels.py`. The markdown output carries a footer note: `*NE = Not Established (pre-production stub; do not use for regulatory reporting)`.
- Default analyte selection: `include_in_default_figures == True`, sorted by `display_order` then canonical name. Override via `analyte_filter: list[str]` (list of canonical names).
- This tool builds a **legend**, not a data evaluation. It does NOT consume `AnalyticalResultRecord` or sample results. "Exceedance symbology notes" = static footnote text on the key table.
- GDB write is a thin stub. The CLI `--gdb` path calls `_guard("build-analytical-key")` then the stub; outside Pro the deferred `import arcpy` raises `ImportError` naturally.
- Branch: `main` (no active worktree constraint named in the roadmap for this tool).
- Frequent small commits. Do NOT squash.

---

### Task 1: Core module `build_analytical_key.py` + core tests

**Files:**
- Create: `autogis/core/envmon/build_analytical_key.py`
- Create: `tests/envmon/test_build_analytical_key.py`

**Interfaces:**
- Consumes: `load_analyte_dictionary(path)` → `dict[str, dict]`, `load_screening_levels(path)` → `dict[str, dict[str, dict]]`, `screening_for(screening_levels, matrix, canonical)` → `Optional[dict]` — all from `autogis.core.common.config`
- Produces (for Task 2):
  - `AnalyticalKeyRow` dataclass — fields: `canonical: str`, `abbreviation: str`, `display_order: int`, `units: str`, `screening_value: Optional[float]`, `screening_units: str`, `screening_source: str`, `level_established: bool`, `draft_flag: bool`
  - `build_analytical_key(analytes: dict, screening_levels: dict, matrix: str, analyte_filter: Optional[list[str]] = None) -> list[AnalyticalKeyRow]`
  - `format_key_markdown(rows: list[AnalyticalKeyRow], matrix: str, site_id: str = "") -> str`
  - `write_key_csv(rows: list[AnalyticalKeyRow], path: Path) -> None`
  - `write_key_xlsx(rows: list[AnalyticalKeyRow], path: Path, matrix: str = "") -> None`
  - `write_analytical_key_gdb_table(gdb_path: str, site_id: str, figure_spec_id: str, rows: list[AnalyticalKeyRow]) -> None`  — `# pragma: no cover`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_build_analytical_key.py`:

```python
"""Tests for build_analytical_key core logic (arcpy-free)."""
import csv
import io
from pathlib import Path

import pytest

from autogis.core.envmon.build_analytical_key import (
    AnalyticalKeyRow,
    build_analytical_key,
    format_key_markdown,
    write_key_csv,
    write_key_xlsx,
)

# ---------------------------------------------------------------------------
# Inline fixtures — do NOT source from real YAML config.
# The real screening_levels.yaml has value: null + _TODO sources throughout;
# that is the NORMAL case and must render cleanly as "NE".
# ---------------------------------------------------------------------------

_ANALYTES = {
    "Benzene": {
        "canonical_name": "Benzene",
        "abbreviation": "B",
        "analytical_group": "VPH_VOC",
        "display_order": 10,
        "default_units_by_matrix": {"GW": "ug/L", "SOIL": "mg/kg"},
        "include_in_default_figures": True,
        "significant_figures": 2,
    },
    "Toluene": {
        "canonical_name": "Toluene",
        "abbreviation": "T",
        "analytical_group": "VPH_VOC",
        "display_order": 20,
        "default_units_by_matrix": {"GW": "ug/L", "SOIL": "mg/kg"},
        "include_in_default_figures": True,
        "significant_figures": 2,
    },
    "Methane": {
        "canonical_name": "Methane",
        "abbreviation": "CH4",
        "analytical_group": "GAS",
        "display_order": 200,
        "default_units_by_matrix": {"GW": "mg/L"},
        "include_in_default_figures": False,  # excluded by default
        "significant_figures": 2,
    },
}

# Normal case: all null + _TODO, matching the real repo config.
_SCREENING_NULL = {
    "GW": {
        "Benzene": {"value": None, "units": "ug/L", "source": "_TODO MDEQ RBSL"},
        "Toluene": {"value": None, "units": "ug/L", "source": "_TODO MDEQ RBSL"},
    }
}

# Synthetic populated case — exercises the "level present" path.
_SCREENING_POPULATED = {
    "GW": {
        "Benzene": {"value": 5.0, "units": "ug/L", "source": "MDEQ MCL Table A"},
        "Toluene": {"value": 1000.0, "units": "ug/L", "source": "MDEQ MCL Table A"},
    }
}


# ---------------------------------------------------------------------------
# build_analytical_key — filtering and ordering
# ---------------------------------------------------------------------------

def test_default_filter_excludes_non_figure_analytes():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    canonicals = [r.canonical for r in rows]
    assert "Methane" not in canonicals


def test_default_filter_includes_figure_analytes():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    canonicals = [r.canonical for r in rows]
    assert "Benzene" in canonicals
    assert "Toluene" in canonicals


def test_rows_sorted_by_display_order():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    orders = [r.display_order for r in rows]
    assert orders == sorted(orders)
    assert rows[0].canonical == "Benzene"
    assert rows[1].canonical == "Toluene"


def test_analyte_filter_restricts_output():
    rows = build_analytical_key(
        _ANALYTES, _SCREENING_NULL, matrix="GW", analyte_filter=["Benzene"]
    )
    assert len(rows) == 1
    assert rows[0].canonical == "Benzene"


def test_units_are_matrix_specific_gw():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.units == "ug/L"


def test_units_are_matrix_specific_soil():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="SOIL")
    # No SOIL screening levels in the null fixture, but Benzene has SOIL units.
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.units == "mg/kg"


def test_units_fallback_when_matrix_absent():
    # Methane has no SOIL entry; analyte_filter overrides default filter.
    rows = build_analytical_key(
        _ANALYTES, {}, matrix="SOIL", analyte_filter=["Methane"]
    )
    # Should fall back to empty string rather than raise.
    assert rows[0].units == ""


# ---------------------------------------------------------------------------
# build_analytical_key — null screening (NORMAL case)
# ---------------------------------------------------------------------------

def test_null_screening_produces_not_established():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.level_established is False
    assert benzene.screening_value is None


def test_null_screening_sets_draft_flag():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.draft_flag is True


def test_null_screening_preserves_source():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert "_TODO" in benzene.screening_source


def test_analyte_with_no_screening_entry_also_not_established():
    # Methane not in _SCREENING_NULL; use analyte_filter to include it.
    rows = build_analytical_key(
        _ANALYTES, _SCREENING_NULL, matrix="GW", analyte_filter=["Methane"]
    )
    methane = rows[0]
    assert methane.level_established is False
    assert methane.draft_flag is True
    assert methane.screening_value is None


# ---------------------------------------------------------------------------
# build_analytical_key — populated screening (synthetic case)
# ---------------------------------------------------------------------------

def test_populated_screening_sets_level_established():
    rows = build_analytical_key(_ANALYTES, _SCREENING_POPULATED, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.level_established is True
    assert benzene.screening_value == 5.0


def test_populated_screening_draft_flag_false_when_no_todo():
    rows = build_analytical_key(_ANALYTES, _SCREENING_POPULATED, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.draft_flag is False


def test_populated_screening_units_from_screening_level():
    rows = build_analytical_key(_ANALYTES, _SCREENING_POPULATED, matrix="GW")
    benzene = next(r for r in rows if r.canonical == "Benzene")
    assert benzene.screening_units == "ug/L"


# ---------------------------------------------------------------------------
# format_key_markdown
# ---------------------------------------------------------------------------

def test_format_markdown_contains_abbreviation():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    md = format_key_markdown(rows, matrix="GW")
    assert "B" in md   # Benzene abbreviation


def test_format_markdown_ne_for_null_screening():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    md = format_key_markdown(rows, matrix="GW")
    assert "NE" in md


def test_format_markdown_draft_banner_when_all_null():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    md = format_key_markdown(rows, matrix="GW")
    # Must carry a disclaimer when screening levels are stubs.
    assert "pre-production" in md.lower() or "draft" in md.lower() or "not established" in md.lower()


def test_format_markdown_shows_value_when_populated():
    rows = build_analytical_key(_ANALYTES, _SCREENING_POPULATED, matrix="GW")
    md = format_key_markdown(rows, matrix="GW")
    assert "5.0" in md or "5" in md


def test_format_markdown_contains_header():
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    md = format_key_markdown(rows, matrix="GW")
    first_line = md.splitlines()[0]
    assert "Analytical Key" in first_line or "Analyte" in first_line


# ---------------------------------------------------------------------------
# write_key_csv
# ---------------------------------------------------------------------------

def test_write_key_csv_creates_file(tmp_path):
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    out = tmp_path / "key.csv"
    write_key_csv(rows, out)
    assert out.exists()


def test_write_key_csv_headers(tmp_path):
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    out = tmp_path / "key.csv"
    write_key_csv(rows, out)
    with out.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
    assert "canonical" in fieldnames
    assert "abbreviation" in fieldnames
    assert "units" in fieldnames
    assert "screening_value" in fieldnames
    assert "level_established" in fieldnames
    assert "draft_flag" in fieldnames


def test_write_key_csv_null_screening_value(tmp_path):
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    out = tmp_path / "key.csv"
    write_key_csv(rows, out)
    with out.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        data = list(reader)
    benzene_row = next(r for r in data if r["canonical"] == "Benzene")
    assert benzene_row["screening_value"] == "" or benzene_row["screening_value"] == "None"
    assert benzene_row["level_established"] in ("False", "false", "0")


# ---------------------------------------------------------------------------
# write_key_xlsx
# ---------------------------------------------------------------------------

def test_write_key_xlsx_creates_file(tmp_path):
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    out = tmp_path / "key.xlsx"
    write_key_xlsx(rows, out, matrix="GW")
    assert out.exists()
    assert out.stat().st_size > 0


def test_write_key_xlsx_sheet_has_header_row(tmp_path):
    from openpyxl import load_workbook
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    out = tmp_path / "key.xlsx"
    write_key_xlsx(rows, out, matrix="GW")
    wb = load_workbook(out)
    ws = wb.active
    header = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    assert "Analyte" in header or "canonical" in header


def test_write_key_xlsx_data_row_count(tmp_path):
    from openpyxl import load_workbook
    rows = build_analytical_key(_ANALYTES, _SCREENING_NULL, matrix="GW")
    out = tmp_path / "key.xlsx"
    write_key_xlsx(rows, out, matrix="GW")
    wb = load_workbook(out)
    ws = wb.active
    # header row + 2 data rows (Benzene, Toluene — Methane excluded by default)
    assert ws.max_row == 3
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_build_analytical_key.py -v
```

Expected: `ImportError: cannot import name 'AnalyticalKeyRow' from 'autogis.core.envmon.build_analytical_key'` (module doesn't exist yet).

- [ ] **Step 3: Create `autogis/core/envmon/build_analytical_key.py`**

```python
"""build_analytical_key.py — Generate the analytical key/legend table for map layouts.

All functions in this module are arcpy-free (headless). The GDB write stub
(write_analytical_key_gdb_table) requires ArcGIS Pro and is marked
# pragma: no cover; import arcpy is deferred inside that function.

Assumption: default analyte selection = include_in_default_figures==True,
sorted by display_order then canonical name. Override via analyte_filter.
Screening levels are always authoritative from screening_levels.yaml
(secondary source; primary is the workbook RBSL row, which is not in scope
here). All values in the current DRAFT config are null — that is expected
and renders as NE (Not Established) with a draft_flag.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

_BOLD = Font(bold=True)
_DRAFT_FILL = PatternFill(fill_type="solid", fgColor="FFF2CC")  # light amber for draft rows
_MAX_COL_WIDTH = 40


@dataclass
class AnalyticalKeyRow:
    canonical: str
    abbreviation: str
    display_order: int
    units: str                       # matrix-specific from analyte dict
    screening_value: Optional[float] # None = not established
    screening_units: str             # from screening_levels entry; "" when absent
    screening_source: str            # from screening_levels entry; "" when absent
    level_established: bool          # True only when screening_value is not None
    draft_flag: bool                 # True when source has "_TODO" or value is None


def _is_draft(entry: Optional[dict]) -> bool:
    """Return True when a screening entry is a DRAFT stub or absent."""
    if entry is None:
        return True
    if entry.get("value") is None:
        return True
    if "_TODO" in str(entry.get("source", "")):
        return True
    return False


def build_analytical_key(
    analytes: dict,
    screening_levels: dict,
    matrix: str,
    analyte_filter: Optional[list] = None,
) -> list[AnalyticalKeyRow]:
    """Assemble sorted AnalyticalKeyRow list from analyte dict + screening levels.

    Args:
        analytes: output of load_analyte_dictionary(path) — {canonical: {…}}
        screening_levels: output of load_screening_levels(path) — {matrix: {canonical: {…}}}
        matrix: "GW" or "SOIL" (required; both units and screening are keyed by matrix)
        analyte_filter: optional list of canonical names to include;
            if None, defaults to analytes where include_in_default_figures == True
    """
    matrix_screening = (screening_levels.get(matrix) or {})

    rows: list[AnalyticalKeyRow] = []
    for canonical, entry in analytes.items():
        if canonical.startswith("_"):
            continue
        if not isinstance(entry, dict):
            continue

        # Apply filter
        if analyte_filter is not None:
            if canonical not in analyte_filter:
                continue
        else:
            if not entry.get("include_in_default_figures", False):
                continue

        # Units from analyte dict, matrix-specific
        units_by_matrix = entry.get("default_units_by_matrix") or {}
        units = units_by_matrix.get(matrix, "")

        # Screening level — may be None (expected DRAFT case)
        sl_entry = matrix_screening.get(canonical)
        if sl_entry and isinstance(sl_entry, dict):
            screening_value = sl_entry.get("value")  # None is normal
            screening_units = sl_entry.get("units", "")
            screening_source = sl_entry.get("source", "")
        else:
            screening_value = None
            screening_units = ""
            screening_source = ""

        level_established = screening_value is not None
        draft = _is_draft(sl_entry)

        rows.append(AnalyticalKeyRow(
            canonical=canonical,
            abbreviation=str(entry.get("abbreviation", canonical)),
            display_order=int(entry.get("display_order", 9999)),
            units=units,
            screening_value=screening_value,
            screening_units=screening_units,
            screening_source=screening_source,
            level_established=level_established,
            draft_flag=draft,
        ))

    rows.sort(key=lambda r: (r.display_order, r.canonical))
    return rows


# ---------------------------------------------------------------------------
# Output helpers — headless (openpyxl / csv only)
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES = [
    "canonical", "abbreviation", "display_order", "units",
    "screening_value", "screening_units", "screening_source",
    "level_established", "draft_flag",
]

_XLSX_HEADERS = [
    "Analyte", "Abbr", "Order", "Units",
    "Screening Level", "SL Units", "SL Source",
    "Level Established", "Draft/Stub",
]


def format_key_markdown(
    rows: list[AnalyticalKeyRow],
    matrix: str,
    site_id: str = "",
) -> str:
    """Render rows as a markdown table with header and footnote."""
    title = f"Analytical Key — Matrix: {matrix}"
    if site_id:
        title += f"  |  Site: {site_id}"

    lines = [f"# {title}", ""]
    lines.append(
        f"| {'Analyte':<28} | {'Abbr':<6} | {'Units':<10} | {'Screening Level':>16} | {'SL Units':<10} | {'Source'} |"
    )
    lines.append(
        f"| {'-'*28} | {'-'*6} | {'-'*10} | {'-'*16} | {'-'*10} | {'-'*30} |"
    )
    has_draft = False
    for r in rows:
        sl_display = f"{r.screening_value}" if r.level_established else "NE"
        if r.draft_flag:
            sl_display += " *"
            has_draft = True
        lines.append(
            f"| {r.canonical:<28} | {r.abbreviation:<6} | {r.units:<10} | {sl_display:>16} | {r.screening_units:<10} | {r.screening_source} |"
        )

    lines.append("")
    lines.append(
        "**Legend:** Values in **bold** on map figures exceed the screening level. "
        "J = estimated value, U = non-detect at reporting limit."
    )
    lines.append("")
    if has_draft:
        lines.append(
            "> \\* **NE = Not Established.** "
            "Screening levels marked \\* are pre-production stubs (source contains _TODO). "
            "Do not use for regulatory reporting until replaced with verified citations."
        )
    return "\n".join(lines)


def write_key_csv(rows: list[AnalyticalKeyRow], path: Path) -> None:
    """Write key rows to CSV."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "canonical": r.canonical,
                "abbreviation": r.abbreviation,
                "display_order": r.display_order,
                "units": r.units,
                "screening_value": r.screening_value if r.screening_value is not None else "",
                "screening_units": r.screening_units,
                "screening_source": r.screening_source,
                "level_established": r.level_established,
                "draft_flag": r.draft_flag,
            })


def write_key_xlsx(
    rows: list[AnalyticalKeyRow],
    path: Path,
    matrix: str = "",
) -> None:
    """Write key rows to Excel workbook (headless, openpyxl only).

    Sheet: 'AnalyticalKey'. Bold header row. Amber fill on draft/stub rows.
    Column widths auto-sized to content (capped at 40 characters).
    """
    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "AnalyticalKey"

    # Header row
    for ci, header in enumerate(_XLSX_HEADERS, start=1):
        cell = ws.cell(row=1, column=ci, value=header)
        cell.font = _BOLD

    # Data rows
    for ri, r in enumerate(rows, start=2):
        sl_display = r.screening_value if r.level_established else None
        values = [
            r.canonical,
            r.abbreviation,
            r.display_order,
            r.units,
            sl_display,
            r.screening_units,
            r.screening_source,
            r.level_established,
            r.draft_flag,
        ]
        for ci, val in enumerate(values, start=1):
            cell = ws.cell(row=ri, column=ci, value=val)
            if r.draft_flag:
                cell.fill = _DRAFT_FILL

    # Auto-size columns
    for col in ws.columns:
        max_len = 0
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, _MAX_COL_WIDTH)

    # Matrix label in a cell below the table for context
    if matrix:
        ws.cell(row=len(rows) + 3, column=1, value=f"Matrix: {matrix}")

    wb.save(path)


def write_analytical_key_gdb_table(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    figure_spec_id: str,
    rows: list[AnalyticalKeyRow],
) -> None:
    """Write Env_AnalyticalKey table in GDB (ArcGIS Pro / arcpy only).

    Fields written:
        SiteID, FigureSpecID, AnalyticalOrder (Long), CanonicalName, Abbreviation,
        Matrix (inferred from units column), Units, ScreeningValue (Double/None),
        ScreeningUnits, ScreeningSource, LevelEstablished (Short 0/1),
        DraftFlag (Short 0/1), GeneratedDate (Date).
    Assumption: Env_AnalyticalKey table already exists in the GDB (created by
    upgrade-schema). Use InsertCursor to append; existing rows for the same
    SiteID+FigureSpecID are NOT purged here — purge upstream if regenerating.
    """
    import arcpy
    from datetime import datetime
    from pathlib import Path as _P

    table = str(_P(gdb_path) / "Env_AnalyticalKey")
    fields = [
        "SiteID", "FigureSpecID", "AnalyticalOrder", "CanonicalName",
        "Abbreviation", "Units", "ScreeningValue", "ScreeningUnits",
        "ScreeningSource", "LevelEstablished", "DraftFlag", "GeneratedDate",
    ]
    generated = datetime.now()
    with arcpy.da.InsertCursor(table, fields) as cur:
        for r in rows:
            cur.insertRow([
                site_id,
                figure_spec_id,
                r.display_order,
                r.canonical,
                r.abbreviation,
                r.units,
                r.screening_value,    # None → arcpy inserts NULL
                r.screening_units,
                r.screening_source,
                int(r.level_established),
                int(r.draft_flag),
                generated,
            ])
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_analytical_key.py -v
```

Expected: all tests PASS.

If `test_write_key_xlsx_sheet_has_header_row` fails because header cells don't match: confirm `_XLSX_HEADERS[0]` is `"Analyte"` (the test asserts `"Analyte" in header`).

- [ ] **Step 5: Full suite regression check**

```
python -m pytest -q
```

Expected: all previously passing tests still PASS; new tests add to the count.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/build_analytical_key.py tests/envmon/test_build_analytical_key.py
git commit -m "feat(envmon): build_analytical_key — legend table, NE draft handling, xlsx/csv/md output"
```

---

### Task 2: Capabilities registration + CLI command + CLI tests

**Files:**
- Modify: `autogis/runtime/capabilities.py` — add `"build-analytical-key": Runtime.HYBRID`
- Modify: `autogis/adapters/cli.py` — add `@envmon.command("build-analytical-key")`
- Create: `tests/envmon/test_cli_build_analytical_key.py`

**Interfaces:**
- Consumes from Task 1: `build_analytical_key`, `format_key_markdown`, `write_key_csv`, `write_key_xlsx`, `write_analytical_key_gdb_table`
- Consumes from config: `load_analyte_dictionary(path)`, `load_screening_levels(path)`
- Produces: `autogis envmon build-analytical-key` CLI command

- [ ] **Step 1: Write failing CLI tests**

Create `tests/envmon/test_cli_build_analytical_key.py`:

```python
"""CLI integration tests for envmon build-analytical-key (arcpy-free paths)."""
import csv
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis

# Use the real repo config files.
# Note: all screening values in the real YAML are null (_TODO stubs).
# Tests must not assert numeric screening values from these files.
_CONFIG = Path(__file__).parent.parent.parent / "autogis" / "config"
_ANALYTES = str(_CONFIG / "analytes" / "analyte_dictionary.yaml")
_SCREENING = str(_CONFIG / "screening_levels" / "screening_levels.yaml")


def _invoke(*args):
    return CliRunner(mix_stderr=False).invoke(autogis, list(args))


def test_command_in_envmon_help():
    result = _invoke("envmon", "--help")
    assert result.exit_code == 0
    assert "build-analytical-key" in result.output


def test_command_help_shows_matrix_option():
    result = _invoke("envmon", "build-analytical-key", "--help")
    assert result.exit_code == 0
    assert "--matrix" in result.output


def test_markdown_to_stdout_gw(tmp_path):
    """No --out flag → markdown printed to stdout; exit 0."""
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "GW",
    )
    assert result.exit_code == 0, result.output
    assert "Analytical Key" in result.output
    # Real screening values are null; NE must appear.
    assert "NE" in result.output


def test_csv_output(tmp_path):
    out = str(tmp_path / "key.csv")
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "GW",
        "--out", out,
    )
    assert result.exit_code == 0, result.output
    assert Path(out).exists()
    with open(out, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) > 0
    assert "canonical" in reader.fieldnames
    # All values null in the real config — level_established must be False.
    assert all(r["level_established"] in ("False", "false", "0") for r in rows)


def test_xlsx_output(tmp_path):
    from openpyxl import load_workbook
    out = str(tmp_path / "key.xlsx")
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "GW",
        "--out", out,
    )
    assert result.exit_code == 0, result.output
    assert Path(out).exists()
    wb = load_workbook(out)
    ws = wb.active
    assert ws.title == "AnalyticalKey"
    header = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    assert "Analyte" in header


def test_markdown_output_file(tmp_path):
    out = str(tmp_path / "key.md")
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "GW",
        "--out", out,
    )
    assert result.exit_code == 0, result.output
    assert Path(out).exists()
    content = Path(out).read_text(encoding="utf-8")
    assert "Analytical Key" in content
    assert "NE" in content


def test_analytes_list_filter(tmp_path):
    out = str(tmp_path / "key.csv")
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "GW",
        "--analytes-list", "Benzene",
        "--out", out,
    )
    assert result.exit_code == 0, result.output
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["canonical"] == "Benzene"


def test_soil_matrix(tmp_path):
    out = str(tmp_path / "key_soil.csv")
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "SOIL",
        "--out", out,
    )
    assert result.exit_code == 0, result.output
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    # Benzene has SOIL units mg/kg in the analyte dict.
    benzene = next((r for r in rows if r["canonical"] == "Benzene"), None)
    assert benzene is not None
    assert benzene["units"] == "mg/kg"


def test_gdb_flag_raises_outside_pro():
    """--gdb outside ArcGIS Pro produces a clean ClickException (ImportError on arcpy)."""
    result = _invoke(
        "envmon", "build-analytical-key",
        _ANALYTES, _SCREENING,
        "--matrix", "GW",
        "--gdb", "/nonexistent/path.gdb",
        "--site", "TEST",
        "--figure-spec-id", "TEST_SPEC",
    )
    # arcpy not available in test env; must not produce a raw traceback.
    # Either an ImportError is surfaced as ClickException or the test env
    # has arcpy absent and a clean error message appears.
    assert result.exit_code != 0
    # Should NOT be a raw Python traceback leaked to the user.
    assert "Traceback" not in result.output or "Error" in result.output
```

- [ ] **Step 2: Run CLI tests to confirm they fail**

```
python -m pytest tests/envmon/test_cli_build_analytical_key.py -v
```

Expected: `Error: No such command 'build-analytical-key'`.

- [ ] **Step 3: Register capability in `autogis/runtime/capabilities.py`**

Open `autogis/runtime/capabilities.py`. Add one line inside `TOOLS` (after the `"run-history"` entry):

```python
    "build-analytical-key": Runtime.HYBRID,  # tool 5.5: headless output + optional LOCAL gdb write
```

Full updated `TOOLS` dict tail (add after `"run-history"` line, before the closing `}`):

```python
    "build-analytical-key": Runtime.HYBRID,  # tool 5.5
```

- [ ] **Step 4: Add CLI command to `autogis/adapters/cli.py`**

Add the following block after the `manage-screening-levels` command (around line 183):

```python
@envmon.command("build-analytical-key")
@click.argument("analytes", metavar="ANALYTES_YAML", type=click.Path(exists=True))
@click.argument("screening", metavar="SCREENING_YAML", type=click.Path(exists=True))
@click.option("--matrix", required=True, type=click.Choice(["GW", "SOIL"]),
              help="Matrix to build key for (GW or SOIL). Required: units and "
                   "screening levels are both keyed by matrix.")
@click.option("--out", default=None, type=click.Path(),
              help="Output file path. Format inferred from extension: "
                   ".xlsx, .csv, or .md. If absent, markdown is written to stdout.")
@click.option("--analytes-list", default=None,
              help="Comma-separated list of canonical analyte names to include. "
                   "Default: all analytes where include_in_default_figures=True.")
@click.option("--gdb", default=None, type=click.Path(),
              help="Write Env_AnalyticalKey GDB table (requires ArcGIS Pro).")
@click.option("--site", "site_id", default="", show_default=False,
              help="Site ID label for header and GDB write.")
@click.option("--figure-spec-id", default="", show_default=False,
              help="FigureSpecID label for GDB write.")
def build_analytical_key_cmd(
    analytes, screening, matrix, out, analytes_list, gdb, site_id, figure_spec_id
):
    """Tool 5.5: generate the analytical key/legend table for map layouts (headless).

    Reads the analyte dictionary and screening levels; outputs a sorted table
    of display names, units, and screening levels per analyte. Null screening
    values (pre-production stubs) render as NE (Not Established) with a
    DRAFT footnote.

    Output format is inferred from --out extension (.xlsx / .csv / .md).
    Without --out, markdown is printed to stdout.

    --gdb requires ArcGIS Pro (arcpy). Without Pro, a clean error is shown.
    """
    from autogis.core.common.config import load_analyte_dictionary, load_screening_levels
    from autogis.core.envmon.build_analytical_key import (
        build_analytical_key,
        format_key_markdown,
        write_key_csv,
        write_key_xlsx,
        write_analytical_key_gdb_table,
    )

    adict = load_analyte_dictionary(Path(analytes))
    slevels = load_screening_levels(Path(screening))

    filter_list = None
    if analytes_list:
        filter_list = [a.strip() for a in analytes_list.split(",") if a.strip()]

    rows = build_analytical_key(adict, slevels, matrix=matrix, analyte_filter=filter_list)

    if not rows:
        raise click.ClickException(
            f"No analytes matched for matrix={matrix!r}. "
            "Check --analytes-list or include_in_default_figures flags in the analyte dict."
        )

    if out is None:
        # Default: markdown to stdout
        click.echo(format_key_markdown(rows, matrix=matrix, site_id=site_id))
    else:
        out_path = Path(out)
        suffix = out_path.suffix.lower()
        if suffix == ".xlsx":
            write_key_xlsx(rows, out_path, matrix=matrix)
        elif suffix == ".csv":
            write_key_csv(rows, out_path)
        else:
            # .md or any other extension → markdown
            out_path.write_text(
                format_key_markdown(rows, matrix=matrix, site_id=site_id),
                encoding="utf-8",
            )
        click.echo(f"Wrote analytical key: {out_path}  ({len(rows)} analytes, matrix={matrix})")

    if gdb:
        _guard("build-analytical-key")
        try:
            write_analytical_key_gdb_table(gdb, site_id, figure_spec_id, rows)
            click.echo(f"Written to GDB: {gdb} / Env_AnalyticalKey")
        except ImportError:
            raise click.ClickException(
                "arcpy is not available. Run build-analytical-key --gdb inside "
                "ArcGIS Pro, or use the BuildAnalyticalKey tool in the .pyt toolbox."
            )
```

- [ ] **Step 5: Run CLI tests**

```
python -m pytest tests/envmon/test_cli_build_analytical_key.py -v
```

Expected: all tests PASS.

Troubleshooting:
- If `test_gdb_flag_raises_outside_pro` fails because `result.output` is empty: use `result.output + (result.exception and str(result.exception) or "")` in the assertion — the CliRunner captures `click.ClickException` in `output`, but if arcpy is entirely absent the ImportError is caught and re-raised as ClickException by the `except ImportError` block above.
- If `test_csv_output` fails on `level_established` values: CSV rows are string `"False"` — the assertion covers both `"False"` and `"false"` and `"0"`.

- [ ] **Step 6: Full suite regression**

```
python -m pytest -q
```

Expected: all previously passing tests still PASS. The new test files add to the count.

- [ ] **Step 7: Commit**

```bash
git add autogis/runtime/capabilities.py autogis/adapters/cli.py \
        tests/envmon/test_cli_build_analytical_key.py
git commit -m "feat(cli): add envmon build-analytical-key command (tool 5.5, headless, optional GDB)"
```

---

## Self-Review

### 1. Spec coverage

| Roadmap requirement | Covered by |
|---|---|
| Analyte display names and abbreviations | `AnalyticalKeyRow.canonical`, `.abbreviation` — Task 1 |
| Units (matrix-specific) | `.units` sourced from `default_units_by_matrix[matrix]` — Task 1 |
| Screening levels (when established) | `.screening_value`, `.screening_units`, `.screening_source` — Task 1 |
| Exceedance symbology notes | Static footnote in `format_key_markdown` ("values in bold exceed…", qualifiers legend) — Task 1 |
| NE / Not Established when level absent | `draft_flag`, `level_established=False`, "NE" render — Task 1 |
| DRAFT stub warning | Banner footnote + amber xlsx fill when `draft_flag=True` — Task 1 |
| Headless output: xlsx | `write_key_xlsx` (openpyxl) — Task 1 |
| Headless output: csv | `write_key_csv` — Task 1 |
| Headless output: markdown | `format_key_markdown` — Task 1 |
| Optional GDB table | `write_analytical_key_gdb_table` (`# pragma: no cover`) — Task 1 |
| CLI surface | `envmon build-analytical-key` — Task 2 |
| Capabilities registry entry | `"build-analytical-key": Runtime.HYBRID` — Task 2 |
| Consumes analyte dict + screening levels | Via `load_analyte_dictionary` / `load_screening_levels` from `autogis.core.common.config` — both tasks |
| arcpy-free invariant | All core functions import no arcpy; GDB stub defers import — Task 1 |

### 2. Placeholder scan

No TBD, TODO (outside the real YAML stubs), or "implement later" in any code block. All test assertions contain actual values. All function signatures are consistent across tasks.

### 3. Type consistency

- `build_analytical_key(analytes, screening_levels, matrix, analyte_filter)` — exactly matches CLI usage in Task 2.
- `format_key_markdown(rows, matrix, site_id)` — CLI calls `format_key_markdown(rows, matrix=matrix, site_id=site_id)` ✓
- `write_key_csv(rows, path)` — CLI calls `write_key_csv(rows, out_path)` ✓
- `write_key_xlsx(rows, path, matrix)` — CLI calls `write_key_xlsx(rows, out_path, matrix=matrix)` ✓
- `write_analytical_key_gdb_table(gdb_path, site_id, figure_spec_id, rows)` — CLI calls with same positional order ✓
- `AnalyticalKeyRow` fields referenced in tests: `canonical`, `abbreviation`, `display_order`, `units`, `screening_value`, `screening_units`, `screening_source`, `level_established`, `draft_flag` — all defined in the dataclass ✓

### 4. DRAFT screening risk (key risk per spec)

- All test assertions against real config files assert `NE` and `level_established=False` — not numeric values. ✓
- The one test with a populated value (`_SCREENING_POPULATED`) uses an inline synthetic fixture — not from the repo YAML. ✓
- `format_key_markdown` carries the mandatory footnote whenever `draft_flag` is True on any row. ✓
