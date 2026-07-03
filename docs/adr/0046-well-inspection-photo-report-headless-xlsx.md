# ADR-0046: GenerateWellInspectionPhotoReport (7.4) — headless XLSX from the harvest manifest; Pillow declared as an extra

**Status:** Accepted

**Date:** 2026-07-03

## Context

Roadmap tool 7.4 (`GenerateWellInspectionPhotoReport`) assembles the annual
per-well photo inventory: photo, condition, GPS, inspection info, notes. It
was built from the reconciled brief
`docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md` §2, because
the two 2026-06-28 design docs each had a disqualifying flaw:

- spec `docs/superpowers/specs/2026-06-28-generate-well-inspection-photo-report-design.md`
  proposed creating `core/envmon/well_inspection_report.py` — **a module that
  already exists** (shipped in PR #102 backing `well-inspection-report`, whose
  docstring explicitly defers photo attachments to this tool), and claimed
  "zero new dependencies" — false, since openpyxl's image embedding requires
  Pillow. It also required a hand-built photo-manifest CSV that duplicates
  what the attachment harvester's `manifest.csv` already records.
- plan `docs/superpowers/plans/2026-06-28-generate-well-inspection-photo-report.md`
  proposed an HTML renderer plus fpdf2 PDF output, and sourced GPS from the
  harvest manifest's `geometry` column — which is reserved and always empty
  (`core/harvest/models.py`), silently losing GPS.

## Decision

**Hybrid: the plan's inputs, the spec's XLSX output. Module
`core/envmon/well_inspection_photo_report.py`, CLI
`envmon generate-inspection-report` (CLOUD, headless).**

- **Photo source:** the harvester's `manifest.csv`/`.json`, read via the
  existing `index_field_attachments.load_manifest()`. No redundant
  user-built photo manifest.
- **Pilot assumption, isolated in `match_photos_to_wells()`:** the well ID is
  the first path component of `saved_path` under `--harvest-dir` — true only
  when the site's harvest `group_template` renders a well ID. Mismatches
  trip aggregated QA WARNINGs (`wells_without_photos`,
  `photos_without_record`) rather than failing silently.
- **Inspection metadata:** a separate user CSV whose headers extend the
  already-shipped `well_inspection_report.py` maintenance-log schema
  (`WellID, InspectionDate, Inspector, Condition, Notes`) with optional
  `GPS_Lat, GPS_Lon, DepthToWaterFt` — one schema can feed both tools. GPS
  comes only from this CSV.
- **Output:** openpyxl XLSX; photos EXIF-corrected, converted to RGB,
  thumbnailed to the `--photo-width`/`--photo-height` box, and embedded via
  `openpyxl.drawing.image.Image` (re-encoded JPEG bytes, so the workbook
  doesn't balloon to the original photo sizes).
- **Dependency:** `Pillow>=9.0` declared in `pyproject.toml` as a
  `[project.optional-dependencies] report` extra (matching the house style of
  the `cloud` extra for optional runtime deps) and added to `dev` so the
  Pillow-gated tests run in CI. Pillow is lazy-imported inside the write
  path only; `core/` and `adapters/` still import with neither arcpy,
  arcgis, nor Pillow present (locked by
  `test_module_imports_without_arcpy_arcgis_or_pillow`). A missing-photo
  workbook can even be written without Pillow — the import only happens when
  a photo file is actually embedded.
- **Dropped (YAGNI):** fpdf2, the HTML renderer, and any `--pdf` flag. No
  reporting tool in this codebase auto-generates PDF; it is a manual
  downstream step everywhere (same call as ADR-0042 for `gen-boring-logs`).
- **No DRAFT banner.** Considered per the brief's open risk (unvalidated
  against real field photos). DRAFT markers in this repo flag silently-wrong
  numeric/compliance stubs (screening levels, H281 profile); this tool's
  failure mode is loud — visible placeholder cells plus QA WARNINGs — so the
  pilot assumption is documented in the module docstring and surfaced
  through QA instead.

## Consequences

### Positive consequences

- Photo inventory reports come straight from a harvest run + one small CSV;
  no manual Word assembly (1–2 h/site).
- The group_template assumption is confined to one function with a QA
  tripwire, so a non-well-id harvest layout is detected, not silently empty.
- The `report` extra keeps base installs Pillow-free while making the
  requirement explicit instead of "works by luck of the environment".

### Negative consequences

- First Pillow usage in the codebase — a new (optional) binary dependency to
  track for CVEs/upgrades.
- One well's photos must share one harvest group directory; multi-template
  harvests need re-grouping before this tool can match them.

## Alternatives considered

- **Spec as written** — unbuildable (module-name collision with the shipped
  `well_inspection_report.py`) and its "zero new dependencies" claim is false.
- **Plan's HTML + fpdf2 PDF** — two renderers and an extra dependency for an
  output format no sibling tool auto-generates; rejected as YAGNI.
- **Pillow in base `dependencies`** — rejected; embedding is the only Pillow
  consumer, and the house style (the `cloud` extra) is to keep optional
  runtime capabilities in extras.

## Related decisions

- [ADR-0042: gen-boring-logs headless Markdown assembly](0042-gen-boring-logs-headless-markdown-assembly.md)
  — precedent for "PDF is a downstream step".
- [ADR-0038: record-dataclass naming](0038-record-dataclass-naming-convention.md)
  — `PhotoInspectionRecord` uses snake_case (internal record; the CSV headers
  stay PascalCase for schema alignment).
- Brief: `docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md` §2.
