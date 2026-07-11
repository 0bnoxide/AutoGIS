# Report Template System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the two Markdown envmon report tools a sleek, self-contained HTML output built from a shared, drift-proof design system, closing issue #163.

**Architecture:** One canonical `report.css` is consumed by both (a) a stdlib-only Python render layer (`report_html.py`) that inlines it into self-contained HTML reports, and (b) DesignSync preview pages *generated from the same render-layer builders* (so markup can't drift). The two report tools gain an additive `--format html` path via a data/render split — one gather-data function feeds two thin renderers — so Markdown and HTML never disagree on counts. Photos reuse the existing attachment-harvester pipeline.

**Tech Stack:** Python 3.10+ stdlib (`html`, `importlib.resources`, `base64`), Click, `Pillow>=9.0` (photo path only, via the existing `autogis[report]` extra, lazy-imported), the `DesignSync` tool for the design push.

## Global Constraints

- `core/` and `adapters/` must be **arcpy-free**; `core/` must not import `adapters/`.
- Report tools' core stays **pure stdlib**; the only optional dependency is `Pillow`, **lazy-imported**, gated by the existing `report = ["Pillow>=9.0"]` extra. **No new dependency.**
- Output is **self-contained HTML** (CSS inlined, images as `data:` URIs) — no external `http(s)://` refs. Print-optimized (`@media print`). **No `weasyprint`, no `python-docx`.**
- **Escaping (binding):** only params suffixed `*_html` accept caller-supplied raw HTML; every other value is `html.escape`-d; attribute contexts use `html.escape(..., quote=True)`.
- Markdown remains the **default** output on both tools; HTML is additive; the existing XLSX photo tool is untouched.
- Thumbnail box **300×225, JPEG q80** (matches the XLSX tool).
- ADR number: **verify `ls docs/adr/ | tail` AND `gh pr list` at commit time** before finalizing `0082` (this repo has a history of ADR-number collisions).
- Python `requires-python = ">=3.10"` — `importlib.resources.files()` is available (3.9+); do not use `importlib.resources.read_text` (deprecated).

---

### Task 1: Canonical CSS asset + packaging

**Files:**
- Create: `autogis/core/common/report_assets/__init__.py`
- Create: `autogis/core/common/report_assets/report.css`
- Modify: `pyproject.toml` (add `[tool.setuptools.package-data]`)
- Test: `tests/test_report_assets.py`

**Interfaces:**
- Produces: an importable resource package `autogis.core.common.report_assets` containing `report.css`, resolvable via `importlib.resources.files("autogis.core.common.report_assets").joinpath("report.css")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_assets.py
from importlib.resources import files


def test_report_css_resource_resolves_and_nonempty():
    res = files("autogis.core.common.report_assets").joinpath("report.css")
    text = res.read_text(encoding="utf-8")
    assert ".report" in text and ".kpi" in text and "@media print" in text
    assert len(text) > 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autogis.core.common.report_assets'`

- [ ] **Step 3: Create the package marker**

```python
# autogis/core/common/report_assets/__init__.py
"""Packaged static assets for the HTML report render layer (report.css).

A real package (not a bare dir) so importlib.resources.files() can resolve it
and setuptools package-data ships the .css in a wheel/non-editable install.
"""
```

- [ ] **Step 4: Create the canonical stylesheet**

```css
/* autogis/core/common/report_assets/report.css
   Canonical report design — the single source of truth shared by the Python
   render layer (report_html.py) and the DesignSync preview bundle. Report
   canvas is always light (documents print on white). */
:root {
  --bg: #ffffff; --ink: #1a1d21; --muted: #5b636c; --line: #e3e7eb;
  --panel: #f7f8fa; --accent: #3b5bdb;
  --ok-bg: #e6f4ea; --ok-fg: #1c7c3c;
  --warn-bg: #fdf3e2; --warn-fg: #9a6700;
  --bad-bg: #fdecec; --bad-fg: #b42318;
  --info-bg: #e8effd; --info-fg: #2f4fbf;
  --neutral-bg: #eef1f4; --neutral-fg: #3a424b;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica,
          Arial, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--panel); color: var(--ink);
       font-family: var(--font); line-height: 1.5;
       -webkit-font-smoothing: antialiased; }
.report { max-width: 8.5in; margin: 24px auto; background: var(--bg);
          padding: 40px 48px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
          border-radius: 6px; }
.report-header { border-bottom: 2px solid var(--accent); padding-bottom: 16px;
                 margin-bottom: 24px; }
.report-header h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -.01em; }
.subtitle { color: var(--muted); margin: 0 0 12px; font-size: 15px; }
.meta-strip { display: flex; flex-wrap: wrap; gap: 6px 24px; font-size: 13px; }
.meta-item { display: flex; gap: 6px; }
.meta-k { color: var(--muted); } .meta-v { font-weight: 600; }
.report-section { margin: 28px 0; }
.report-section > h2 { font-size: 17px; margin: 0 0 12px;
                       border-left: 3px solid var(--accent); padding-left: 10px; }
.kpi-row { display: flex; flex-wrap: wrap; gap: 12px; }
.kpi { flex: 1 1 140px; background: var(--neutral-bg); border-radius: 6px;
       padding: 14px 16px; }
.kpi-value { font-size: 26px; font-weight: 700; line-height: 1.1; }
.kpi-label { font-size: 12px; color: var(--muted); margin-top: 2px;
             text-transform: uppercase; letter-spacing: .04em; }
table.data { border-collapse: collapse; width: 100%; font-size: 13px; }
table.data th { text-align: left; background: var(--panel); color: var(--muted);
                font-weight: 600; padding: 8px 10px; border-bottom: 2px solid var(--line); }
table.data td { padding: 8px 10px; border-bottom: 1px solid var(--line); }
table.data tr:nth-child(even) td { background: #fbfcfd; }
.badge { display: inline-block; font-size: 12px; font-weight: 600;
         padding: 2px 8px; border-radius: 999px; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: 16px;
        margin: 12px 0; }
.card-title { font-size: 15px; margin: 0 0 8px; }
.photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
              gap: 12px; }
.photo { margin: 0; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.photo img { width: 100%; height: auto; display: block; }
.photo figcaption { font-size: 12px; color: var(--muted); padding: 6px 8px; }
.report-footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid var(--line);
                 color: var(--muted); font-size: 12px; }
.tone-ok { background: var(--ok-bg); color: var(--ok-fg); }
.tone-warn { background: var(--warn-bg); color: var(--warn-fg); }
.tone-bad { background: var(--bad-bg); color: var(--bad-fg); }
.tone-info { background: var(--info-bg); color: var(--info-fg); }
.tone-neutral { background: var(--neutral-bg); color: var(--neutral-fg); }
td.tone-ok, td.tone-warn, td.tone-bad, td.tone-info { font-weight: 600; }
@media print {
  body { background: #fff; }
  .report { box-shadow: none; margin: 0; max-width: none; border-radius: 0; padding: 0; }
  .kpi { border: 1px solid var(--line); }
  table.data tr { page-break-inside: avoid; }
}
```

- [ ] **Step 5: Add package-data to pyproject.toml**

After the `[tool.setuptools.packages.find]` block (end of file), append:

```toml
[tool.setuptools.package-data]
"autogis.core.common.report_assets" = ["*.css"]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_report_assets.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add autogis/core/common/report_assets/ pyproject.toml tests/test_report_assets.py
git commit -m "feat(report): canonical report.css asset + package-data (#163)"
```

---

### Task 2: HTML render layer (`report_html.py`)

**Files:**
- Create: `autogis/core/common/report_html.py`
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `autogis.core.common.report_assets/report.css` (Task 1).
- Produces:
  - `badge(text, tone="neutral") -> str`
  - `kpi_row(items: Sequence[tuple[str, object, str]]) -> str`  # (label, value, tone)
  - `table(headers, rows, *, tone_of: Callable[[int,int], str|None] | None = None) -> str`
  - `card(title, body_html: str) -> str`
  - `section(heading, body_html: str) -> str`
  - `photo_grid(images: Sequence[tuple[str, str]]) -> str`  # (src, caption)
  - `render_document(*, title, subtitle="", meta: dict|None = None, sections: Sequence[str]=(), generated: str="") -> str`
  - `TONES: frozenset[str]` = `{"ok","warn","bad","info","neutral"}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_html.py
import autogis.core.common.report_html as rh


def test_text_context_escaping_renders_script_inert():
    out = rh.table(["A"], [["<script>alert(1)</script>"]])
    assert "<script>alert(1)" not in out
    assert "&lt;script&gt;" in out


def test_attribute_context_escaping_cannot_break_out():
    # A caption/src containing a double-quote must not escape the attribute.
    out = rh.photo_grid([('data:image/jpeg;base64,AAA" onerror="x', 'cap"tion')])
    assert 'onerror="x' not in out
    assert "&quot;" in out


def test_badge_applies_tone_class_and_falls_back_on_bad_tone():
    assert 'class="badge tone-bad"' in rh.badge("EXCEED", "bad")
    assert 'class="badge tone-neutral"' in rh.badge("x", "nonsense")


def test_kpi_row_and_table_structure():
    assert 'class="kpi-row"' in rh.kpi_row([("Wells", 5, "neutral")])
    t = rh.table(["H1", "H2"], [["a", "b"]], tone_of=lambda i, j: "bad" if j == 1 else None)
    assert "<th>H1</th>" in t and "<td>a</td>" in t and 'class="tone-bad"' in t


def test_render_document_is_self_contained():
    doc = rh.render_document(
        title="T", subtitle="S", meta={"Site": "X"},
        sections=[rh.section("Sec", "<p>body</p>")], generated="2026-07-11",
    )
    assert doc.startswith("<!doctype html>")
    assert "<style>" in doc and ".report" in doc          # CSS inlined
    assert "http://" not in doc and "https://" not in doc  # no external refs
    assert 'src="http' not in doc and 'href="http' not in doc


def test_render_document_is_deterministic():
    kw = dict(title="T", sections=[rh.section("S", "<p>x</p>")], generated="2026-07-11")
    assert rh.render_document(**kw) == rh.render_document(**kw)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_html.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autogis.core.common.report_html'`

- [ ] **Step 3: Implement the render layer**

```python
# autogis/core/common/report_html.py
"""Self-contained HTML report render layer — the code half of the shared
report design (the other half is the DesignSync preview bundle; both consume
autogis/core/common/report_assets/report.css).

Pure stdlib. Escape-safe: only *_html-suffixed params accept caller-supplied
raw HTML; every other value is html.escape-d, and attribute contexts use
quote=True so a double-quote cannot break out of an attribute.
"""
from __future__ import annotations

import html
from importlib.resources import files
from typing import Callable, Optional, Sequence

TONES = frozenset({"ok", "warn", "bad", "info", "neutral"})


def _css() -> str:
    return files("autogis.core.common.report_assets").joinpath(
        "report.css").read_text(encoding="utf-8")


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _attr(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _tone_class(tone: Optional[str]) -> str:
    t = tone or "neutral"
    if t not in TONES:
        t = "neutral"
    return f"tone-{t}"


# Public aliases — the DesignSync generator (Task 7) and report tools (Task 4)
# consume these; keep the underscored names for internal call sites.
esc = _esc
attr = _attr


def css() -> str:
    """The canonical report stylesheet text (single source of truth)."""
    return _css()


def badge(text, tone: str = "neutral") -> str:
    return f'<span class="badge {_tone_class(tone)}">{_esc(text)}</span>'


def kpi_row(items: Sequence[tuple]) -> str:
    tiles = []
    for item in items:
        label, value = item[0], item[1]
        tone = item[2] if len(item) > 2 else "neutral"
        tiles.append(
            f'<div class="kpi {_tone_class(tone)}">'
            f'<div class="kpi-value">{_esc(value)}</div>'
            f'<div class="kpi-label">{_esc(label)}</div></div>'
        )
    return f'<div class="kpi-row">{"".join(tiles)}</div>'


def table(headers: Sequence, rows: Sequence[Sequence], *,
          tone_of: Optional[Callable[[int, int], Optional[str]]] = None) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, cell in enumerate(row):
            tone = tone_of(i, j) if tone_of else None
            cls = f' class="{_tone_class(tone)}"' if tone else ""
            cells.append(f"<td{cls}>{_esc(cell)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (f'<table class="data"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def card(title, body_html: str) -> str:
    return (f'<section class="card"><h3 class="card-title">{_esc(title)}</h3>'
            f'<div class="card-body">{body_html}</div></section>')


def section(heading, body_html: str) -> str:
    return (f'<section class="report-section"><h2>{_esc(heading)}</h2>'
            f'{body_html}</section>')


def photo_grid(images: Sequence[tuple]) -> str:
    figs = []
    for src, caption in images:
        figs.append(
            f'<figure class="photo"><img src="{_attr(src)}" '
            f'alt="{_attr(caption)}"/>'
            f'<figcaption>{_esc(caption)}</figcaption></figure>'
        )
    return f'<div class="photo-grid">{"".join(figs)}</div>'


def render_document(*, title, subtitle: str = "", meta: Optional[dict] = None,
                    sections: Sequence[str] = (), generated: str = "") -> str:
    subtitle_html = f'<p class="subtitle">{_esc(subtitle)}</p>' if subtitle else ""
    meta_html = ""
    if meta:
        items = "".join(
            f'<div class="meta-item"><span class="meta-k">{_esc(k)}</span>'
            f'<span class="meta-v">{_esc(v)}</span></div>'
            for k, v in meta.items()
        )
        meta_html = f'<div class="meta-strip">{items}</div>'
    footer = "Generated by AutoGIS" + (f" · {_esc(generated)}" if generated else "")
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        f"<title>{_esc(title)}</title><style>{_css()}</style></head>"
        '<body><main class="report">'
        f'<header class="report-header"><h1>{_esc(title)}</h1>'
        f"{subtitle_html}{meta_html}</header>"
        f"{''.join(sections)}"
        f'<footer class="report-footer">{footer}</footer>'
        "</main></body></html>"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_html.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/common/report_html.py tests/test_report_html.py
git commit -m "feat(report): stdlib HTML render layer with escape-safe builders (#163)"
```

---

### Task 3: Promote the photo-thumbnail helper to public

**Files:**
- Modify: `autogis/core/envmon/well_inspection_photo_report.py:150-167` (rename `_prepared_image_bytes` → `prepare_image_bytes`, keep back-compat alias) and its call site at line ~269
- Test: `tests/envmon/test_well_inspection_photo_report.py` (add one case)

**Interfaces:**
- Produces: `prepare_image_bytes(path, box: tuple[int,int]) -> bytes | None` (public; EXIF-corrected, RGB, thumbnailed JPEG bytes; `None` if the file is missing on disk; raises `ImportError` with the Pillow hint if Pillow is absent).

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_well_inspection_photo_report.py  (add)
def test_prepare_image_bytes_is_public():
    from autogis.core.envmon import well_inspection_photo_report as m
    assert hasattr(m, "prepare_image_bytes")
    # missing file returns None without importing Pillow
    assert m.prepare_image_bytes("does_not_exist.jpg", (10, 10)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_well_inspection_photo_report.py::test_prepare_image_bytes_is_public -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'prepare_image_bytes'`

- [ ] **Step 3: Rename the function and add a back-compat alias**

In `well_inspection_photo_report.py`, change the def line:

```python
def prepare_image_bytes(path: Path, box: tuple[int, int]) -> Optional[bytes]:
    """EXIF-corrected, RGB, thumbnail-to-*box* JPEG bytes; None if the file
    is missing on disk. Pillow is lazy-imported here (the only place)."""
```

At the module bottom (after the function), add:

```python
# Back-compat: this was module-private before it was reused by the HTML report.
_prepared_image_bytes = prepare_image_bytes
```

Update the internal call site (was `data = _prepared_image_bytes(`) to `data = prepare_image_bytes(`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_well_inspection_photo_report.py -v`
Expected: PASS (all existing cases + the new one)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/well_inspection_photo_report.py tests/envmon/test_well_inspection_photo_report.py
git commit -m "refactor(report): promote prepare_image_bytes to public for HTML reuse (#163)"
```

---

### Task 4: Well-inspection HTML output + photo grid

**Files:**
- Modify: `autogis/core/envmon/well_inspection_report.py` (add HTML renderers, `fmt` + photo params on `build_well_inspection_reports`, Pillow fail-fast)
- Test: `tests/test_well_inspection_report.py` (add HTML cases)

**Interfaces:**
- Consumes: `report_html` (Task 2); `prepare_image_bytes`, `match_photos_to_wells`, `load_manifest` (Task 3 / existing).
- Produces:
  - `generate_well_report_html(well_id, well_row, inspections, *, generated_date=None, photos: Sequence[tuple[str,str]]=()) -> str`
  - `generate_site_summary_html(wells, inspections_by_well, *, site_id, generated_date=None, qa) -> str`
  - `build_well_inspection_reports(..., fmt: str = "md", manifest_path=None, harvest_dir=None)` writing `.md` (default) or `.html`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_well_inspection_report.py  (add)
from pathlib import Path
from autogis.core.common.qa import QACollector
from autogis.core.envmon.well_inspection_report import (
    build_well_inspection_reports, generate_well_report_html,
)


def _wells_csv(tmp_path):
    p = tmp_path / "wells.csv"
    p.write_text("WellID,Owner\nMW-1,ACME\n", encoding="utf-8")
    return p


def test_generate_well_report_html_contains_id_and_history():
    html = generate_well_report_html(
        "MW-1", {"WellID": "MW-1", "Owner": "ACME"},
        [{"InspectionDate": "2026-04-01", "Condition": "GOOD", "Notes": "ok"}],
    )
    assert "MW-1" in html and "2026-04-01" in html and "<table" in html


def test_build_writes_html_when_fmt_html(tmp_path):
    qa = QACollector()
    written = build_well_inspection_reports(
        _wells_csv(tmp_path), tmp_path / "out", site_id="S", fmt="html", qa=qa,
    )
    assert any(str(p).endswith("MW-1.html") for p in written)
    assert any(str(p).endswith("SiteSummary.html") for p in written)
    body = (tmp_path / "out" / "MW-1.html").read_text(encoding="utf-8")
    assert body.startswith("<!doctype html>")
    assert "http://" not in body and "https://" not in body   # self-contained


def test_photo_grid_embeds_matching_photo(tmp_path):
    # Positive path (spec §E): a real JPEG under harvest/MW-1/ with an ABSOLUTE
    # saved_path must land as an inline <img src="data:..."> in MW-1.html.
    # TRAP: match_photos_to_wells does Path(saved).relative_to(harvest_dir);
    # a RELATIVE saved_path against an absolute harvest_dir is silently dropped,
    # so the saved_path here MUST be absolute or the test passes vacuously.
    pytest = __import__("pytest")
    Image = pytest.importorskip("PIL.Image")  # Pillow-gated
    harvest = tmp_path / "harvest"
    (harvest / "MW-1").mkdir(parents=True)
    img_path = harvest / "MW-1" / "wellhead.jpg"
    Image.new("RGB", (32, 24), (120, 140, 160)).save(img_path, "JPEG")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "attachment_id,original_name,saved_path,disposition\n"
        f"1,wellhead.jpg,{img_path},downloaded\n", encoding="utf-8")
    out = tmp_path / "out"
    qa = QACollector()
    build_well_inspection_reports(
        _wells_csv(tmp_path), out, site_id="S", fmt="html",
        manifest_path=manifest, harvest_dir=harvest, qa=qa,
    )
    body = (out / "MW-1.html").read_text(encoding="utf-8")
    assert 'src="data:image/jpeg;base64,' in body
    assert "wellhead.jpg" in body  # caption


def test_photo_inputs_without_pillow_fail_fast(tmp_path, monkeypatch):
    # Simulate Pillow missing: the probe must raise BEFORE any file is written.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no pillow")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("attachment_id,saved_path,disposition\n1,harv/MW-1/a.jpg,downloaded\n",
                        encoding="utf-8")
    (tmp_path / "harv" / "MW-1").mkdir(parents=True)
    out = tmp_path / "out"
    qa = QACollector()
    import pytest
    with pytest.raises(ImportError):
        build_well_inspection_reports(
            _wells_csv(tmp_path), out, site_id="S", fmt="html",
            manifest_path=manifest, harvest_dir=tmp_path / "harv", qa=qa,
        )
    assert not out.exists() or not list(out.glob("*.html"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_well_inspection_report.py -k "html or photo or fail_fast" -v`
Expected: FAIL — `ImportError: cannot import name 'generate_well_report_html'`

- [ ] **Step 3: Add the HTML renderers**

At the top of `well_inspection_report.py`, add imports:

```python
import base64
from autogis.core.common import report_html as rh
```

Add, after `generate_well_report`:

```python
def generate_well_report_html(
    well_id: str,
    well_row: dict,
    inspections: List[dict],
    *,
    generated_date: Optional[date] = None,
    photos: "list[tuple[str, str]]" = (),
) -> str:
    """Self-contained HTML report for one well (mirror of generate_well_report).

    photos: (data-URI, caption) pairs; empty -> no photo section.
    """
    generated = (generated_date or date.today()).isoformat()
    meta = {k: v for k, v in well_row.items() if k != "WellID"}
    sections: List[str] = []
    if inspections:
        latest = inspections[0]
        cond = latest.get("Condition", "")
        tone = "ok" if cond.strip().upper() in _PASSING_CONDITIONS else "warn"
        latest_html = (
            f'<p>Date: {rh.esc(latest.get("InspectionDate", ""))} · '
            f'Condition: {rh.badge(cond or "—", tone)} · '
            f'Notes: {rh.esc(latest.get("Notes", ""))}</p>'
        )
        sections.append(rh.section("Latest Inspection", latest_html))
        hist = rh.table(
            ["Date", "Condition", "Notes"],
            [[i.get("InspectionDate", ""), i.get("Condition", ""),
              i.get("Notes", "")] for i in inspections],
        )
        sections.append(rh.section("Inspection History", hist))
    else:
        sections.append(rh.section("Inspection History",
                                   "<p><em>No inspection records on file.</em></p>"))
    if photos:
        sections.append(rh.section("Field Photos", rh.photo_grid(photos)))
    return rh.render_document(
        title=f"Well Inspection Report — {well_id}",
        meta=meta, sections=sections, generated=generated,
    )


def generate_site_summary_html(
    wells: List[dict],
    inspections_by_well: Dict[str, List[dict]],
    *,
    site_id: str,
    generated_date: Optional[date] = None,
    qa: QACollector,
) -> str:
    """HTML site summary (mirror of generate_site_summary; same QA emits)."""
    generated = (generated_date or date.today()).isoformat()
    never, attention, rows = [], [], []
    for w in wells:
        wid = w.get("WellID", "")
        history = inspections_by_well.get(wid, [])
        if not history:
            never.append(wid)
            cond, dt = "NEVER INSPECTED", ""
        else:
            cond = history[0].get("Condition", "")
            dt = history[0].get("InspectionDate", "")
            if cond.strip().upper() not in _PASSING_CONDITIONS:
                attention.append(wid)
        rows.append([wid, dt, cond])

    def tone_of(i, j):
        if j != 2:
            return None
        c = rows[i][2].strip().upper()
        if c == "NEVER INSPECTED":
            return "warn"
        return "ok" if c in _PASSING_CONDITIONS else "bad"

    kpi = rh.kpi_row([
        ("Total wells", len(wells), "neutral"),
        ("Never inspected", len(never), "warn" if never else "ok"),
        ("Needs attention", len(attention), "bad" if attention else "ok"),
    ])
    tbl = rh.table(["WellID", "Latest Inspection", "Condition"], rows, tone_of=tone_of)
    body = rh.render_document(
        title=f"Well Inspection Site Summary — {site_id}",
        sections=[rh.section("Summary", kpi), rh.section("Well Status", tbl)],
        generated=generated,
    )
    if never:
        qa.add(SEV_WARNING, "wells_never_inspected",
               f"{len(never)} well(s) have no inspection history: {', '.join(never)}")
    if attention:
        qa.add(SEV_WARNING, "wells_need_attention",
               f"{len(attention)} well(s) have a non-passing latest condition: "
               f"{', '.join(attention)}")
    qa.add(SEV_INFO, "well_inspection_summary_complete",
           f"Site summary: {len(wells)} well(s), {len(never)} never inspected, "
           f"{len(attention)} need attention")
    return body
```

- [ ] **Step 4: Extend `build_well_inspection_reports`**

Change the signature and body of `build_well_inspection_reports`. Add params
`fmt: str = "md"`, `manifest_path: Optional[Path] = None`,
`harvest_dir: Optional[Path] = None`. Insert, right after `inspections_by_well`
is built and before the write loop:

```python
    # Photo grid (HTML only): reuse the harvester pipeline. Fail fast on a
    # missing Pillow BEFORE writing any file (reports are written per-well).
    photos_by_well: Dict[str, list] = {}
    if fmt == "html" and manifest_path and harvest_dir:
        from autogis.core.envmon.index_field_attachments import load_manifest
        from autogis.core.envmon.well_inspection_photo_report import (
            match_photos_to_wells, prepare_image_bytes,
        )
        try:
            import PIL  # noqa: F401  (fail-fast capability probe)
        except ImportError as exc:
            raise ImportError('Pillow is required to embed photos. Install with: '
                              'pip install "autogis[report]"') from exc
        manifest_rows = load_manifest(Path(manifest_path))
        photo_map = match_photos_to_wells(manifest_rows, Path(harvest_dir), qa=qa)
        missing: List[str] = []
        for wid, entries in photo_map.items():
            imgs = []
            for e in entries:
                data = prepare_image_bytes(e.get("saved_path", ""), (300, 225))
                if data is None:
                    missing.append(e.get("original_name") or e.get("saved_path", ""))
                    continue
                uri = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
                imgs.append((uri, e.get("original_name") or ""))
            if imgs:
                photos_by_well[wid] = imgs
        if missing:
            # Parity with the XLSX tool's photo_files_missing WARNING.
            qa.add(SEV_WARNING, "photo_files_missing",
                   f"{len(missing)} manifest photo(s) not found on disk: "
                   f"{', '.join(missing)}")
```

Then in the per-well write loop, replace the Markdown-only write with a format
switch. Replace:

```python
        content = generate_well_report(
            wid, well_row, inspections_by_well.get(wid, []),
            generated_date=generated_date,
        )
        safe_wid = _sanitize_well_id(wid, qa=qa)
        path = output_dir / f"{safe_wid}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)
```

with:

```python
        safe_wid = _sanitize_well_id(wid, qa=qa)
        if fmt == "html":
            content = generate_well_report_html(
                wid, well_row, inspections_by_well.get(wid, []),
                generated_date=generated_date,
                photos=photos_by_well.get(wid, ()),
            )
            path = output_dir / f"{safe_wid}.html"
        else:
            content = generate_well_report(
                wid, well_row, inspections_by_well.get(wid, []),
                generated_date=generated_date,
            )
            path = output_dir / f"{safe_wid}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)
```

And replace the summary write:

```python
    summary_content = generate_site_summary(
        deduped_wells, inspections_by_well, site_id=site_id,
        generated_date=generated_date, qa=qa,
    )
    summary_path = output_dir / "SiteSummary.md"
```

with:

```python
    if fmt == "html":
        summary_content = generate_site_summary_html(
            deduped_wells, inspections_by_well, site_id=site_id,
            generated_date=generated_date, qa=qa,
        )
        summary_path = output_dir / "SiteSummary.html"
    else:
        summary_content = generate_site_summary(
            deduped_wells, inspections_by_well, site_id=site_id,
            generated_date=generated_date, qa=qa,
        )
        summary_path = output_dir / "SiteSummary.md"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_well_inspection_report.py -v`
Expected: PASS (existing MD cases unchanged + new HTML/photo/fail-fast cases)

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/well_inspection_report.py tests/test_well_inspection_report.py
git commit -m "feat(report): well-inspection HTML output + photo grid via harvester (#163)"
```

---

### Task 5: Monitoring-event HTML output (data/render split)

**Files:**
- Modify: `autogis/core/envmon/generate_event_report.py` (extract `_gather_event_data`, keep `generate_event_report` MD byte-stable, add `generate_event_report_html`)
- Test: `tests/test_generate_event_report.py` (add HTML + parity cases)

**Interfaces:**
- Consumes: `report_html` (Task 2); `canonical_result_rows` (existing).
- Produces:
  - `_gather_event_data(site_id, event_id, *, results_csv=None, comparison_csv=None, history_csv=None, gaps_csv=None, rpd_qa_csv=None, generated_date=None, qa) -> dict`
  - `generate_event_report_html(site_id, event_id, *, <same kwargs>, qa) -> str`
  - `generate_event_report(...)` unchanged signature/output (now delegates gather→MD).

**Guarding invariant:** `generate_event_report` MD output must be byte-identical
to today's. The existing tests in `tests/test_generate_event_report.py` are the
guard — they must stay green untouched. The gather refactor moves computation,
not formatting.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_generate_event_report.py  (add)
from autogis.core.common.qa import QACollector
from autogis.core.envmon.generate_event_report import (
    generate_event_report, generate_event_report_html, _gather_event_data,
)


def _results_csv(tmp_path):
    p = tmp_path / "results.csv"
    p.write_text(
        "LocationID,AnalyteCanonicalName,DisplayText,ScreeningLevel,"
        "ExceedsScreeningLevel,DisplayColorClass\n"
        "MW-1,Benzene,5.5,5.0,1,EXCEED\n"
        "MW-2,Benzene,<1.0,5.0,0,OK\n",
        encoding="utf-8")
    return p


def test_event_html_has_kpi_and_exceedance_badge(tmp_path):
    qa = QACollector()
    html = generate_event_report_html(
        "S", "2026Q2", results_csv=_results_csv(tmp_path), qa=qa)
    assert html.startswith("<!doctype html>")
    assert 'class="kpi-row"' in html
    assert "EXCEED" in html and "tone-bad" in html


def test_md_and_html_agree_on_exceedance_count(tmp_path):
    qa1, qa2 = QACollector(), QACollector()
    md = generate_event_report("S", "2026Q2", results_csv=_results_csv(tmp_path), qa=qa1)
    data = _gather_event_data("S", "2026Q2", results_csv=_results_csv(tmp_path), qa=qa2)
    # exec-summary row order: [total, exceedances, gaps, rpd]
    assert data["summary_rows"][1][1] == 1
    assert "Screening level exceedances | 1" in md.replace("  ", " ")


def test_badge_tone_falls_back_when_colorclass_missing(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("LocationID,AnalyteCanonicalName,DisplayText,ScreeningLevel,"
                 "ExceedsScreeningLevel\nMW-9,Lead,20,15,1\n", encoding="utf-8")
    qa = QACollector()
    html = generate_event_report_html("S", "E", results_csv=p, qa=qa)
    assert "tone-bad" in html  # fell back to ExceedsScreeningLevel=1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate_event_report.py -k "html or agree or fallback" -v`
Expected: FAIL — `ImportError: cannot import name 'generate_event_report_html'`

- [ ] **Step 3: Extract the gather function**

Add near the top of `generate_event_report.py`:

```python
from autogis.core.common import report_html as rh

_EXCEED_TRUE = ("1", "True", "true", "YES")


def _exceeds(row: dict) -> bool:
    return str(row.get("ExceedsScreeningLevel", "")).strip() in _EXCEED_TRUE


def _color_tone(row: dict) -> str:
    """DisplayColorClass EXCEED/OK -> bad/ok; UNKNOWN/absent -> fall back to
    ExceedsScreeningLevel (mirrors the exec-summary count logic)."""
    cc = str(row.get("DisplayColorClass", "")).strip().upper()
    if cc == "EXCEED":
        return "bad"
    if cc == "OK":
        return "ok"
    return "bad" if _exceeds(row) else "ok"
```

Add the gather function (it performs ALL data policy — the ADR-0079 canonical
read stays here and nowhere else):

```python
def _gather_event_data(site_id, event_id, *, results_csv=None,
                       comparison_csv=None, history_csv=None, gaps_csv=None,
                       rpd_qa_csv=None, generated_date=None, qa) -> dict:
    generated = (generated_date or date.today()).isoformat()
    results = canonical_result_rows(_load_csv(results_csv), qa)
    comparisons = _load_csv(comparison_csv)
    history = _load_csv(history_csv)
    gaps = _load_csv(gaps_csv)
    rpd = _load_csv(rpd_qa_csv)

    n_results = len(results)
    exceed_results = [r for r in results if _exceeds(r)]
    n_exceedances = len(exceed_results)
    n_gaps = len(gaps)
    n_rpd_errors = sum(1 for r in rpd
                       if str(r.get("severity", "")).upper() == "ERROR")

    summary_rows = [
        ["Total analytical results", n_results],
        ["Screening level exceedances", n_exceedances],
        ["Data gaps identified", n_gaps],
        ["RPD QA errors", n_rpd_errors],
    ]

    trend_rows = None
    if comparisons:
        counts: dict = {}
        for r in comparisons:
            t = str(r.get("TrendLabel", r.get("TrendVsPrevious", "UNKNOWN"))).upper()
            counts[t] = counts.get(t, 0) + 1
        trend_rows = [[t, c] for t, c in sorted(counts.items())]

    history_rows = None
    if history:
        exceed_hist = [h for h in history
                       if str(h.get("LatestExceedance", "")).strip() in ("1", "True", "true")]
        shown = (exceed_hist or history)[:10]
        history_rows = [[h.get("LocationID", ""), h.get("AnalyteCanonicalName", ""),
                         h.get("NTotal", ""), h.get("TrendVsPrevious", ""),
                         h.get("LatestResult", "")] for h in shown]

    gap_rows = [[g.get("LocationID", g.get("location_id", "")),
                 g.get("AnalyteName", g.get("analyte", "")),
                 g.get("Status", g.get("status", "")),
                 g.get("Detail", g.get("detail", ""))] for g in gaps[:20]]
    gaps_overflow = max(0, len(gaps) - 20)

    rpd_error_rows = None
    if n_rpd_errors:
        errs = [r for r in rpd if str(r.get("severity", "")).upper() == "ERROR"][:10]
        rpd_error_rows = [[r.get("location_id", r.get("LocationID", "")),
                           r.get("analyte", r.get("AnalyteName", "")),
                           r.get("message", r.get("Message", ""))] for r in errs]

    # HTML-only detail (MD output is intentionally unchanged): exceedance list
    # with per-row color tone. Cap mirrors the other detail sections.
    exceedance_rows = [[r.get("LocationID", ""), r.get("AnalyteCanonicalName", ""),
                        r.get("DisplayText", r.get("ResultRawText", "")),
                        r.get("ScreeningLevel", ""), _color_tone(r)]
                       for r in exceed_results[:20]]

    return {
        "site_id": site_id, "event_id": event_id, "generated": generated,
        "n_results": n_results, "n_exceedances": n_exceedances,
        "n_gaps": n_gaps, "n_rpd_errors": n_rpd_errors, "rpd_total": len(rpd),
        "summary_rows": summary_rows, "trend_rows": trend_rows,
        "history_rows": history_rows, "gap_rows": gap_rows,
        "gaps_overflow": gaps_overflow, "rpd_error_rows": rpd_error_rows,
        "exceedance_rows": exceedance_rows,
    }
```

- [ ] **Step 4: Rewrite `generate_event_report` to render MD from gather**

Replace the body of `generate_event_report` (keep its signature and docstring)
so it calls `_gather_event_data` then formats the SAME Markdown as before:

```python
    d = _gather_event_data(
        site_id, event_id, results_csv=results_csv, comparison_csv=comparison_csv,
        history_csv=history_csv, gaps_csv=gaps_csv, rpd_qa_csv=rpd_qa_csv,
        generated_date=generated_date, qa=qa,
    )
    lines = [
        f"# Monitoring Event Report — {site_id} / {event_id}", "",
        f"**Generated:** {d['generated']}  ", f"**Site:** {site_id}  ",
        f"**Event:** {event_id}  ", "",
        "## Executive Summary", "",
        _md_table(["Metric", "Value"], d["summary_rows"]), "",
    ]
    if d["trend_rows"] is not None:
        lines += ["## Trend vs Previous Event", "",
                  _md_table(["Trend", "Count"], d["trend_rows"]), ""]
    if d["history_rows"] is not None:
        lines += ["## History Summary (Top 10)", "",
                  _md_table(["Location", "Analyte", "N Total", "Trend", "Latest Result"],
                            d["history_rows"]), ""]
    if d["gap_rows"]:
        lines += ["## Data Gaps", "",
                  _md_table(["Location", "Analyte", "Status", "Detail"], d["gap_rows"])]
        if d["gaps_overflow"]:
            lines.append(f"*... and {d['gaps_overflow']} more gap(s) in the full CSV.*")
        lines.append("")
    if d["rpd_total"]:
        lines += ["## Duplicate RPD QA", "",
                  f"{d['rpd_total']} RPD QA record(s) — {d['n_rpd_errors']} ERROR(s).", ""]
        if d["rpd_error_rows"] is not None:
            lines += [_md_table(["Location", "Analyte", "Message"], d["rpd_error_rows"]), ""]
    lines += ["---", "*Report generated by AutoGIS `envmon generate-event-report`.*", ""]
    content = "\n".join(lines)
    qa.add(SEV_INFO, "generate_event_report_complete",
           f"generate_event_report: {site_id}/{event_id}, {len(lines)} lines, "
           f"{d['n_results']} results, {d['n_exceedances']} exceedances")
    return content
```

> Note: verify against the pre-refactor output — the existing tests in
> `tests/test_generate_event_report.py` must pass unchanged. If any assertion
> differs, adjust the MD formatting above to match the original exactly (this is
> a pure refactor of the MD path).

- [ ] **Step 5: Add the HTML renderer**

```python
def generate_event_report_html(site_id, event_id, *, results_csv=None,
                               comparison_csv=None, history_csv=None,
                               gaps_csv=None, rpd_qa_csv=None,
                               generated_date=None, qa) -> str:
    """Self-contained HTML monitoring event report (mirror of the MD tool)."""
    d = _gather_event_data(
        site_id, event_id, results_csv=results_csv, comparison_csv=comparison_csv,
        history_csv=history_csv, gaps_csv=gaps_csv, rpd_qa_csv=rpd_qa_csv,
        generated_date=generated_date, qa=qa,
    )
    kpi = rh.kpi_row([
        ("Results", d["n_results"], "neutral"),
        ("Exceedances", d["n_exceedances"], "bad" if d["n_exceedances"] else "ok"),
        ("Data gaps", d["n_gaps"], "warn" if d["n_gaps"] else "ok"),
        ("RPD errors", d["n_rpd_errors"], "bad" if d["n_rpd_errors"] else "ok"),
    ])
    sections = [rh.section("Executive Summary", kpi)]
    if d["exceedance_rows"]:
        body = rh.table(
            ["Location", "Analyte", "Result", "Screening Level", "Status"],
            [[r[0], r[1], r[2], r[3], rh.badge("EXCEED", r[4])] for r in d["exceedance_rows"]],
        )
        # badge() output is pre-escaped safe HTML; table() escapes it as text,
        # so render the status column via a tone_of highlight instead:
        rows = [[r[0], r[1], r[2], r[3], "EXCEED"] for r in d["exceedance_rows"]]
        tones = [r[4] for r in d["exceedance_rows"]]
        body = rh.table(
            ["Location", "Analyte", "Result", "Screening Level", "Status"], rows,
            tone_of=lambda i, j: tones[i] if j == 4 else None,
        )
        sections.append(rh.section("Screening Exceedances", body))
    if d["trend_rows"] is not None:
        sections.append(rh.section("Trend vs Previous Event",
                                   rh.table(["Trend", "Count"], d["trend_rows"])))
    if d["history_rows"] is not None:
        sections.append(rh.section("History Summary (Top 10)", rh.table(
            ["Location", "Analyte", "N Total", "Trend", "Latest Result"], d["history_rows"])))
    if d["gap_rows"]:
        gaps_tbl = rh.table(["Location", "Analyte", "Status", "Detail"], d["gap_rows"])
        extra = (f'<p><em>… and {d["gaps_overflow"]} more gap(s) in the full CSV.</em></p>'
                 if d["gaps_overflow"] else "")
        sections.append(rh.section("Data Gaps", gaps_tbl + extra))
    if d["rpd_total"]:
        rpd_body = f'<p>{d["rpd_total"]} RPD QA record(s) — {d["n_rpd_errors"]} ERROR(s).</p>'
        if d["rpd_error_rows"] is not None:
            rpd_body += rh.table(["Location", "Analyte", "Message"], d["rpd_error_rows"])
        sections.append(rh.section("Duplicate RPD QA", rpd_body))
    return rh.render_document(
        title=f"Monitoring Event Report — {site_id} / {event_id}",
        meta={"Site": site_id, "Event": event_id},
        sections=sections, generated=d["generated"],
    )
```

> Remove the dead first `body = rh.table(...)` assignment shown above during
> implementation — the `tone_of` version is the one to keep. (Kept in the plan
> to show why: `table()` escapes cell text, so a `badge()` string inside a cell
> would render as visible markup; color the cell via `tone_of` instead.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate_event_report.py -v`
Expected: PASS (existing MD cases unchanged + new HTML/parity/fallback cases)

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/generate_event_report.py tests/test_generate_event_report.py
git commit -m "feat(report): monitoring-event HTML via data/render split (#163)"
```

---

### Task 6: CLI `--format html` wiring

**Files:**
- Modify: `autogis/adapters/cli.py:1267-1336` (both commands)
- Test: `tests/test_cli_report_html.py`

**Interfaces:**
- Consumes: `generate_event_report_html` (Task 5), `build_well_inspection_reports(..., fmt=...)` (Task 4).
- Produces: `generate-event-report --format {md,html}`; `well-inspection-report --format {md,html} [--manifest ... --harvest-dir ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_report_html.py
from pathlib import Path
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_event_report_format_html(tmp_path):
    r = tmp_path / "results.csv"
    r.write_text("LocationID,AnalyteCanonicalName,DisplayText,ScreeningLevel,"
                 "ExceedsScreeningLevel,DisplayColorClass\nMW-1,Benzene,5.5,5,1,EXCEED\n",
                 encoding="utf-8")
    out = tmp_path / "report.html"
    res = CliRunner().invoke(autogis, [
        "envmon", "generate-event-report", "--site", "S", "--event", "E",
        "--results-csv", str(r), "--output", str(out), "--format", "html",
    ])
    assert res.exit_code == 0, res.output
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_well_inspection_format_html(tmp_path):
    w = tmp_path / "wells.csv"
    w.write_text("WellID,Owner\nMW-1,ACME\n", encoding="utf-8")
    out = tmp_path / "out"
    res = CliRunner().invoke(autogis, [
        "envmon", "well-inspection-report", "--wells-csv", str(w),
        "--site", "S", "--output-dir", str(out), "--format", "html",
    ])
    assert res.exit_code == 0, res.output
    assert (out / "MW-1.html").exists() and (out / "SiteSummary.html").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_report_html.py -v`
Expected: FAIL — `no such option: --format`

- [ ] **Step 3: Wire `generate-event-report`**

In `cli.py`, change the `--output` help text and add a `--format` option to the
`generate-event-report` command (after `--rpd-qa-csv`, before `--report`):

```python
@click.option("--output", required=True, type=click.Path(),
              help="Output file path (.md or .html per --format).")
@click.option("--format", "fmt", type=click.Choice(["md", "html"]),
              default="md", show_default=True, help="Output format.")
```

Add `fmt` to the function params and branch the content:

```python
def generate_event_report_cmd(
    site_id, event_id, output, fmt,
    results_csv, comparison_csv, history_csv, gaps_csv, rpd_qa_csv,
    report, fail_on,
):
    """Assemble a monitoring event report (Markdown or HTML) from CSV tool outputs."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.generate_event_report import (
        generate_event_report, generate_event_report_html,
    )
    qa = QACollector()
    render = generate_event_report_html if fmt == "html" else generate_event_report
    content = render(
        site_id, event_id,
        results_csv=Path(results_csv) if results_csv else None,
        comparison_csv=Path(comparison_csv) if comparison_csv else None,
        history_csv=Path(history_csv) if history_csv else None,
        gaps_csv=Path(gaps_csv) if gaps_csv else None,
        rpd_qa_csv=Path(rpd_qa_csv) if rpd_qa_csv else None,
        qa=qa,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    click.echo(f"Written: {out}")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Wire `well-inspection-report`**

Add options to the `well-inspection-report` command (after `--maintenance-log-csv`,
before `@qa_report_options`):

```python
@click.option("--format", "fmt", type=click.Choice(["md", "html"]),
              default="md", show_default=True,
              help="Output format for each per-well file + the site summary.")
@click.option("--manifest", "manifest_path", default=None, type=click.Path(),
              help="Attachment harvester manifest (.csv/.json); HTML only, enables photos.")
@click.option("--harvest-dir", default=None, type=click.Path(),
              help="Harvest output dir (photo saved_path root); HTML only, enables photos.")
```

Update the function to thread them through:

```python
def well_inspection_report_cmd(wells_csv, site_id, output_dir,
                               maintenance_log_csv, fmt, manifest_path,
                               harvest_dir, report, fail_on):
    """Generate well inspection reports + a site summary (Markdown or HTML)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.well_inspection_report import build_well_inspection_reports

    # Guard against silently-ignored photo inputs (photos need both, HTML only).
    if (manifest_path or harvest_dir) and not (manifest_path and harvest_dir):
        raise click.UsageError("--manifest and --harvest-dir must be given together.")
    if (manifest_path or harvest_dir) and fmt != "html":
        raise click.UsageError("--manifest/--harvest-dir require --format html.")

    qa = QACollector()
    written = build_well_inspection_reports(
        Path(wells_csv), Path(output_dir),
        site_id=site_id,
        maintenance_log_csv=Path(maintenance_log_csv) if maintenance_log_csv else None,
        fmt=fmt,
        manifest_path=Path(manifest_path) if manifest_path else None,
        harvest_dir=Path(harvest_dir) if harvest_dir else None,
        qa=qa,
    )
    click.echo(f"Written {len(written)} {fmt.upper()} file(s) to {output_dir}")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli_report_html.py tests/test_cli_generate_event_report.py -v`
Expected: PASS (new format cases + existing event-report CLI cases unchanged)

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/test_cli_report_html.py
git commit -m "feat(report): --format html on event + well-inspection CLIs (#163)"
```

---

### Task 7: DesignSync preview bundle (generated from the render layer)

**Files:**
- Create: `docs/design/report-templates/build_bundle.py` (generator)
- Create (generated, committed): `docs/design/report-templates/*.html`
- Test: `tests/test_report_design_bundle.py`

**Interfaces:**
- Consumes: `report_html` builders (Task 2).
- Produces: preview HTML pages, each with a first-line `<!-- @dsCard group="…" -->`
  marker, generated by importing the builders (so preview markup == report markup).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_design_bundle.py
import importlib.util
from pathlib import Path

# Anchor to the repo, not the pytest cwd.
BUNDLE = Path(__file__).resolve().parents[1] / "docs" / "design" / "report-templates"


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_bundle", BUNDLE / "build_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bundle_generates_self_contained_previews(tmp_path):
    mod = _load_builder()
    written = mod.build(tmp_path)
    assert written, "generator produced no files"
    for p in written:
        text = Path(p).read_text(encoding="utf-8")
        assert text.lstrip().startswith("<!-- @dsCard")
        assert "http://" not in text and "https://" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_design_bundle.py -v`
Expected: FAIL — generator file does not exist.

- [ ] **Step 3: Write the generator**

```python
# docs/design/report-templates/build_bundle.py
"""Generate the DesignSync preview bundle FROM the render-layer builders, so the
claude.ai/design visual spec cannot drift from the markup the tools emit.

Run:  python docs/design/report-templates/build_bundle.py
Then push with the DesignSync tool (see this file's sibling README / the plan).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from autogis.core.common import report_html as rh  # noqa: E402


def _preview(group: str, title: str, body_html: str) -> str:
    css = rh.css()
    return (f'<!-- @dsCard group="{group}" -->\n'
            "<!doctype html>\n"
            f'<html lang="en"><head><meta charset="utf-8"/><title>{title}</title>'
            f'<style>{css}</style></head><body><main class="report" '
            'style="margin:12px auto">'
            f"{body_html}</main></body></html>\n")


def build(out_dir) -> list:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pages = {
        "kpi_row.html": _preview("Components", "KPI row", rh.kpi_row([
            ("Total wells", 42, "neutral"), ("Never inspected", 3, "warn"),
            ("Needs attention", 1, "bad")])),
        "data_table.html": _preview("Components", "Data table", rh.table(
            ["Location", "Analyte", "Result", "Status"],
            [["MW-1", "Benzene", "5.5", "EXCEED"], ["MW-2", "Benzene", "<1.0", "OK"]],
            tone_of=lambda i, j: ("bad" if i == 0 else "ok") if j == 3 else None)),
        "badges.html": _preview("Components", "Status badges",
            " ".join(rh.badge(t.upper(), t) for t in
                     ["ok", "warn", "bad", "info", "neutral"])),
        "photo_grid.html": _preview("Components", "Photo grid", rh.photo_grid([
            # 1x1 transparent PNG data URI — self-contained placeholder.
            ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1"
             "HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
             "MW-1 — wellhead")])),
        "report_shell.html": (
            '<!-- @dsCard group="Shell" -->\n' + rh.render_document(
                title="Well Inspection Report — MW-1",
                meta={"Owner": "ACME", "Site": "Demo"},
                sections=[rh.section("Inspection History", rh.table(
                    ["Date", "Condition", "Notes"],
                    [["2026-04-01", "GOOD", "clear"]]))],
                generated="2026-07-11")),
    }
    written = []
    for name, html in pages.items():
        p = out / name
        p.write_text(html, encoding="utf-8")
        written.append(str(p))
    return written


if __name__ == "__main__":
    for p in build(Path(__file__).resolve().parent):
        print("wrote", p)
```

- [ ] **Step 4: Generate the committed previews**

Run: `python docs/design/report-templates/build_bundle.py`
Expected: prints `wrote docs/design/report-templates/<name>.html` for each page.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_report_design_bundle.py -v`
Expected: PASS

- [ ] **Step 6: Push to DesignSync (manual tool step — during execution, not pytest)**

Using the `DesignSync` tool:
1. `create_project` name `"AutoGIS Report Templates"` → capture `projectId` (surfaces a permission prompt; no design-system project exists yet).
2. `finalize_plan` with `writes: ["*.html"]`, `localDir: "docs/design/report-templates"` → capture `planId`.
3. `write_files` with each preview's `localPath` (e.g. `kpi_row.html`) and `path` (same) under the `planId`.
Record the resulting project URL in the PR description.

- [ ] **Step 7: Commit**

```bash
git add docs/design/report-templates/ tests/test_report_design_bundle.py
git commit -m "feat(report): DesignSync preview bundle generated from render layer (#163)"
```

---

### Task 8: ADR-0082, README refresh, full-suite gate

**Files:**
- Create: `docs/adr/0082-report-template-system.md` (verify the number first)
- Modify: `README.md` (test count / tool notes if the README tracks them)
- Test: full suite

- [ ] **Step 1: Verify the ADR number is still free**

Run: `ls docs/adr/ | grep -E '^[0-9]{4}-' | sort | tail -3 && gh pr list --state open --json files --jq '.[].files[].path' | grep -i 'docs/adr/' || echo "no open-PR ADRs"`
Expected: highest is `0081-…`; if a `0082-…` appears in any open PR, use the next free number and update every reference in this task.

- [ ] **Step 2: Write the ADR**

```markdown
# ADR-0082: Report template system — self-contained HTML + shared DesignSync design

**Status:** Accepted
**Date:** 2026-07-11
**Closes:** #163

## Context
Two envmon report tools (`well-inspection-report`, `generate-event-report`)
emitted plain Markdown; a third (`generate-inspection-report`, ADR-0046) embedded
photos only in XLSX. No tool produced a styled report, and #163 asked for a
deliberate, documented templating decision rather than per-tool improvisation.

## Decision
- **Output: self-contained HTML** — CSS inlined, images as base64 `data:` URIs,
  print-optimized (`@media print`) so PDF is a browser Ctrl-P. No `weasyprint`.
- **"Multi-format" means multi report-TYPE**, one output format (HTML) per run,
  additive to the default Markdown. **DOCX and any PDF-rendering library are
  explicitly deferred** (no clean high-fidelity path; separate future work).
- **One canonical `report.css`** (`autogis/core/common/report_assets/`) is the
  single source of truth, consumed by a stdlib-only Python render layer
  (`report_html.py`) AND by DesignSync preview pages **generated from the same
  builders** — markup cannot drift from the design.
- **Data/render split:** each tool has one gather-data function feeding two thin
  renderers (MD, HTML), so counts (incl. the ADR-0079 canonical exceedance dedup)
  are computed once and never diverge.
- **Photos reuse the existing pipeline** (harvester manifest → `match_photos_to_wells`
  → `prepare_image_bytes`) and the existing `autogis[report]` (Pillow) extra,
  lazy-imported. **No new dependency.**

## Consequences
- Reports are archivable/emailable single files that print cleanly.
- The claude.ai/design "AutoGIS Report Templates" project is the reviewable
  visual spec; regenerate + re-push the bundle when the design changes.
- Word output, if ever needed, is a deliberate future ADR — not a silent gap.
```

- [ ] **Step 3: Refresh README counts (if tracked)**

Run: `python -m pytest -q 2>&1 | tail -3` to get the new total, then update any
test-count line in `README.md` that references it. If the README does not track a
count, skip this step (no placeholder edit).

- [ ] **Step 4: Full-suite gate**

Run: `python -m pytest -q`
Expected: all pass (baseline + new tests). Investigate any failure before proceeding.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0082-report-template-system.md README.md
git commit -m "docs(adr): ADR-0082 report template system; closes #163"
```

---

## Post-plan review gate

After Task 8, before opening the PR:
- Cold `pr-reviewer` subagent over the full branch diff (arcpy-free invariant, canonical config, ADR consistency, coverage, correctness) + `envmon-spec-checker`.
- Address findings, then `gh pr create --draft` with a body linking the DesignSync project URL and `Closes #163`.

## Self-review (author check against the spec)

- **Spec coverage:** §A→Task 7; §B→Tasks 1,2; §C→Tasks 3,4,5,6; §D→Task 8; §E→tests in Tasks 1,2,4,5,7. ✓
- **Escaping (both contexts):** Task 2 Steps 1 (tests) + 3 (`_esc`/`_attr`). ✓
- **Package-data / resource resolution:** Task 1. ✓
- **Data/render split + MD byte-stability:** Task 5 (guarded by existing tests staying green). ✓
- **DisplayColorClass UNKNOWN/absent fallback:** Task 5 `_color_tone` + test. ✓
- **Pillow fail-fast before writes / public helper:** Tasks 3, 4. ✓
- **Type consistency:** `fmt` (str "md"/"html"), `photos: list[(str,str)]`, `tone_of(i,j)->str|None`, `_gather_event_data(...)->dict` used identically across Tasks 4–6. ✓
- **No new dependency; arcpy-free:** render layer stdlib; Pillow lazy via existing extra. ✓

## Plan review incorporated (Fable, 2026-07-11, medium)

Verdict EXECUTE-WITH-FIXES; MD refactor confirmed **byte-identical** (existing
`tests/test_generate_event_report.py` stays green — verified section-by-section).
Fixes folded in:
- **B1 (blocking):** added `test_photo_grid_embeds_matching_photo` (Task 4) — a
  Pillow-gated positive path with an **absolute** `saved_path` (a relative one is
  silently dropped by `match_photos_to_wells`' `relative_to`, so a naïve test
  would pass vacuously).
- Exported public `esc()`/`css()` from `report_html` (no cross-module private use
  in Tasks 4/7).
- Photo `photo_files_missing` QA WARNING for parity with the XLSX tool (Task 4).
- CLI `UsageError` when `--manifest`/`--harvest-dir` are given apart or without
  `--format html` (Task 6).
- Anchored the Task 7 bundle test path to the repo, not the pytest cwd.
- Tightened the self-containment assertion in the well-report HTML test.

Deferred (non-blocking, optional at execution): assert committed previews equal a
fresh regen (Task 7); filter the photo pre-pass to deduped well ids (perf only).
