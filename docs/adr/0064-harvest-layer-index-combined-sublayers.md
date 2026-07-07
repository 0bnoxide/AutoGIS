# ADR-0064: `HarvestConfig.layer_index` — select a sublayer from the combined layers+tables list

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
key. `resolve_layer()` indexes
`list(item.layers or []) + list(item.tables or [])` — the same combined-list
precedent as `core/agol/dashboard_refresh.py`.

- **Numbering is the COMBINED layers-then-tables list**, matching AGOL's
  continuous portal `?sublayer=N` / REST sublayer numbering — NOT the arcgis
  Python API's separate `.layers[]`/`.tables[]` arrays. Documented on the
  field, the loader, and the resolver.
- Out-of-range (including negative) indexes raise `ConfigError` with the
  item id and sublayer count instead of leaking `IndexError` (or silently
  wrapping via negative indexing).
- Default `0` = first entry of the combined list; existing configs keep
  today's behavior unchanged (`layers[0]` when any layer exists).
- **No CLI flag** (YAGNI): the override whitelist stays `where`/`out`/
  `incremental`; `layer_index` is config-file-only.
- Arcpy-free invariant untouched: the change adds no `arcgis` imports.

## Consequences

### Positive consequences

- Tables and non-first layers with attachments are now harvestable per job
  config; misconfiguration fails loudly at resolve time.

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
