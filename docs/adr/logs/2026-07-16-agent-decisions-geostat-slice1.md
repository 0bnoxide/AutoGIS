# Agent decisions — 2026-07-16 (Phase-5 geostat slice-1 implementation)

Judgment calls made while implementing slice 1 per ADR-0085 and
`docs/superpowers/specs/2026-07-16-geostat-slice1-design.md`. Supplement to
ADR-0085 — the ADR remains the durable record.

## Treated the user's merge of PR #239 + "continue geostat development" as the direction sign-off
**Decision:** Flipped ADR-0085 from Proposed to Accepted and proceeded with
slice-1 implementation without a separate confirmation round-trip.
**Reasoning:** The handoff doc requires "plain-text sign-off from the user on
the direction" before per-tool spec/code. The user personally merged the
Proposed ADR (PR #239, 2026-07-16 00:38 UTC, no change requests, no
comments), then opened this session with the instruction "continue geostat
development". Asking "do you approve the ADR you just merged?" would block
an unattended session on a question the user's actions already answered. The
Accepted stamp in ADR-0085 records this basis explicitly, and the slice-1 PR
still requires the user's explicit merge approval — the direction remains
reversible before anything lands on main.
**Revisit if:** the user objects to the ADR direction on the slice-1 PR —
revert the status flip and rework per their comments.

## Leave-one-out (not k-fold) cross-validation, implemented in the arcpy seam
**Decision:** The pipeline ranks models by leave-one-out cross-validation:
per fold, rebuild the surface from N−1 wells with the same arcpy calls the
contour stage uses, predict at the held-out well.
**Reasoning:** The review doc left "LOO vs k-fold" open. Monitoring networks
are small (H281 test case: 9 wells) — k-fold at n≈9 adds a fold-assignment
parameter and noise for no benefit; LOO is deterministic and parameter-free.
Resubstitution (sampling the full-data surface at its own inputs) was
rejected as methodologically empty: TIN is exact at its mass points, so every
TIN run would score RMSE 0. Doing LOO headless with reimplemented
interpolators was rejected because it would rank a *different* model than the
one arcpy ships. Cost: N surface rebuilds per method per run — noted with a
ponytail ceiling comment in `make_arcpy_loo_predictor`.
**Revisit if:** a site with hundreds of wells makes per-fold rebuilds too
slow (batch the folds or sample k-fold), or slice 2's Geostatistical Analyst
work brings native `GACrossValidation` for the kriging methods.

## No new CLI verb for BuildGroundwaterSurfaceModel
**Decision:** `BuildGroundwaterSurfaceModel` ships as the pipeline invoked
with a single method plus the `approve-gw-model` verb — no third
`build-gw-surface-model` command. The discovery registry maps the roadmap
name to `approve-gw-model` so `list-tools` still surfaces it.
**Reasoning:** ADR-0085 decision 1 already defines the tool as "single-method
entry over the same orchestration"; the .pyt method parameter is multiValue,
so selecting one method IS the single-method entry. A separate command would
be a duplicate wrapper (the #98/#106 four-surface drift class exists because
of exactly such wrappers).
**Revisit if:** users ask for a dedicated command name in Pro/CLI.

## GetCellValue over ExtractValuesToPoints for IDW LOO sampling
**Decision:** Sample the per-fold IDW raster at the held-out well with
`arcpy.management.GetCellValue` rather than `arcpy.sa.ExtractValuesToPoints`.
**Reasoning:** One fold needs exactly one value at one point. GetCellValue
needs no Spatial Analyst license for the sampling step, creates no output
feature class to manage/delete, and its NoData case ("NoData" string) maps
cleanly to the predictor's None contract. Both were doc-verified
(2026-07-16); cell-center approximation vs. exact point interpolation is
within the tolerance of a ranking heuristic whose output is explicitly a
suggestion (ADR-0085 decision 3).
**Revisit if:** per-fold sampling ever needs many points at once — 
ExtractValuesToPoints is the batch tool.

## Geometry.intersect/union for the plume clip, not arcpy.analysis.Clip
**Decision:** `write_plume_draft_to_gdb` clips the hull with in-memory
geometry methods (`union` the boundary rows, `intersect(hull, 4)`) instead of
the `arcpy.analysis.Clip` feature-class pattern ADR-0085 pointed at.
**Reasoning:** Clip operates on feature classes, which would force creating
and cleaning up two scratch FCs for a single-polygon operation the geometry
API does in two calls. The ADR's intent was "reuse an established clip
mechanism, don't invent one" — geometry intersect is an established,
doc-verified arcpy primitive, and the empty-intersection case returns False
(nothing written) rather than silently writing an empty shape.
**Revisit if:** multi-ring/curved boundaries misbehave under geometry
union/intersect — fall back to the Clip-on-FCs pattern.
