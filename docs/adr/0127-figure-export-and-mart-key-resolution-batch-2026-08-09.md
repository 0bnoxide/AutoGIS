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
  proven ExportFigures chain". Six figure-spec keys (`visible_layers`,
  `hidden_layers`, `layout_text`, `default_layout_text`,
  `extent_boundary_layer`, `extent_buffer_pct`) were inert on the only
  batch-figure path that exists. (`figure_number` is a seventh key the CLI
  does not read, but it feeds `output_filename_pattern` only — decision 2
  below keeps the packet name, so it stays inert there deliberately.)
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

## Amendments from cold review (2026-08-11)

Two review passes ran against this batch. Both found real defects **introduced
by the centralization above**, which is worth recording rather than quietly
patching -- the pattern is that collapsing two divergent paths into one makes
their disagreements load-bearing for the first time.

**9. `export_layouts(layout_names=[])` means "export nothing" -- a contract
change to a public core seam.** `FIGURE_REQUIRED` is a key-*presence* check, so
a spec carrying `layout_name:` (YAML null) or `""` loads clean. Returning
`None` for those reproduced #459 exactly, with no QA record. Now
`prepare_figure_aprx` emits a `layout_name_missing` **ERROR**, short-circuits
(configuring nothing, since nothing will be exported), and returns `[]`; and
`export_layouts` narrows `if layout_names:` to `if layout_names is not None:`.
Callers passing `[]` previously got "no filter, export everything" and now get
"export nothing" -- in-tree there are none, but it is a behavior change to a
library function, not an internal detail.

**10. One layout-name match rule, case-insensitive, for every consumer.**
`export_layouts` has always lowercased; `update_layout_text` and
`zoom_to_boundary` compared exactly. While `layout_names` was permanently
`None` the two rules never had to agree. Once `prepare_figure_aprx` fed one
resolved name to all three, a case-mismatched spec **exported** the layout
while silently skipping its text and extent -- an unconfigured figure shipped
beside an ERROR claiming the layout was not in the APRX. `_select_layouts()` is
now the single rule, and `zoom_to_boundary` reports an unmatched layout instead
of returning silently.

**11. Figure-spec values are coerced at the trust boundary, not `float()`-ed.**
`extent_buffer_pct` and `layout_text` are not `FIGURE_REQUIRED`, so
`extent_buffer_pct:` (null) or `"5%"` loads clean and used to raise a raw
`TypeError`/`ValueError` out of the CLI -- a new crash surface, since
`gen-map-series` did not read either key before this batch. Both now coerce
with a WARNING and a default, matching `_load_json_option`'s stated convention
("usage mistakes at the CLI trust boundary, not crashes"). `visible_layers`
given as a bare scalar is normalized rather than iterated per character.

**12. The prior-water-level selector skips rows with no elevation.** Not a
figure-export issue at all -- a *semantic* conflict with ADR-0126 that a clean
textual merge could not surface. ADR-0126 gave Survey123 water levels a real
`EventDate`; those rows carry a DTW but no TOC, so post-merge they out-date the
workbook row, won `select_prior_water_levels`, and collapsed every `Delta_ft`
to NULL and every `Trend` to "Unknown" -- the precise symptom decision 3 above
claims to have fixed, re-entering through a different door. Neither change is
wrong alone. The selector now skips candidates with no usable elevation, so it
returns the latest prior that can actually produce a delta.

**13. Coercion helpers test for what is ACCEPTED, not for what is rejected.**
Round 2 added `_name_list`/`_text_map`/`_buffer_pct` and round 3 found all
three half-done: `_name_list` special-cased `str`, so every other scalar still
raised and a mapping silently iterated as its KEYS; `_buffer_pct` coerced the
type but not the value, so `nan`/`inf`/`-100` passed and a negative pad
inverts the extent. Each now tests for the shape it accepts
(`isinstance(value, (list, tuple, set))`, `math.isfinite and >= 0`) rather
than enumerating the shapes it rejects — an enumeration is a list that is
wrong the moment YAML produces a type nobody listed.

**14. One grammar for layout text.** `_text_map` was a *second* answer to a
question `load_layout_text_yaml` already answered in the same module: the
values file accepted a list of `{element_name, text}` dicts, the figure spec
rejected every list. Both now route through `_as_text_map()`; the values file
raises, the figure spec warns. Adding a divergent second rule while removing
duplication elsewhere is the same defect this batch is about, committed inside
the fix for it.

## Negative consequences of decision 12 (prior-row skip)

Skipping elevation-less prior rows means `Delta_ft` can span a **different**
pair of events than the two most recent, and `Dash_GWLevelSummary` has no
prior-date column to show which. The span can therefore change between runs as
new field rounds land, with nothing in the delivered table saying so. The skip
is still the right call — the alternative is a NULL delta — but it is a
disclosure gap, mitigated only by a `[prior-water-level]` INFO log when a
skipped candidate is newer than the chosen prior. A `PriorEventDate` column on
`Dash_GWLevelSummary` would close it properly and is deliberately **not** in
this batch (schema change, separate decision).

**15. The disclosure log is filtered by candidacy, and the layout-text
unification narrows rather than widens.** Round 4's own additions needed both.
The `[prior-water-level]` skip was recorded *before* the candidate filter, so
the current event's own DTW-only row was announced as a "shadowed prior" -- 
post-ADR-0126 that is every well, every run. Reordering the two independent
`continue` predicates costs nothing and leaves `by_loc` identical. And
`_as_text_map` originally unified the two layout-text grammars by teaching the
*figure spec* the values file's list form -- new surface area no shipped spec
uses and no schema mentions. It now shares only the mapping rule both sides
genuinely have; the list form stays in the hand-written file format's loader.
One grammar per file kind is still one grammar.

**A note on the shape of this batch.** Four review rounds. Round 1 fixed the
six filed issues, and those fixes have held unchanged through every subsequent
round. Rounds 2-4 found nothing wrong with them -- every later finding was in
*defensive code this batch added while fixing the previous round's finding*,
which is a real cost of centralizing two divergent paths: each collapse makes a
latent disagreement load-bearing for the first time, and each guard written to
absorb one is itself a new thing that can be half-right. The guards are worth
keeping (the crashes and inverted extents were real), but the honest lesson is
that the hardening, not the fixes, is what earned three rounds of review.

**New QA categories in this batch:** `required_layer_uncheckable`,
`layout_name_missing`, `bad_extent_buffer_pct`, `spec_value_not_a_mapping`,
`spec_value_not_a_list`, and a `layout_missing` record from `zoom_to_boundary`.

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
