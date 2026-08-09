# Agent decisions — 2026-08-09

Session task (scheduled, no live owner): fix open issues by significance, check
the README against actual repo state, survey for wiring gaps and stale
assertions, and open a ready-for-review PR. Every call below was made
autonomously. ADR-0127 is the durable record of the design decisions; this log
records the judgment behind them and the calls that did not warrant an ADR.

## Take the seven survey issues and leave PR #464's six alone

**Decision:** Fix #459, #460, #461, #462, #463, #466 here. Do not touch #412,
#420, #425, #454, #455, #457.

**Reasoning:** PR #464 is open against the same base and closes that second
set. Re-fixing them would produce conflicting diffs on the same files
(`survey123` normalizer, `gdb_schema`, `coord_cli`) for no gain. The seven I
took are on disjoint paths (figure export, dashboard mart, WQX) and form one
coherent failure class of their own.

**Revisit if:** #464 is closed unmerged — its six would then need a home.

## Extract the chain instead of copying four steps into the CLI

**Decision:** `layout_manager.prepare_figure_aprx()` owns the six-step figure
preparation chain; both call sites call it. #462 could have been closed by
pasting `set_layer_visibility` / `update_layout_text` / `zoom_to_boundary` into
`gen_map_series_cmd` — three lines.

**Reasoning:** Two copies of one chain drifting apart *is* #462. The paste fixes
today's drift and rebuilds the mechanism that caused it, in the same place. It
also would have left #459's `spec.get("layouts")` to be fixed at two call sites
independently — the shape that let the wrong key survive in both for this long.
Returning `(work, layout_names)` from one function means neither defect has two
places to come back to. This is a bigger diff than the lazy fix and I judged it
the *smaller* one over the next change to this chain.

**Revisit if:** A third caller needs a materially different chain — then the
parameterization is the thing to question, not the extraction.

## Rule that `gen-map-series`' `{stem}` filename is correct, and fix the doc

**Decision:** Do not apply the spec's `output_filename_pattern` in
`gen-map-series`, contrary to row 7 of #462's table. Correct the two docstrings
that claimed full parity instead.

**Reasoning:** I traced `plan_map_series` before changing anything.
`out_name` is the packet name and it is the only thing carrying each mode's
grouping and ordering — `Appendix_001_…` for `combined_appendix`, and distinct
stems for `per_map_type` vs `historical`. `output_filename_pattern` is
`FIGURE_REQUIRED`, so it is set on every spec; letting it win would override
the packet name on every run and collapse all four modes onto identical names.
The issue filed this as an omission; it is a design difference, and the
docstring asserting parity was the actual defect. Fixing the code to match a
wrong doc would have broken the four modes to satisfy a sentence.

**Revisit if:** The owner wants per-figure naming in batch mode — that needs a
`{stem}` token in the pattern, not a silent override.

## Absorb the two table spellings at a helper, not in the selector

**Decision:** `_prior_gwe_by_location()` accepts both `GroundwaterElevation_ft`
and `GWE_ft`. #466 suggested normalizing inside `select_prior_water_levels`.

**Reasoning:** The selector returns *references* to its input rows; adding a
key there mutates the caller's `Env_WaterLevels` data as a side effect of a
function documented as a pure selector. The helper gets the same "one place"
property with no mutation, and it also deletes a dict comprehension that was
duplicated verbatim across both builders.

## Rewrite the three test fixtures that agreed with #466

**Decision:** Change `tests/envmon/test_dashboard_data_mart.py` prior-row
fixtures from `GWE_ft` to `GroundwaterElevation_ft`, and pin that spelling to
`TABLE_SCHEMAS` in a separate assertion.

**Reasoning:** Those fixtures passed *because* they restated the defect — they
fed the builder the current-event column name for rows that in production come
from a table that has no such column. A fix with the old fixtures still green
proves nothing. The schema-pinning test is there because a future edit could
otherwise "fix" the fixture back. Verified by reverting `autogis/` and
re-running: 12 of the new/edited tests fail against the unfixed source.

## Delete the `.pyt`'s figure-spec skeleton rather than correct it

**Decision:** `LoadFigureSpec` renders
`init_site.render_figure_spec_template()`; the hardcoded copy is gone.

**Reasoning:** #461 offers both. Correcting the literal is the smaller diff and
leaves two skeletons — which is what produced the bug (only the CLI copy was
maintained). `render_figure_spec_template` is a thin wrapper over `_render` /
`_read_template`, which already existed; the new surface is one function, not a
mechanism.

**Revisit if:** The `.pyt` skeleton ever needs to differ from `init-site`'s —
then it needs its own template *file*, not a string constant.

## File the registry defects rather than fix them

**Decision:** Two findings from the README audit go to GitHub, not into this
diff: `ManageScreeningLevels` carries `runtime="DRAFT"` (so
`envmon list-tools --runtime CLOUD` omits it, reproduced live), and
`TOOL_REGISTRY` has five duplicate `roadmap_id` values plus three ids resolving
to no catalog heading (extending #458).

**Reasoning:** Both look like typos and neither is. `--runtime` accepts
`"DRAFT"` as an explicit `click.Choice`, so DRAFT-as-runtime was a deliberate
decision at some point even though `status="draft"` already carries it and
`RUNTIME_MAP` says `CLOUD`. And #458 already established that the correct
roadmap numbers are an owner call, because the README's own `Roadmap #` column
contradicts its prose. Guessing either would replace a visible wrong answer
with an invisible one.

## Keep `export_layouts`' `combine_pdf` parameter after deleting its only caller

**Decision:** Drop `combine_pdf=spec.get("combined_pdf_name")` from the `.pyt`
(#463 item 1); keep the parameter and the branch in `export_figures`.

**Reasoning:** #463 offers "document the key or drop the argument and the
branch". The key is genuinely dead — with #459 fixed an export emits one
layout, so combining one PDF is a rename. But the *parameter* is a working
library seam named in ADR-0047, and `gen-map-series` uses the same
`PDFDocumentCreate` primitive for its cross-APRX combine. Deleting a
documented library capability to close a caller-side defect overshoots.

## Report, don't fix: `Dash_OpenIssues.AssignedTo`

**Decision:** A schema sweep of the mart found `build_dash_open_issues` reads
`AssignedTo` from `Env_ImportQA`, which has no such column — so the delivered
column is always blank. Reported in the PR, not fixed.

**Reasoning:** Same class as #466 but it has an explicit `""` default rather
than a silent `None`, and `Env_ReviewComments` *does* have `AssignedTo`.
Whether `Dash_OpenIssues` should source assignment from a different table is a
data-model decision, not a typo.

## Install `numpy` rather than work around the collection errors

**Decision:** `pip install -e .` at session start; no repo change.

**Reasoning:** Four test files failed collection on `ModuleNotFoundError:
numpy` — the session-start hook installs a hand-maintained dep list behind
`--no-deps`. PR #464 already fixes that hook. Fixing it here too would conflict
for no benefit, and running the suite against 2909 of 2954 tests would have
hidden regressions.
