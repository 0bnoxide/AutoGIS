# ADR-0127: Figure-export and dashboard-mart key-resolution batch (2026-08-09) — one chain, one key, one place

**Status:** Proposed

**Date:** 2026-08-09

## Context

The repo-wide wiring-gap survey of 2026-08-08 (#458–#463) and the cold review
of PR #464 (#466) filed a cluster that shares one failure class, adjacent to
but distinct from ADR-0124's and ADR-0126's:

- **ADR-0124**: doing something *plausible* instead of admitting you cannot do
  the right thing.
- **ADR-0126**: a lookup that structurally *cannot succeed*, answering anyway.
- **This batch**: **two copies of one chain that drifted apart, and a key read
  from the wrong vocabulary.** The code is reading a name — a config key, a
  column — that its own source never defines. There is a correct name; the
  reader is simply using the other one, or a second copy of the reader never
  got the fix.

Every member produces a confident, wrong deliverable and no error:

- **#459** Both figure-export call sites selected layouts with
  `spec.get("layouts")` — a key defined by no shipped spec, no template, no
  ADR. The schema key is the singular `layout_name`, which is in
  `FIGURE_REQUIRED`. So `layout_names` was always `None`, `export_layouts` fell
  through its filter, and **every layout in the APRX was exported** — each one
  other than the configured layout carrying the template's saved extent, no
  title, no figure number, no draft note. Because the default filename pattern
  has no `{layout}` token, they all collided on one stem and `_versioned()`
  disambiguated them as `_v2.pdf`, `_v3.pdf`. The operator received a folder of
  near-identical PDFs, exactly one correct, with a truthful-sounding file count.
  The `layout_missing` ERROR that exists to catch a bad layout name was
  unreachable for the same reason.
- **#462** `gen-map-series` executes arcpy directly and had no `.pyt`
  equivalent, but carried its *own* copy of the ExportFigures chain — one that
  had lost `set_layer_visibility`, `update_layout_text` and `zoom_to_boundary`
  entirely. `map_series_plan`'s module docstring asserted it "replays the
  proven ExportFigures chain". Seven figure-spec keys (`visible_layers`,
  `hidden_layers`, `layout_text`, `default_layout_text`,
  `extent_boundary_layer`, `extent_buffer_pct`, `figure_number`) were inert on
  the only batch-figure path that exists.
- **#466** `build_dash_well_status` / `build_dash_gw_level_summary` read prior
  water levels as `GWE_ft`. Prior rows come from `Env_WaterLevels`, whose
  column is `GroundwaterElevation_ft`; `GWE_ft` is the
  `Env_CurrentWaterLevelEvent` spelling, which the *current* side reads
  legitimately. So `PriorGWE_ft` and `Delta_ft` were always NULL and `Trend`
  was always `"Unknown"` on the delivered dashboard — a reviewer saw a site
  where nothing had moved.
- **#461** `LoadFigureSpec` (.pyt) wrote a hardcoded figure-spec skeleton that
  `FigureSpec.load` rejects: it omitted `figure_title` (a `FIGURE_REQUIRED`
  key) and offered `analyte_set_name`, which is the name of a Python parameter
  on `analyte_list()`, not a config key. The tool reported "Template written".
  The failure surfaced one tool later, attributed to the operator's editing.
  `autogis/config/_templates/site_skeleton/figure_spec.yaml` — the twin
  `init-site` writes — was valid the whole time; only the CLI copy was
  maintained.
- **#460** `export-wqx` constructed a `QACollector`, fed it to `map_to_wqx`,
  and never read it. An AST scan of all 120 `@envmon.command` bodies found this
  was the only one. The discarded records include `wqx_out_unmapped_matrix` —
  and an unmapped matrix is *not* a rejected row, so it appeared in neither the
  rejections CSV nor any report. The command carried no `@qa_report_options`,
  so no CI gate could fail an outbound regulatory submission; it exited 0
  regardless. Its docstring asserted "nothing silently disappears".
- **#463 item 2** `preexport_qa` caught `GetCount` failures with a bare
  `except: pass`, so a required layer whose count could not be taken produced
  no record *and* the function still returned `True`. "We could not check" was
  indistinguishable from "we checked and it was fine".
- **#463 items 1, 3–5** `combined_pdf_name` (read at one line, defined
  nowhere) and three parameters no function body reads.

## Decision

**1. One chain, extracted, not two copies kept in sync.**
`layout_manager.prepare_figure_aprx()` now owns the six-step figure
preparation chain (copy → repath → definition queries → visibility → layout
text → zoom). `ExportFigures` (.pyt) and `gen-map-series` (CLI) both call it.
This is the root-cause fix for #462: bringing the four missing steps across by
copy-paste would have created four new drift points in the same place the
first three drifted. It is also what makes #459's fix land once —
`prepare_figure_aprx` returns `(work_aprx, layout_names)`, resolving
`layout_name` in the one place both callers route through, so the wrong key
cannot come back at one call site only.

**2. `gen-map-series` keeps `{stem}` filenames, deliberately.**
#462 listed the hardcoded `"{stem}"` pattern as a fourth omission. It is not.
`plan_map_series`'s `out_name` is the *packet* name and it carries the mode's
grouping and ordering (`Appendix_001_…`, and the distinct per-mode stems for
`per_map_type` / `historical`). Since `output_filename_pattern` is
`FIGURE_REQUIRED`, letting the per-figure pattern win would override the
packet name on **every** run and collapse all four modes onto identical names.
The docstring was the thing that was wrong, and both it and
`map_series_plan`'s module docstring now state the departure explicitly rather
than claiming parity that should not exist.

**3. Table-name differences resolve at one seam, not at each consumer.**
`_prior_gwe_by_location()` accepts either spelling and is used by both mart
builders. The two source tables genuinely name the same quantity differently
and that is not changing, so the difference is absorbed once. Rejected:
normalizing inside `select_prior_water_levels`, which would mutate the
caller's row dicts (the selector returns references to its input).

**4. One figure-spec skeleton.** `init_site.render_figure_spec_template()`
renders the shipped template; the `.pyt` calls it. The second hardcoded copy
is deleted. A second copy of a template *is* the defect — keeping one and
fixing its two errors would leave the drift mechanism in place.

**5. `export-wqx` gets the standard QA tail.** `@qa_report_options` +
`_render_qa(qa, report, fail_on)`, matching every sibling command. The records
were already being produced correctly; they had nowhere to go.

**6. "Could not check" is a QA record, not silence.** `preexport_qa` narrows
its swallow to a `required_layer_uncheckable` WARNING naming the layer and the
exception class. Non-blocking, like the `required_layer_empty` warning it sits
beside — the change is that it is now *visible*.

**7. Dead reads deleted rather than documented.** `combined_pdf_name` is
dropped from the `.pyt` call site: with #459 fixed, an export emits exactly one
layout, so combining a single PDF is a no-op rename. `export_layouts`'
`combine_pdf` *parameter* stays — it is a working library seam named by
ADR-0047, and `gen-map-series` uses the same `PDFDocumentCreate` primitive for
its genuine cross-APRX combine. The three dead function parameters are removed.

**8. A producer/consumer test, not just the fixes.**
`test_every_figure_spec_key_read_on_the_export_path_exists` asserts every
`spec.get(...)` key on the export path is in `FIGURE_REQUIRED` or supplied by a
shipped spec. This is the *third* instance of the class (#443 `contours`, #459
`layouts`, #463 `combined_pdf_name`); the fixes alone would not have stopped a
fourth.

## Consequences

### Positive

- A multi-layout APRX template no longer produces a folder of unconfigured
  near-duplicate PDFs. The `layout_missing` QA ERROR becomes reachable.
- CLI-driven map series get layer visibility, layout text and site-boundary
  extent — the only batch-figure path in the suite now produces configured
  figures.
- `Dash_WellStatus` / `Dash_GWLevelSummary` show real deltas and trends.
- `export-wqx` can be gated in CI (`--fail-on warning`).
- `LoadFigureSpec`'s output loads.
- Four figure-spec key defects and three dead parameters are gone, and the
  class has a test.

### Negative / residual

- **`gen-map-series` output changes.** Figures previously exported with the
  template's saved extent and no title now carry the spec's. That is the fix,
  but a caller who had adapted to the old output will see different PDFs.
- **File counts drop.** Where a template has multiple layouts, an export that
  used to write N files now writes 1. Correct, and visible.
- **`export-wqx` can now fail.** A run with `--fail-on warning` and an unmapped
  matrix code exits non-zero where it previously exited 0.
- **A new WARNING category.** `required_layer_uncheckable` will surface on
  APRXs where it was previously silent. That is the point, but it can appear on
  a pipeline that read as clean.
- **Not verified live.** This is a cloud session with no arcpy.
  `prepare_figure_aprx`, `export_layouts` and `preexport_qa` are
  `pragma: no cover` arcpy seams; the chain's step order, its returned
  `layout_names`, and the QA branch are pinned by headless tests with arcpy
  mocked, but no ArcGIS Pro run has exercised them. **No arcpy call signature
  is added or edited in this batch** — `prepare_figure_aprx` calls the existing
  `layout_manager` functions unchanged, and only the `except` handler around
  `arcpy.management.GetCount` changed — so ADR-0077 has no new call to verify.
  A live-Pro `ExportFigures` and `gen-map-series` run is still owed before the
  new chain is trusted in the field.
- **#458 is deliberately not fixed here.** Six shipped tools carry a roadmap id
  the catalog assigns to a different tool. The right number is an owner call
  (the README's own `Roadmap #` column contradicts the prose in several rows),
  so this batch adds evidence to the issue rather than guessing. The README
  audit this session extended it: `TOOL_REGISTRY` also has five duplicate
  `roadmap_id` values and three ids resolving to no catalog heading.

## Alternatives considered

- **Fix `spec.get("layouts")` at each call site.** Two one-line edits, no
  extraction. Rejected: it leaves #462's drift entirely unfixed, and the next
  chain step added to one caller drifts again.
- **Accept both `layouts` (plural) and `layout_name`.** Rejected by YAGNI — no
  spec, template or doc defines the plural, and inventing a multi-layout
  contract to preserve a key that was a typo is backwards.
- **Delete `export_layouts`' `combine_pdf` branch entirely** (as #463 offers).
  Rejected: it is a working library parameter named by ADR-0047 and is not
  itself the defect; the defect was a caller reading a key nothing defines.
- **Give `.pyt LoadFigureSpec` a corrected literal skeleton.** Smaller diff,
  but preserves two skeletons — the exact mechanism that produced #461.
