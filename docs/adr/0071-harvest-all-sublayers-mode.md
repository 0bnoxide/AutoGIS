# ADR-0071: `all_sublayers` — harvest every attachment-bearing layer/table of an item in one run

**Status:** Accepted

**Date:** 2026-07-08

## Context

A harvest job config targets exactly one sublayer (`url` or `item_id` +
`layer_index`). Items with several attachment-bearing layers/tables (a
common AGOL survey pattern — one feature layer plus one or more related
photo tables) need one config file and one run per sublayer today, each with
its own output directory to avoid manifest collisions.

## Decision

Add **`all_sublayers: bool = False`** to `HarvestConfig`. When set,
`resolve_all_layers()` (`core/harvest/harvester.py`) returns every
attachment-bearing sublayer of the item (`item.layers` + `item.tables`
combined, same precedent as `resolve_layer`/ADR-0066), and `harvest()` runs
each through the existing per-feature download loop, rooting each
sublayer's output under `directory/<sanitized name>_<sublayer id>/` instead
of `directory/` directly — the same collision the multi-run workaround above
avoids, but from one config and one run.

Mutually exclusive with `url` (targets exactly one sublayer already) and
`layer_index` (picks one specific sublayer id) and `incremental`
(last-run state is tracked per output directory; one shared directory would
conflate "last run" across unrelated sublayers). `HarvestConfig.load`
enforces all three at load time — the single validation source, per the
existing convention (ADR-0065's Site Config Builder round-trips through it
rather than re-deriving rules).

GUI: the Site Config Builder dialog (ADR-0065) gets a "Harvest every
layer/table in this item" checkbox. Checking it disables the URL field, the
fetched-sublayer picker, and Incremental (clearing the latter) so the form
can't be filled into a combination that only fails at Save time.

## Consequences

### Positive consequences

- One config + one run covers a whole item's attachment-bearing sublayers
  instead of N hand-maintained configs/output directories.
- Every downloaded/skipped/failed manifest row now carries `source_table`
  (the resolved sublayer's own name) even in the existing single-sublayer
  path — previously always `None` — since `harvest()` now names the sublayer
  once for both modes rather than only in the new branch.

### Negative consequences

- A second directory-nesting convention (single-sublayer: flat; all-sublayers:
  one subfolder per sublayer) for callers reading `manifest.csv`/`.json` to
  reason about.

Cold review caught two gaps in the first pass, both fixed before merge:

- **Sanitized-name folder collisions.** Two sublayers whose names sanitize
  to the same string (`sanitize()` only strips illegal filesystem chars, so
  e.g. `"Photos/A"` and `"PhotosA"` both become `"PhotosA"`) would have
  landed in the same subfolder, reintroducing the exact OBJECTID collision
  this feature exists to prevent. Fixed: the subfolder name is always
  `sanitize(name) + "_" + sublayer_id` — REST sublayer ids are unique per
  item, so this is a hard guarantee, not a best-effort one.
- **Lost manifest state on a mid-batch sublayer failure.** A fatal error
  resolving/querying one sublayer (bad `where` for its schema, a transient
  network error) used to propagate and abort the whole run before
  `manifest.write()` ever ran, discarding already-completed sublayers'
  results. Fixed: in all-sublayers mode only, a per-sublayer exception is
  caught and recorded as a `failed` manifest row (naming the sublayer, no
  `objectid`/`attachment_id`) instead of raised — the same "never kill the
  run" resilience `_harvest_layer` already applies one level down, extended
  to the sublayer level. Single-sublayer mode keeps its pre-existing
  behavior of propagating the exception.

## Alternatives considered

- **Multiple layer_index configs run in sequence (status quo)** — rejected
  as the thing this ADR replaces; still available for one specific sublayer.
- **Match sublayers by name instead of harvesting all** — rejected as
  YAGNI; "every attachment-bearing sublayer" is the actual reported need.

## Related decisions

- ADR-0066 — the combined layers+tables id-matching precedent this reuses.
- ADR-0065 — the Site Config Builder dialog this adds a checkbox to.
