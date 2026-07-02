# ADR-0036 — AGOL web map + hosted views batch (2026-07-02):
UpdateAGOLWebMapFromFigureSpec, CreateHostedViewsForStakeholders

**Status:** Accepted
**Date:** 2026-07-02
**Deciders:** Greg / Claude (Fable plans+reviews, Sonnet implements)
**Related:** ADR-0002 (arcpy-free core), ADR-0003 (HarvestConfig canonical location — established the "config is
core business logic, one loader" precedent this batch follows),
issue #118 precedent (agol-group CLI commands skip `capabilities.py`/`_guard()`),
`docs/superpowers/specs/2026-06-28-update-agol-webmap-from-figure-spec-design.md`,
`docs/superpowers/specs/2026-06-28-create-hosted-views-for-stakeholders-design.md`

---

## Context

Second batch from the 2026-07-02 graph-based repo-structure brief's
recommended build order: two independent CLOUD/AGOL tools sharing the
`core/agol/*` injected-`gis`/lazy-`arcgis` contract established by
`publish.py` and `dashboard_publish.py`. Unlike the prior CAD/Civil3D batch
(ADR-0035), these two have no build-order dependency on each other and were
planned/implemented/reviewed as one pass.

## Decision

Ship both tools' core logic + CLI wiring, TDD, with the specs' shapes as
designed:

1. `autogis/core/agol/webmap.py` — `WebMapUpdateResult`,
   `apply_spec_to_webmap_json` (pure), `update_webmap_from_spec`
   (orchestrator). **Scoped to visibility + definition-query fields only**
   — the canonical `FigureSpec` (`autogis/core/common/config.py`,
   `FIGURE_REQUIRED`) carries no popup/label/symbology config, so the
   spec's broader Architecture-section wording is narrowed to what the
   real data actually supports. Every real figure-spec YAML under
   `autogis/config/figure_specs/` confirms this.
2. `autogis/core/agol/hosted_views.py` — `ViewSpec`, `ViewResult`,
   `resolve_fields` (pure), `load_view_specs` (pure), `create_stakeholder_view`
   (orchestrator, single lazy `arcgis.features.FeatureLayerCollection`
   import inside the create branch only).
3. `agol update-webmap` / `agol create-views` CLI commands, inserted after
   `promote_cmd`. Neither registered in `capabilities.py`'s `TOOLS` dict nor
   guarded — same PR #118 precedent as every other `agol`-group command.
4. `agol create-views` fails pre-flight (`click.UsageError`) on a malformed
   view-spec YAML (missing `name`/`source_layer`, or both `allow_fields` and
   `deny_fields` set) before touching AGOL at all.

### Safety fixes from Fable's adversarial review (landed before merge)

An independent Fable review of the first-pass implementation (same model
that planned it, reviewing the Sonnet-implemented diff) found three real
gaps, all fixed with tests locking the fix:

- **`allow_fields: []` was fail-open.** `if spec.allow_fields:` treated an
  explicit empty allow-list the same as "no allow-list", exposing every
  field — the opposite of the spec's safe-default intent. Fixed to
  `is not None` checks throughout (`resolve_fields`, `load_view_specs`);
  `allow_fields: []` now means "expose nothing."
- **Multi-layer/table sources were unverified.** `create_stakeholder_view`
  only read/filtered/verified `source.layers[0]`; a source feature service
  with additional layers or tables would have those exposed through the
  view entirely unchecked — a silent leak the design's "never trust the
  create call, verify after" principle exists to prevent. Fixed: a
  `SEV_WARNING` (`view_unverified_layers`) fires when
  `len(source.layers) > 1` or `source.tables` is non-empty, naming the
  count so an operator knows to check manually. Not upgraded to a blocking
  ERROR — the common case (single-layer hosted feature layer) is
  unaffected, and blocking on an unverifiable unknown would be overly
  punitive for the majority case.
- **Unwrapped `gis` calls could abort a batch mid-loop.** `_find_item`'s
  `gis.content.search`, `source.layers[0].properties["fields"]` access, and
  `webmap.py`'s `item.get_data()` had no exception handling, unlike every
  other `gis`-touching call in both modules — a transient network/auth
  failure would raise instead of producing a clean QA ERROR, aborting
  `create-views`' whole view list on one bad lookup. Fixed: wrapped, each
  emitting a scoped `SEV_ERROR` (`view_source_missing` on search failure,
  `view_source_unreadable` on a malformed source item, `webmap_data_unreadable`
  on a get_data failure) instead of propagating.

### Pinned design decisions (specs left these open)

- CLI passes `FigureSpec.load(path).data` (plain dict) into `webmap.py`'s
  core function; core never imports `FigureSpec` itself.
- Definition-query placeholder rendering mirrors
  `layout_manager.apply_figure_definition_queries`'s `.format(**fmt)`
  convention exactly, including the same four placeholder names
  (`site_id`, `event_date`, `figure_spec_id`, `map_type`); `event_date` is
  not part of the canonical `FigureSpec`, so it's a new keyword-only
  parameter (core) / `--event-date` option (CLI), default `""`.
  Unrenderable templates (unknown placeholder) emit a `SEV_WARNING`
  (`defquery_render_failed`) and are skipped, not raised.
- Layer-title matching in `webmap.py` is case-insensitive
  (`.lower()`), matching `layout_manager.set_layer_visibility`'s
  convention. A spec-named layer absent from the web map is a
  `SEV_WARNING` (`webmap_layer_missing`), never created — same
  "no silent default" stance as ADR-0035's `cad_layer_map.py`.
- `update_webmap_from_spec` counts only **actually-changed** layers
  (compare-before-set on visibility and definitionExpression); zero changes
  skips the `item.update()` write entirely (`webmap_no_changes` INFO).
  `dry_run=True` still reads the current web map JSON (needed to compute
  the diff) but never calls `item.update()`.
- `hosted_views.ViewResult.exposed_fields`/`leaked_fields` are populated
  from a **post-write read-back** of the view's realized field
  visibility, not the intent sent to `update_definition` — the
  verification step this design explicitly requires ("never trust the
  create call").
- Created views are not shared/published (stay AGOL-default private) —
  `ViewSpec` has no share-level field and the design doesn't ask for one.
- No `CliRunner` tests added for either command — no existing precedent
  for CLI-level tests anywhere in the `agol` command group; core-module
  tests (27 across both modules) are the established convention.

## Consequences

### Positive

- Two more roadmap tools (6.3, 6.11) shippable without arcpy; 27 new
  tests, full suite 1297 passing.
- `hosted_views.py`'s sensitive-field-leak verification is a genuinely
  adversarial safety check (re-reads AGOL's realized state rather than
  trusting the request payload), now hardened against the three gaps
  above via independent model review before merge — a second AI reviewer
  (Fable, same model as the planner but a fresh context) catching issues
  the implementer's own tests didn't cover is the value of the two-role
  split this batch used.
- Established a reusable pattern (title-search + create-or-update,
  read-back verification) other AGOL item-publishing tools can follow.

### Negative

- `webmap.py` cannot apply popup, label, or symbology config despite the
  approved spec's Architecture section naming them — the canonical
  `FigureSpec` simply has no such fields today. If popup/label/symbology
  become part of `FigureSpec` later, `apply_spec_to_webmap_json` will need
  a follow-up extension.
- `view_unverified_layers` is a WARNING, not a blocking ERROR — a
  multi-layer/table source with sensitive data in a layer other than
  `layers[0]` is flagged but not prevented. Left as an operator-verify
  step rather than a hard block, given the common case is single-layer.

## Alternatives considered

- **Blocking ERROR instead of WARNING for multi-layer/table sources**:
  rejected — would make the tool unusable for the (common) case of a
  multi-layer service where only layer 0 is relevant, without the tool
  having any way to know that in advance.
- **`allow_fields: []` treated as "no restriction"** (the original,
  fail-open behavior): rejected after Fable's review — inverts the
  design's stated safety rationale.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0003: HarvestConfig canonical location](0003-harvest-config-canonical-location.md)
- [ADR-0035: CAD/Civil 3D handoff batch](0035-cad-civil3d-handoff-batch.md)
- `docs/superpowers/specs/2026-06-28-update-agol-webmap-from-figure-spec-design.md`
- `docs/superpowers/specs/2026-06-28-create-hosted-views-for-stakeholders-design.md`
