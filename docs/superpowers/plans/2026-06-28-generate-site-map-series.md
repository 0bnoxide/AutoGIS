# GenerateSiteMapSeries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `GenerateSiteMapSeries` — iterate pages of an ArcGIS Pro map series layout, filter by page name, export each page to PDF/PNG, and optionally combine all exported PDFs into a single document.

**Architecture:**
- New: `autogis/core/envmon/map_series.py`
- Modify: `autogis/adapters/cli.py` — add `generate-map-series` command (LOCAL, `_guard`)
- Modify: `autogis/runtime/capabilities.py` — register `"generate-map-series": Runtime.LOCAL`
- New: `tests/envmon/test_map_series.py`

## Global Constraints

- Arcpy imports inside function bodies only; module-level import is `from ...runtime.sessions import arcpy_env as _arcpy` (arcpy-free, as in `export_figures.py`).
- `QACollector` / `QARecord` / `SEV_*` from `autogis.core.common.qa`.
- All pure logic (output path construction, page filtering) is arcpy-free and directly unit-tested.
- Arcpy-dependent paths (`export_map_series`, `list_map_series_pages`) tested with `unittest.mock.patch`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `map_series.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_map_series.py`:

```python
"""Tests for map_series.py — arcpy-free logic tested directly; arcpy paths mocked."""
from pathlib import Path
from unittest import mock

import pytest

from autogis.core.envmon.map_series import (
    MapSeriesConfig,
    MapSeriesResult,
    build_output_path,
    export_map_series,
    filter_pages,
    list_map_series_pages,
)


# ---------------------------------------------------------------------------
# Pure / arcpy-free tests
# ---------------------------------------------------------------------------

def test_build_output_path_pdf(tmp_path):
    p = build_output_path(tmp_path, "Site A - Sheet 1", "PDF")
    assert p == tmp_path / "Site A - Sheet 1.pdf"


def test_build_output_path_png(tmp_path):
    p = build_output_path(tmp_path, "Sheet 2", "PNG")
    assert p.suffix == ".png"


def test_build_output_path_uses_out_dir(tmp_path):
    p = build_output_path(tmp_path, "PageX", "PDF")
    assert p.parent == tmp_path


def test_filter_pages_none_returns_all():
    assert filter_pages(["A", "B", "C"], None) == ["A", "B", "C"]


def test_filter_pages_empty_list_returns_all():
    assert filter_pages(["A", "B"], []) == ["A", "B"]


def test_filter_pages_subset():
    result = filter_pages(["A", "B", "C"], ["A", "C"])
    assert result == ["A", "C"]


def test_filter_pages_unknown_name_dropped():
    result = filter_pages(["A", "B"], ["A", "X"])
    assert result == ["A"]


def test_map_series_config_defaults():
    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=Path("/out"),
    )
    assert cfg.format == "PDF"
    assert cfg.dpi == 300
    assert cfg.pages is None
    assert cfg.combine_pdf is False


# ---------------------------------------------------------------------------
# Arcpy-mocked helpers
# ---------------------------------------------------------------------------

def _make_arcpy_mock(page_names: list):
    """Build a minimal arcpy mock whose map series yields the given page names."""
    arcpy = mock.MagicMock()

    ms = mock.MagicMock()
    ms.enabled = True
    ms.pageCount = len(page_names)
    ms.pageNameField = "Name"
    # side_effect returns one name per call in order (first loop only touches it once
    # per iteration)
    ms.pageRow.getValue.side_effect = list(page_names)

    layout = mock.MagicMock()
    layout.name = "Map Series"
    layout.mapSeries = ms

    aprx = mock.MagicMock()
    aprx.listLayouts.return_value = [layout]
    arcpy.mp.ArcGISProject.return_value = aprx
    arcpy.mp.PDFDocumentCreate.return_value = mock.MagicMock()

    return arcpy, layout, ms


# ---------------------------------------------------------------------------
# Arcpy-mocked tests — export_map_series
# ---------------------------------------------------------------------------

@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_export_all_pages(mock_arcpy_fn, tmp_path):
    arcpy, _, _ = _make_arcpy_mock(["A", "B", "C"])
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
    )
    result = export_map_series(cfg)
    assert len(result.exported) == 3
    assert len(result.skipped) == 0


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_export_filtered_pages_two_of_three(mock_arcpy_fn, tmp_path):
    """filter=['A','C'] from ['A','B','C'] → 2 exported, 1 skipped."""
    arcpy, _, _ = _make_arcpy_mock(["A", "B", "C"])
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
        pages=["A", "C"],
    )
    result = export_map_series(cfg)
    assert len(result.exported) == 2
    assert "B" in result.skipped


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_combine_pdf_creates_combined(mock_arcpy_fn, tmp_path):
    arcpy, _, _ = _make_arcpy_mock(["A", "B"])
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
        combine_pdf=True,
    )
    result = export_map_series(cfg)
    assert result.combined is not None
    arcpy.mp.PDFDocumentCreate.assert_called_once()


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_combine_pdf_false_no_combined(mock_arcpy_fn, tmp_path):
    arcpy, _, _ = _make_arcpy_mock(["A"])
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
        combine_pdf=False,
    )
    result = export_map_series(cfg)
    assert result.combined is None
    arcpy.mp.PDFDocumentCreate.assert_not_called()


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_no_map_series_returns_error(mock_arcpy_fn, tmp_path):
    arcpy = mock.MagicMock()
    layout = mock.MagicMock()
    layout.name = "Map Series"
    layout.mapSeries = None
    aprx = mock.MagicMock()
    aprx.listLayouts.return_value = [layout]
    arcpy.mp.ArcGISProject.return_value = aprx
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
    )
    result = export_map_series(cfg)
    assert len(result.exported) == 0
    assert any(r.category == "no_map_series" for r in result.qa.records)


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_layout_not_found_returns_error(mock_arcpy_fn, tmp_path):
    arcpy = mock.MagicMock()
    aprx = mock.MagicMock()
    aprx.listLayouts.return_value = []
    arcpy.mp.ArcGISProject.return_value = aprx
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
    )
    result = export_map_series(cfg)
    assert len(result.exported) == 0
    assert any(r.category == "layout_not_found" for r in result.qa.records)


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_unsupported_format_returns_error(mock_arcpy_fn, tmp_path):
    arcpy, _, _ = _make_arcpy_mock(["A"])
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
        format="TIFF",
    )
    result = export_map_series(cfg)
    assert len(result.exported) == 0
    assert any(r.category == "unsupported_format" for r in result.qa.records)


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_out_dir_created(mock_arcpy_fn, tmp_path):
    arcpy, _, _ = _make_arcpy_mock(["A"])
    mock_arcpy_fn.return_value = arcpy

    out_dir = tmp_path / "nested" / "output"
    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=out_dir,
    )
    export_map_series(cfg)
    assert out_dir.exists()


@mock.patch("autogis.core.envmon.map_series._arcpy")
def test_qa_info_on_success(mock_arcpy_fn, tmp_path):
    arcpy, _, _ = _make_arcpy_mock(["A", "B"])
    mock_arcpy_fn.return_value = arcpy

    cfg = MapSeriesConfig(
        aprx_path=Path("p.aprx"),
        layout_name="Map Series",
        out_dir=tmp_path,
    )
    result = export_map_series(cfg)
    assert any(r.category == "map_series_complete" for r in result.qa.records)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_map_series.py -v
```

Expected: `ImportError` — `map_series` does not exist yet.

- [ ] **Step 3: Create `autogis/core/envmon/map_series.py`**

```python
"""map_series.py — ArcGIS Pro map series (paginated) layout export (Tool 5.6).

Iterates pages of a SpatialMapSeries or MapSeries on a Layout, filters by page
name, exports each selected page to PDF or PNG, and optionally combines all
exported PDFs into a single document using arcpy.mp.PDFDocumentCreate.

Arcpy-free helpers (build_output_path, filter_pages) are importable without
an ArcGIS Pro licence and are tested directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING
from ...runtime.sessions import arcpy_env as _arcpy

_EXTS = {"PDF": ".pdf", "PNG": ".png"}


@dataclass
class MapSeriesConfig:
    """Parameters for a single map series export run."""

    aprx_path: Path
    layout_name: str
    out_dir: Path
    format: str = "PDF"          # PDF or PNG
    dpi: int = 300
    pages: Optional[List[str]] = None   # None or [] → export all pages
    combine_pdf: bool = False


@dataclass
class MapSeriesResult:
    """Results returned by export_map_series."""

    exported: List[Path] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    combined: Optional[Path] = None
    qa: QACollector = field(default_factory=QACollector)


# ---------------------------------------------------------------------------
# Arcpy-free helpers
# ---------------------------------------------------------------------------

def build_output_path(out_dir: Path, page_name: str, fmt: str) -> Path:
    """Return the destination path for a single page export.

    Args:
        out_dir:   Directory that will receive the file.
        page_name: Name of the map series page (used as the file stem).
        fmt:       "PDF" or "PNG" (case-insensitive).

    Returns:
        Absolute Path with the correct extension.
    """
    ext = _EXTS.get(fmt.upper(), ".pdf")
    return Path(out_dir) / f"{page_name}{ext}"


def filter_pages(all_pages: List[str], wanted: Optional[List[str]]) -> List[str]:
    """Return the subset of pages to export.

    Args:
        all_pages: Full ordered list of page names from the map series.
        wanted:    Caller-supplied filter list.  None or empty → keep all.

    Returns:
        Ordered list of page names that should be exported.
    """
    if not wanted:
        return list(all_pages)
    wanted_set = {p.strip() for p in wanted}
    return [p for p in all_pages if p in wanted_set]


# ---------------------------------------------------------------------------
# Arcpy-dependent functions
# ---------------------------------------------------------------------------

def list_map_series_pages(aprx_path: Path, layout_name: str) -> List[str]:
    """Return all page names in the map series without exporting.

    Useful as a preview / ``--list-pages`` shortcut before a full export run.
    Requires arcpy (LOCAL runtime).

    Args:
        aprx_path:   Path to the ArcGIS Pro project (.aprx).
        layout_name: Name of the layout that has a map series enabled.

    Returns:
        Ordered list of page name strings.

    Raises:
        ValueError: If the layout is missing or has no enabled map series.
    """
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    try:
        layout = next(
            (lyt for lyt in aprx.listLayouts() if lyt.name == layout_name), None
        )
        if layout is None:
            raise ValueError(
                f"Layout {layout_name!r} not found in {aprx_path}"
            )
        ms = layout.mapSeries
        if ms is None or not ms.enabled:
            raise ValueError(
                f"Layout {layout_name!r} has no enabled map series."
            )
        names: List[str] = []
        for i in range(1, ms.pageCount + 1):
            ms.currentPageNumber = i
            names.append(ms.pageRow.getValue(ms.pageNameField))
        return names
    finally:
        del aprx


def export_map_series(config: MapSeriesConfig) -> MapSeriesResult:
    """Export each selected page in the map series layout.

    Workflow:
    1. Open the APRX and locate the named layout.
    2. Verify the layout has an enabled MapSeries / SpatialMapSeries.
    3. Collect all page names by iterating currentPageNumber.
    4. Apply the page filter (config.pages).
    5. For each selected page, set currentPageNumber and export.
    6. If config.combine_pdf is True, merge all exported PDFs.

    Requires arcpy (LOCAL runtime).  All imports of arcpy happen inside this
    function body; the module can be imported without arcpy present.

    Args:
        config: MapSeriesConfig with all export parameters.

    Returns:
        MapSeriesResult with lists of exported paths, skipped page names,
        optional combined PDF path, and a QACollector.
    """
    arcpy = _arcpy()
    result = MapSeriesResult(qa=QACollector())
    qa = result.qa
    fmt = config.format.upper()

    if fmt not in _EXTS:
        qa.add(QARecord(
            SEV_ERROR, "unsupported_format",
            f"Format {fmt!r} is not supported; use PDF or PNG.",
        ))
        return result

    Path(config.out_dir).mkdir(parents=True, exist_ok=True)
    aprx = arcpy.mp.ArcGISProject(str(config.aprx_path))

    try:
        layout = next(
            (lyt for lyt in aprx.listLayouts() if lyt.name == config.layout_name),
            None,
        )
        if layout is None:
            qa.add(QARecord(
                SEV_ERROR, "layout_not_found",
                f"Layout {config.layout_name!r} not found in {config.aprx_path}.",
            ))
            return result

        ms = layout.mapSeries
        if ms is None or not ms.enabled:
            qa.add(QARecord(
                SEV_ERROR, "no_map_series",
                f"Layout {config.layout_name!r} has no enabled map series.",
            ))
            return result

        # --- Collect all page names (first pass) ---
        all_pages: List[tuple] = []  # (1-based index, page_name)
        for i in range(1, ms.pageCount + 1):
            ms.currentPageNumber = i
            all_pages.append((i, ms.pageRow.getValue(ms.pageNameField)))

        # --- Apply filter ---
        wanted_names = filter_pages(
            [name for _, name in all_pages], config.pages
        )
        wanted_set = set(wanted_names)

        pdfs: List[Path] = []

        for page_num, page_name in all_pages:
            if page_name not in wanted_set:
                result.skipped.append(page_name)
                continue

            out = build_output_path(config.out_dir, page_name, fmt)
            ms.currentPageNumber = page_num  # select page before export

            if fmt == "PDF":
                layout.exportToPDF(
                    str(out),
                    resolution=config.dpi,
                    page_range_type="CURRENT",
                )
                pdfs.append(out)
            else:  # PNG
                layout.exportToPNG(str(out), resolution=config.dpi)

            result.exported.append(out)
            qa.add(QARecord(
                SEV_INFO, "page_exported",
                f"Exported page {page_name!r} → {out.name}",
            ))

        # --- Combine PDFs ---
        if config.combine_pdf and pdfs:
            combined = Path(config.out_dir) / f"{config.layout_name}_combined.pdf"
            pdf_doc = arcpy.mp.PDFDocumentCreate(str(combined))
            for p in pdfs:
                pdf_doc.appendPages(str(p))
            pdf_doc.saveAndClose()
            result.combined = combined
            qa.add(QARecord(
                SEV_INFO, "combined_pdf",
                f"Combined PDF written: {combined.name} ({len(pdfs)} pages).",
            ))

        qa.add(QARecord(
            SEV_INFO, "map_series_complete",
            f"Exported {len(result.exported)} page(s), "
            f"skipped {len(result.skipped)}.",
        ))

    finally:
        del aprx

    return result
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_map_series.py -v
```

Expected: all 15 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/map_series.py \
        tests/envmon/test_map_series.py
git commit -m "feat(envmon): map_series — map series page export with filter + PDF combine (Tool 5.6)"
```

---

### Task 2: CLI command and capabilities registration

- [ ] **Step 1: Add `generate-map-series` to `autogis/adapters/cli.py`**

Locate the block that contains `export-figures` (Tool 6) and insert after it:

```python
@envmon.command("generate-map-series")
@click.option("--aprx", "aprx_path", required=True, type=click.Path(exists=True),
              help="Path to the ArcGIS Pro project (.aprx).")
@click.option("--layout", "layout_name", required=True,
              help="Name of the layout that has a map series enabled.")
@click.option("--out-dir", required=True, type=click.Path(),
              help="Output directory.  Created if absent.")
@click.option("--format", "fmt", default="PDF",
              type=click.Choice(["PDF", "PNG"], case_sensitive=False),
              show_default=True, help="Export format.")
@click.option("--dpi", default=300, show_default=True,
              help="Export resolution in DPI.")
@click.option("--pages", default=None,
              help="Comma-separated page names to export.  Omit to export all.")
@click.option("--combine-pdf", is_flag=True, default=False,
              help="Merge all exported PDFs into a single combined PDF.")
@click.option("--list-pages", is_flag=True, default=False,
              help="Print page names in the map series and exit without exporting.")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to this CSV path.")
def generate_map_series_cmd(
    aprx_path, layout_name, out_dir, fmt, dpi, pages,
    combine_pdf, list_pages, report,
):
    """Tool 5.6: export ArcGIS Pro map series pages to PDF/PNG (ArcGIS Pro only)."""
    _guard("generate-map-series")
    from autogis.core.envmon.map_series import (
        MapSeriesConfig,
        export_map_series,
        list_map_series_pages,
    )

    if list_pages:
        page_names = list_map_series_pages(Path(aprx_path), layout_name)
        for name in page_names:
            click.echo(name)
        return

    pages_list = (
        [p.strip() for p in pages.split(",") if p.strip()]
        if pages else None
    )

    cfg = MapSeriesConfig(
        aprx_path=Path(aprx_path),
        layout_name=layout_name,
        out_dir=Path(out_dir),
        format=fmt,
        dpi=dpi,
        pages=pages_list,
        combine_pdf=combine_pdf,
    )
    result = export_map_series(cfg)
    click.echo(
        f"Exported: {len(result.exported)}  "
        f"Skipped: {len(result.skipped)}  "
        f"Out: {out_dir}"
    )
    if result.combined:
        click.echo(f"Combined PDF: {result.combined}")
    _render_qa(result.qa, report, "error")
```

- [ ] **Step 2: Register in `autogis/runtime/capabilities.py`**

Add to the `TOOLS` dict alongside the other LOCAL map/figure tools:

```python
"generate-map-series": Runtime.LOCAL,  # tool 5.6
```

- [ ] **Step 3: Add help-text test and commit**

Append to `tests/envmon/test_map_series.py`:

```python
from click.testing import CliRunner
from autogis.adapters.cli import autogis as autogis_cli


def test_generate_map_series_in_help():
    result = CliRunner().invoke(autogis_cli, ["envmon", "--help"])
    assert "generate-map-series" in result.output
```

```bash
git add autogis/adapters/cli.py \
        autogis/runtime/capabilities.py \
        tests/envmon/test_map_series.py
git commit -m "feat(cli): add generate-map-series command (Tool 5.6, LOCAL)"
```

---

## Run commands

```bash
# TDD step 1: confirm tests fail before module exists
python -m pytest tests/envmon/test_map_series.py -v

# TDD step 2: after creating map_series.py
python -m pytest tests/envmon/test_map_series.py -v

# Full suite
python -m pytest -q
```
