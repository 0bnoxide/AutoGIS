# ADR-0066: `HarvestConfig.layer_index` — select a sublayer from the combined layers+tables list

**Status:** Accepted

**Date:** 2026-07-06

## Context

`resolve_layer()` (`core/harvest/harvester.py`) hardcoded `item.layers[0]`
whenever a harvest job config used `item_id` instead of a direct `url`. Any
AGOL item with more than one layer/table silently harvested attachments from
the wrong sublayer — confirmed live 2026-07-06 against item
`bb3c27a3ddcf43aeb4e0fb08db3e32c6` (6 sublayers; the wanted one,
`Daily_Diary_Photos`, is sublayer 5 — a *table* — but only `layers[0]`,
`Daily_Diary`, was ever reachable). Wrong data, no error.

## Decision

Add **`layer_index: int = 0`** to `HarvestConfig` (canonical home
`core/common/config.py`), parsed from the optional `layer.layer_index` YAML
key. `resolve_layer()` builds `list(item.layers or []) + list(item.tables or
[])` — the same combined-list precedent as `core/agol/dashboard_refresh.py`
— then **matches by each sublayer's own `.properties.id`**, not by treating
`layer_index` as a raw position in that concatenated list.

- **`layer_index` is AGOL's REST/portal sublayer id** (the continuous
  `?sublayer=N` numbering across layers+tables combined) — NOT a position in
  the arcgis Python API's separate `.layers[]`/`.tables[]` arrays, and (cold
  review caught this) also not assumed to equal its position in the
  concatenated list: the API gives no guarantee those arrays are returned
  sorted by id or laid out layers-then-tables internally, so positional
  indexing could silently resolve the wrong sublayer on a service with
  gappy/interleaved ids — the exact class of bug this ADR exists to fix, just
  narrower. Matching on `.properties.id` is correct regardless of array
  order.
- No match for the requested id raises `ConfigError` naming the item id and
  the sorted list of ids that *do* exist, instead of leaking `IndexError` or
  silently resolving the wrong sublayer.
- Default `0` = whichever sublayer carries id `0` (normally the first layer);
  existing configs keep today's behavior unchanged for the common case where
  layer 0 exists and is at REST id 0.
- **No CLI flag** (YAGNI): the override whitelist stays `where`/`out`/
  `incremental`; `layer_index` is config-file-only.
- Arcpy-free invariant untouched: the change adds no `arcgis` imports.

## Consequences

### Positive consequences

- Tables and non-first layers with attachments are now harvestable per job
  config; misconfiguration fails loudly at resolve time.

**2026-07-08 update:** the three sibling `layer_index` call sites named above
in "Alternatives considered" (`sync_layer.fetch_layer_edits`,
`audit_schema.fetch_layer_schema`, `promote._copy_layer_data`) still did
positional `item.layers[layer_index]` indexing. Extended the same id-matching
fix to all three via a shared `core/agol/_sublayers.resolve_sublayer()`
helper — this ADR's decision now covers all four `layer_index` consumers,
not just the harvester.

### Negative consequences

- One more knob whose combined-list semantics differ from the arcgis API's
  arrays — mitigated by the comments at every touchpoint.

## Alternatives considered

- **Separate `layer_index`/`table_index` keys mirroring the API arrays** —
  rejected: users read sublayer ids off the AGOL item page URL, which uses
  the combined numbering.
- **Match by sublayer name** — rejected as YAGNI; index matches the three
  existing `layer_index` precedents (`sync_layer`, `audit_schema`,
  `promote`).

## Related decisions

- `core/agol/dashboard_refresh.py` combined-list resolution (PR #120 era) —
  the precedent this follows.
