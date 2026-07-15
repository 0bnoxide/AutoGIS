# Agent decisions — 2026-07-15 (Phase-5 geostat architecture review, ADR-0085)

Judgment calls made while running the reuse inventory and drafting ADR-0085
per `docs/HANDOFF-2026-07-15-geostat.md`.

## Nondetect policy: flagged as undesigned, not reused as the handoff doc suggested
**Decision:** Report that no reusable nondetect substitution config exists,
contradicting the handoff doc's pointer to check `generate-reg-tables`'s
config shape.
**Reasoning:** Read `regulatory_table_builder.py` directly —
`ND_QUALIFIERS` is a display-label set only (prints "ND"/"U"/"BDL" in cells),
not a numeric substitution rule (half-RL/RL/zero). `apply_screening.py`
separately hardcodes "non-detect never exceeds" for the exceedance flag.
Neither is what decision 4 needs. Reporting the gap accurately matters more
than following the handoff doc's suggestion verbatim — a wrong reuse claim
in the ADR would mislead whoever specs slice 2.
**Revisit if:** a nondetect substitution config turns up elsewhere in the
codebase that this search missed.

## Scoped BuildAnalyticalConcentrationSurface down to a draft-plume-boundary extension
**Decision:** Recommend slice 1 extend the already-shipped
`draft-plume-boundary` tool (site-boundary clip only) rather than treat
`BuildAnalyticalConcentrationSurface` as a new tool to build from scratch.
**Reasoning:** `draft_plume_boundary.py` already implements
`CONDITIONAL_TOOLS_REVIEW.md`'s "Phase 1: Deterministic plume" — convex/
concave hull from `ExceedsScreeningLevel==1` points, DRAFT-status GDB write.
It ships under a different CLI name (`draft-plume-boundary`, tool 4.5)
than the gated tool it's the review-doc analog of, which is likely why the
handoff doc's shipped-infrastructure list didn't connect the two despite
listing the module. Building a second, parallel hull tool would duplicate
tested logic for no behavioral gain.
**Revisit if:** the user wants `BuildAnalyticalConcentrationSurface` kept as
a distinct tool identity rather than folded into `draft-plume-boundary`'s
scope — this is a naming/product decision the ADR doesn't have standing to
make unilaterally, so it's called out for sign-off, not assumed.

## Reused Env_GWContourPoints instead of new GW_ModelInputPoints/GW_ModelExcludedPoints tables
**Decision:** ADR-0085 recommends reusing the existing
`Env_GWContourPoints` table for model input/excluded points rather than
adding the two new tables the review doc names literally.
**Reasoning:** Column-for-column, `Env_GWContourPoints` already carries
`SiteID/EventDate/LocationID/GroundwaterElevation_ft/UseForContour/
ExclusionReason` — the same fields the review doc's two proposed tables
would hold. ADR-0075 sets a "never duplicate registered schema for cosmetic
reasons" precedent for exactly this kind of choice.
**Revisit if:** slice-1 implementation finds a field genuinely missing from
`Env_GWContourPoints` that only a dedicated `GW_Model*` table could hold
(e.g. a per-run discriminator if the same site/event gets modeled twice).

## EBK/kriging kept out of slice 1 entirely, not stubbed
**Decision:** ADR-0085 defers all EBK/kriging decisions (execution mode,
uncertainty presentation) to slice 2 rather than sketching a tentative
design now.
**Reasoning:** ADR-0077 requires arcpy calls to be doc-verified against
pro.arcgis.com in the same session that writes them; this session did not
verify any Geostatistical Analyst call signatures. Writing even a tentative
kriging design here would create an ADR-blessed shape that the next session
might implement against without redoing verification — worse than leaving
it explicitly unresolved.
**Revisit if:** a future session doc-verifies the relevant Geostatistical
Analyst calls and is ready to spec slice 2.
