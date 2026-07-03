# ADR-0047: gen-map-series (Tool 5.6) — CLI-first batch figure-packet exporter reusing the ExportFigures chain

**Status:** Accepted

**Date:** 2026-07-03

## Context

Roadmap Tool 5.6 (`GenerateSiteMapSeries`, `docs/envmon-feature-roadmap.md`
§5.6) builds figure packets across many sites/events: one PDF per site, per
map type, a combined report appendix, or a historical event series — inputs
are a site list, event list, figure-spec folder, and output folder.

Two pre-existing docs described **different tools** under this number:

- The design spec (`docs/superpowers/specs/2026-06-28-generate-site-map-series-design.md`)
  matches the roadmap: an arcpy-free planner (`plan_map_series()`) expanding
  the site × event × figure-spec matrix into an ordered job list, plus an
  arcpy export driver.
- The implementation plan (`docs/superpowers/plans/2026-06-28-generate-site-map-series.md`)
  instead built around ArcGIS Pro's Map Series / Data Driven Pages layout
  feature (`arcpy.mp.MapSeries`), which iterates pages *within one layout*
  and structurally cannot span multiple sites or events — and which appears
  nowhere else in this codebase.

The batch brief (`docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md`
§3) resolved this: build the spec's tool, discard the plan's design.

The spec's Architecture section also predates ADR-0039: it routes the export
through a new `.pyt` toolbox tool class per the old ADR-0006 pattern.

## Decision

- **The plan doc is superseded.** Its header now carries a superseded banner
  pointing at the spec and this ADR, so its `MapSeriesConfig` /
  `export_map_series` / Data-Driven-Pages design does not get resurrected.
- **CLI-first per ADR-0039, not a `.pyt` tool class.** Tool 5.6 is a batch
  matrix exporter — the opposite of a tool needing interactive map context —
  so it ships as the `envmon gen-map-series` CLI command (name matches the
  `gen-boring-logs` precedent), a generation-2 LOCAL tool with no `.pyt`
  entry. Same reasoning as `update-layout-text` (5.8, ADR-0041).
- **Dual-path guard** following `survey-to-well-elevation`'s pattern:
  `--dry-run` runs `plan_map_series()` and prints the ordered job list with
  zero arcpy (the headless test surface); `_guard("gen-map-series")` fires
  only immediately before the export loop.
- **The only new logic is the arcpy-free planner**
  (`core/envmon/map_series_plan.py`): `MapJob` + `plan_map_series()` per the
  spec's Public API — pure stdlib, deterministic unique naming, four packet
  modes as selectors over one matrix expansion. The export loop replays the
  proven `ExportFigures.execute()` chain per job:
  `update_aprx_data_sources` → `apply_figure_definition_queries` →
  `export_layouts` → `register_exports`. Nothing in that chain was
  reimplemented. The one addition: `combined_appendix` mode concatenates the
  per-job PDFs into a single appendix with `arcpy.mp.PDFDocumentCreate` —
  the same primitive `export_layouts` already uses for its single-APRX
  `combine_pdf`.
- Registered on **both** capability surfaces (`TOOLS["gen-map-series"] =
  Runtime.LOCAL` and a `_REGISTRY_SEED` tuple) — the ADR-0039/H3 drift class.

## Consequences

### Positive consequences

- Packet planning is fully testable headless: the four modes, naming
  determinism/uniqueness and format propagation are covered arcpy-free, and
  the CLI `--dry-run` path is exercised end-to-end in CI.
- The arcpy export surface adds no new arcpy code paths beyond the ~10-line
  appendix concatenation; everything else is the already-shipped
  `layout_manager` / `export_figures` chain, so per-figure behavior
  (versioned filenames, pre-export QA, registry rows) is identical to
  `ExportFigures`.
- A stale plan doc that described the wrong tool is now flagged in place
  instead of silently contradicting the shipped implementation.

### Negative consequences

- The export loop lives in `cli.py` rather than a core module, mirroring the
  `ExportFigures.execute()` body it replicates; if a third consumer of the
  chain appears it should be extracted (currently `.pyt` + CLI).
- The arcpy export path is untestable in this arcpy-free environment (same
  risk class as ADR-0017/0039 deferrals); it reuses proven calls to bound
  that risk.

## Alternatives considered

1. **The plan doc's Data-Driven-Pages design (`map_series.py`,
   `MapSeriesConfig`, `export_map_series`, `filter_pages`):** rejected — it
   misreads Tool 5.6; `arcpy.mp.MapSeries` iterates pages within one layout
   and cannot span the site/event matrix the roadmap requires.
2. **The spec's `.pyt` toolbox tool class:** rejected — cites the
   pre-ADR-0039 architecture; a batch exporter has no need for interactive
   map context, ADR-0039's only trigger for adding a `.pyt` GUI.
3. **Unconditional `_guard()` at command start (the 5.8 pattern):** rejected
   — it would make the planner unreachable headless and untestable in CI;
   the dual-path pattern keeps the plan a first-class headless surface.

## Related decisions

- [ADR-0039: Generation-2 LOCAL tools are CLI-first](0039-cli-first-generation-2-local-tools.md)
- [ADR-0040: Canonical arcpy-access style](0040-canonical-arcpy-access-style.md)
  — arcpy-touching imports are function-scope in the CLI command body.
- [ADR-0041: update-layout-text CLI reuses layout_manager](0041-update-layout-text-cli-reuses-layout-manager.md)
  — the reuse precedent this tool follows.
- [ADR-0006: .pyt toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
  — still governs tools 2–8; not extended to this tool.
- `docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md` §3 — the
  conflict resolution this ADR records.
