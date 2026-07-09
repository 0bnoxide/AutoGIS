# DraftLithologyFromScan Design

**Date:** 2026-07-08
**Status:** Approved
**Tool:** DraftLithologyFromScan (new — extends the 8.0 boring-log intake family; not a
pre-existing roadmap entry, no roadmap tool number assigned)
**Priority:** exploratory — closes a real upstream gap in the boring-log intake chain,
but ships DRAFT-only until validated against a real scanned sample.

---

## Problem

`import_boring_logs.py` (Tool 8.0b/8.0c family) ingests boring-log data only once it is
already digitized into `boring_locations.csv`, `lithology.csv`, and `samples.csv`
matching the `core/common/schema/boring.py` dataclasses. In practice, geotechnical
boring logs arrive as scanned/PDF driller logs — a tabular lithology log (depth
intervals, USCS symbol, description, moisture, etc.), sometimes handwritten — and
someone transcribes them into those CSVs by hand before the existing pipeline ever
runs. There is no tool covering that transcription step.

Two Hugging Face models cover this well: `microsoft/table-transformer-detection` +
`-structure-recognition` (MIT, table layout/structure recovery) and
`microsoft/trocr-base-handwritten` (MIT, handwritten/printed cell OCR).

**Explicitly out of scope / not conflated with:** the phase-gated §11 AI-assisted tools
group (`AIDraftParserProfile`, `AIExplainQAReport`, `AIDraftFigureSpec`,
`AIMapReviewChecklist` — deferred pending LLM-seam design). This tool is document
table-structure/OCR extraction, not an LLM-driven judgment tool, and does not reopen
that gate.

---

## Approach

**Chosen: Table-Transformer (detection + structure recognition) → per-cell TrOCR →
header-alias column mapping → draft CSV + QA report.** Real scanned boring logs are
skewed, noisy photocopies, sometimes handwritten — exactly the case where ML-based
table-structure recognition earns its keep over simpler heuristics.

**Rejected: single end-to-end vision-language model reading the whole page into
structured JSON.** Simpler pipeline, but no per-cell confidence to drive QA flags, no
strong MIT-licensed zero-shot model of this kind found on the Hub, and it drifts toward
the deferred §11 LLM-seam territory. Not pursued.

**Rejected (for now): pdfplumber/camelot for digital-text PDFs + Tesseract/ruled-line
heuristics for scans, with no new ML dependency.** The leanest option and the most
YAGNI-aligned on dependency weight, but heuristic line-detection is fragile against the
scan noise, skew, and handwriting this tool specifically needs to handle. Worth
revisiting as a cheap first cut once a real sample exists, but not the primary path.

**Scope decision — lithology table only.** Boring logs also carry a header block
(BoringID, coordinates, driller, dates → `BoringLocation`) and sometimes a separate
sample/blow-count table (→ `BoringSample`). Table-Transformer targets tabular
structures, not header key-value fields, and there is no real sample document yet to
validate a header-extraction or samples-table approach against. `boring_locations.csv`
and `samples.csv` remain hand-entered; only `lithology.csv` is drafted by this tool.

**Template assumption.** Column *order* is not hard-coded (no real sample exists to fix
it against). Instead, the detected header row is OCR'd and fuzzy-matched against a
small static alias dictionary (e.g. `"uscs"`/`"symbol"`/`"class"` → `uscs`,
`"description"`/`"soil description"` → `description`) to map whichever columns the
scanned template actually has onto `LithologyInterval` fields. This assumes one
consistent template (per the target use case) but not a fixed physical layout.

**DRAFT status.** No real scanned sample has been used to validate this design.
Following the same convention as `screening_levels.yaml` and the H281 parser profile,
the module and CLI help carry a DRAFT banner: output is advisory only until verified
against a real document, and this should not be treated as production-ready until that
verification happens.

---

## Architecture

```
autogis/
  core/envmon/
    draft_lithology_from_scan.py   ← NEW, arcpy-free
  adapters/
    cli.py                         ← add draft-lithology-from-scan command (headless)
pyproject.toml                     ← add `ocr` optional extra
tests/envmon/
  test_draft_lithology_from_scan.py  ← NEW
```

No new schema — reuses `LithologyInterval` from `core/common/schema/boring.py` and the
exact CSV header format `parse_lithology_csv()` already expects
(`TopDepth_ft`, `BottomDepth_ft`, `USCS`, `PrimaryMaterial`, `Color`, `Moisture`,
`Description`, `BoringID`).

---

## Public API (`draft_lithology_from_scan.py`)

```python
@dataclass
class TableRegion:
    bbox: tuple[float, float, float, float]
    confidence: float

@dataclass
class TableGrid:
    header_row: list[str]
    rows: list[list["CellResult"]]

@dataclass
class CellResult:
    text: str
    confidence: float          # avg TrOCR token probability

@dataclass
class DraftResult:
    rows: list[LithologyInterval]
    qa: QACollector

def rasterize_pdf(path: Path, dpi: int = 200) -> list["PIL.Image.Image"]: ...

def extract_table_regions(image) -> list[TableRegion]:
    """table-transformer-detection."""

def recognize_structure(image, region: TableRegion) -> TableGrid:
    """table-transformer-structure-recognition; identifies the header row."""

def ocr_cells(grid: TableGrid, *, handwritten: bool = False) -> TableGrid:
    """Crop + TrOCR each cell, filling in CellResult.text/confidence."""

HEADER_ALIASES: dict[str, list[str]]  # field name -> known header text variants

def map_columns(header_row: list[str]) -> dict[int, str]:
    """Fuzzy-match header cells to LithologyInterval field names."""

def draft_lithology(
    scan_path: Path, *, handwritten: bool = False,
) -> DraftResult:
    """Full pipeline: rasterize -> detect -> recognize -> OCR -> map -> rows + QA."""

def write_draft_csv(rows: list[LithologyInterval], out_path: Path) -> Path: ...
```

---

## Confidence → QA Severity Mapping

| Condition | Severity | Message |
|---|---|---|
| No table detected on any page | `SEV_ERROR` | "no lithology table detected; nothing drafted" |
| Row's average cell confidence < 0.6 | `SEV_WARNING` | "verify against scan" |
| Row's average cell confidence 0.6–0.85 | `SEV_INFO` | "low-moderate confidence, spot-check" |
| Row's average cell confidence ≥ 0.85 | (no flag) | — |

All severities here are advisory — the CLI command does not call `qa.has_blocking()`
to gate anything, since the entire output is a human-reviewed draft, not an
authoritative import. This mirrors `_render_qa`'s existing report-then-continue
behavior, just without the blocking gate that `import-boring-logs` uses.

---

## CLI Command

```
autogis envmon draft-lithology-from-scan SCAN_PATH --out-dir OUT_DIR [--handwritten] [--report <qa.md>]
```

Headless — no `_guard()` call (same class as `validate-boring-logs`, not
`import-boring-logs`). Guards separately on the new `ocr` extra being installed,
raising a `click.ClickException` with an install hint
(`pip install autogis[ocr]`) before touching any model, the same UX pattern as other
missing-capability guards in this codebase.

Output: `lithology.csv` in `OUT_DIR` plus a QA report (stdout and/or `--report` file).
Never authoritative — the reviewer edits the CSV against the original scan, then runs
the existing `autogis envmon validate-boring-logs OUT_DIR` before anything downstream
touches it.

---

## Dependency Scope

New optional extra in `pyproject.toml`:

```toml
ocr = ["torch", "transformers", "pillow", "pymupdf"]
```

Same pattern as the existing `report`/`gui`/`profile`/`cloud` extras — core install
stays free of multi-GB ML dependencies. `pymupdf` handles PDF→image rasterization
without an external Poppler binary dependency. Model weights download from the
Hugging Face Hub on first use via `transformers`' own cache
(`~/.cache/huggingface`) — not reimplemented by this tool.

---

## Error Handling

- Missing `ocr` extra → `click.ClickException` before any model load.
- Corrupt/unreadable PDF, zero pages → `SEV_ERROR`, no CSV written.
- Zero tables detected on every page → `SEV_ERROR`, no CSV written (never fabricate
  rows).
- No network access required beyond the first-run model download; fully offline
  afterward.

---

## Test Strategy

`tests/envmon/test_draft_lithology_from_scan.py` — arcpy-free:

1. `map_columns()` against table-driven header-string fixtures (no model) — correct
   field mapping for known alias variants, unmapped columns ignored.
2. Confidence → severity threshold tests using hand-constructed `TableGrid`/`CellResult`
   fixtures (no image, no model) — verifies the three severity bands and the
   zero-tables-detected `SEV_ERROR` case.
3. `write_draft_csv()` → `parse_lithology_csv()` round-trip: rows written by this tool
   parse cleanly back through the existing reader with no data loss.
4. Model-backed steps (`extract_table_regions`, `recognize_structure`, the TrOCR call in
   `ocr_cells`) are integration-only, gated behind
   `pytest.importorskip("torch")`/`importorskip("transformers")`, matching the existing
   `Pillow`/`matplotlib`-gated pattern for the `dev`/`report`/`profile` extras. These
   don't run in default CI — only where `ocr` is installed.
5. **Follow-up, not blocking this design:** no real scanned boring-log fixture exists
   yet. Adding one (and validating the whole pipeline against it) is required before
   this tool's DRAFT banner can be removed.
