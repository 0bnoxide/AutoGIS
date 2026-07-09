# ADR-XXXX: DraftLithologyFromScan — headless boring-log OCR tool + the `ocr` heavy-ML optional extra

**Status:** Accepted

**Date:** 2026-07-09

> **Numbering:** filed as an `XXXX-` placeholder per `docs/adr/README.md` ("File
> naming" — collision-prone parallel-branch case). Assign the real next-free
> number **at merge**, after scanning `docs/adr/` *and* every open PR's files.
> At authoring time `0072` is the highest merged number and `0073` is already
> taken by open PR #209 (`0073-gui-report-plumbing-and-single-run-pause-parity.md`),
> so `0074` is the apparent next-free — re-confirm before renaming.

## Context

Legacy and third-party boring logs arrive as scanned PDFs / images. The
envmon boring-log pipeline (`create_boring_log_database.py` (8.0a),
`parse_lithology_csv` / `import_boring_logs.py`, `boring_log_report.py`) already
ingests **structured** lithology CSVs, but there was no on-ramp from a *scanned
table* to that CSV — an analyst had to retype every interval by hand.

A tool that OCRs a scanned boring-log table into a draft lithology CSV needs a
table-structure + cell-OCR ML stack (Table-Transformer for table/row/column
detection, TrOCR for cell text). That stack (`torch`, `transformers`, plus
`pymupdf` for PDF rasterization and `Pillow` for image handling) is **the first
heavy ML dependency to enter this repo**. Two decisions are therefore entangled
and both are ADR-worthy:

1. shipping a new tool (`DraftLithologyFromScan`), and
2. establishing **how heavy ML dependencies are admitted** without violating the
   arcpy-free core invariant (ADR-0002) — i.e. the precedent for `torch`/
   `transformers`, parallel to the existing `report`/`profile`/`gui` extras.

Two hard constraints frame the design:

- **`core/` and `adapters/` must import with zero OCR deps installed** (ADR-0002,
  generalized). Most users never OCR a scan; they must not pay a multi-hundred-MB
  torch install to run the CLI.
- **The output must round-trip through the *existing* parser.** The tool is an
  on-ramp, not a parallel schema — its CSV must be exactly what
  `parse_lithology_csv` already reads, or the tool creates a fork.

This tool is deliberately **out of scope of the phase-gated AI-assisted group**
(CLAUDE.md §11, `AIDraft*`/`AIExplain*`): it is deterministic document-OCR /
table-structure ML, not an LLM-driven judgment tool. It requires no LLM seam and
does not reopen that gate.

## Decision

1. **Ship `DraftLithologyFromScan` as a headless (arcpy-free) tool** —
   `autogis/core/envmon/draft_lithology_from_scan.py` + CLI command
   `autogis envmon draft-lithology-from-scan`. Pipeline:
   rasterize PDF/image (`pymupdf`) → detect table regions
   (`microsoft/table-transformer-detection`) → recognize row/column geometry
   (`microsoft/table-transformer-structure-recognition`) → OCR each cell
   (`microsoft/trocr-base-printed` / `-handwritten`) → fuzzy-map header columns
   to `LithologyInterval` fields → build rows with confidence→QA-severity flags →
   write the fixed CSV.

2. **New `ocr` optional-dependency extra**, following the `report =
   ["Pillow>=9.0"]` / `profile = ["matplotlib>=3.7"]` precedent
   (ADR-0046, ADR-0061):

   ```toml
   ocr = ["torch", "transformers", "pillow", "pymupdf"]
   ```

   The **binding rule for heavy ML deps** (the reusable part of this ADR): every
   `torch`/`transformers`/`fitz`/`PIL` import is **function-local, never at module
   level**, mirroring the lazy-`matplotlib` (`subsurface_profile`) and
   lazy-`Pillow` (`well_inspection_photo_report`) patterns — so
   `core/`/`adapters/` stay importable with the `ocr` extra absent. The
   model factories (`_get_detector`/`_get_structure_recognizer`/`_get_trocr`)
   are `@lru_cache`'d so each model loads once per process.

3. **CLI gates on the extra, not on an arcpy session.** This is a headless tool
   (like `validate-boring-logs`), so it takes **no `_guard()` call**. Instead a
   private `_require_ocr_extra()` probes `("torch", "transformers", "PIL",
   "fitz")` via `importlib.util.find_spec` (import names, not the `pillow`/
   `pymupdf` distribution names — and `find_spec` so the guard itself needs no
   heavy import) and raises a clean `click.ClickException` with a
   `pip install autogis[ocr]` hint **before** any model is touched. It is
   registered `Runtime.CLOUD` / `status="draft"` in `runtime/capabilities.py`
   (both `TOOLS` and `_REGISTRY_SEED`), which keeps the tool-registry parity
   tests green without being subject to `_guard()`.

4. **No new schema.** Rows are the existing `LithologyInterval`
   (`core/common/schema/boring.py`); QA reuses `QACollector`/`SEV_*`. `write_draft_csv`
   emits exactly the 8 headers `parse_lithology_csv` reads — `BoringID`,
   `TopDepth_ft`, `BottomDepth_ft`, `USCS`, `PrimaryMaterial`, `Color`,
   `Moisture`, `Description` — and a test pins the write→parse round-trip through
   the real parser (not a mock). Confidence→severity bands are advisory only: no
   table on any page → `SEV_ERROR`; row avg cell confidence <0.6 → `SEV_WARNING`,
   0.6–0.85 → `SEV_INFO`, ≥0.85 → no flag. The CLI never blocks the CSV write on
   QA — the analyst always gets a draft plus advisories.

5. **`map_columns` matches on whole tokens, not substrings.** Header→field
   aliasing anchors short aliases to word boundaries (a column literally headed
   "To" matches `bottom_depth`, but "Total Depth" no longer false-matches the
   bare `"to"` alias) and, when several aliases match a column, the longest wins
   ("Secondary Material" routes to `secondary_material`, not `primary_material`).
   `secondary_material` is a **deliberate mapped-but-not-emitted sink**: the alias
   exists only to stop "Secondary Material" false-matching `primary_material`, and
   the 8-column output schema intentionally excludes it (no `SecondaryMaterial`
   column in `parse_lithology_csv`).

6. **DRAFT / non-authoritative.** No real scanned boring-log sample has validated
   this pipeline. Explicit DRAFT banners live in the module docstring and the CLI
   `--help`; every row must be reviewed against the original scan and then run
   through `autogis envmon validate-boring-logs` before anything downstream uses
   it. This matches the H281-profile / screening-levels DRAFT-stub convention.

## Consequences

### Positive

- Gives legacy/third-party **scanned** boring logs a digitization on-ramp into
  the existing pipeline, reusing `LithologyInterval` and `parse_lithology_csv`
  rather than a parallel importer — the round-trip is test-pinned.
- The arcpy-free **and** ocr-free import invariant both hold: `core/`/`adapters/`
  import with neither `arcpy` nor `torch`/`transformers`/`fitz`/`PIL` present
  (empirically confirmed — the arcpy-free suite passes in an env without
  torch/fitz).
- Establishes a **reusable precedent** for admitting heavy ML dependencies:
  isolate them behind an optional extra, keep every import function-local, gate
  the CLI on the extra with a `pip install autogis[<extra>]` hint. Future ML
  tools follow this rather than re-litigating dependency policy.
- `_require_ocr_extra` surfaces the missing stack as a clean, actionable CLI
  error instead of a mid-pipeline `ModuleNotFoundError` traceback.

### Negative / accepted trade-offs

- **The model-backed path is unvalidated.** This environment has no
  `torch`/`fitz` and no real scanned fixture, so the ML-path tests are
  `pytest.importorskip`-gated and **SKIP** in CI; `rasterize_pdf`,
  `extract_table_regions`, `recognize_structure`, `ocr_cells`, and the
  model portion of `draft_lithology` are verified by code review only. Accepted
  as a documented Test-Strategy gap — the tool is DRAFT and mandates human review;
  it should be re-validated against a real scan before losing DRAFT status.
- **Known observability gap (follow-up, not a blocker):** if a table region is
  detected but structure recognition yields zero data rows, `found_table` stays
  `True`, so a 0-row draft is written with only the generic `SEV_INFO` record
  (no `SEV_ERROR`/`SEV_WARNING`). It is not fully silent — the CLI echoes
  `"(0 row(s))"` — but the QA report reads clean on an empty draft. A 3-line
  advisory (`if found_table and not rows: qa.add(SEV_WARNING,
  "table_detected_no_rows", …)`) is the noted fix; deferred to a follow-up.
- **`secondary_material` OCR text is dropped** when a "Secondary Material" column
  is present, because the output CSV is intentionally the 8-column set
  `parse_lithology_csv` reads. Accepted: emitting a 9th column would break the
  round-trip contract.

## Alternatives considered

1. **Bundle `torch`/`transformers` as base dependencies.** Rejected: a
   multi-hundred-MB ML stack for a feature most users never touch; the optional
   extra + lazy-import pattern (already proven for `Pillow`/`matplotlib`) keeps
   the default install lean.
2. **LLM-based extraction of the lithology table.** Rejected: that is the
   phase-gated AI-assisted group (CLAUDE.md §11), which is deferred pending the
   LLM-seam design. Deterministic document-OCR / table-structure ML needs no LLM
   seam and does not reopen that gate.
3. **Emit `secondary_material` as a 9th CSV column.** Rejected: `parse_lithology_csv`
   reads exactly 8 columns; a 9th would break the write→parse round-trip that is
   the whole point of matching the existing parser. `secondary_material` stays a
   mapping sink instead.
4. **Guess the next ADR number (`0074`) now.** Rejected in favor of the repo's
   documented `XXXX-` placeholder convention (assign at merge), because open PR
   #209 already holds `0073` and a second number guessed pre-merge can still
   3-way-collide — the exact failure mode `tests/test_adr_numbering.py` exists to
   catch (ADR-0034, 0061/0062 history).

## Related decisions

- [ADR-0002](0002-arcpy-free-core-invariant.md) — the arcpy-free `core`/`adapters`
  invariant this tool generalizes to "no heavy ML deps at module level either".
- [ADR-0046](0046-well-inspection-photo-report-headless-xlsx.md) — `Pillow` as a
  `report` optional extra; the lazy-import-with-friendly-hint precedent.
- [ADR-0061](0061-drone-geotech-graphics-tool-batch.md) — `matplotlib` as a
  `profile` optional extra, same lazy-import discipline this ADR follows for the
  `ocr` stack.
- `docs/superpowers/specs/2026-07-08-draft-lithology-from-scan-design.md` and
  `docs/superpowers/plans/2026-07-08-draft-lithology-from-scan.md` — the design
  and execution plan this ADR records.

## Issues/PRs

- New: `autogis/core/envmon/draft_lithology_from_scan.py`,
  `tests/envmon/test_draft_lithology_from_scan.py`,
  `tests/envmon/test_cli_draft_lithology_from_scan.py`.
- Modified: `autogis/adapters/cli.py`, `pyproject.toml`,
  `autogis/runtime/capabilities.py`.
- Follow-up (not in this branch): advisory QA record for the detected-table →
  zero-rows observability gap.
