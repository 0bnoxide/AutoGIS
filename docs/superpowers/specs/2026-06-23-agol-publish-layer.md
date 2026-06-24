# AGOL Publish / Overwrite Feature Layer — Design

**Date:** 2026-06-23
**Status:** Approved
**Scope:** First cloud-push capability: publish a local feature class (FGDB or
in-memory FeatureSet) to AGOL as a hosted feature service, or overwrite an
existing one. Foundational for envmon roadmap §6.1
(`PublishEnvironmentalLayersToAGOL`) and §6.2 (`SyncAGOLFeatureLayerToGDB`).
**Repo integration source:** `docs/repo-integration-roadmap.md` — Tier 1A
(`arcgis` Python API, AGOL/portal overwrite surface).

---

## Purpose

The suite currently has no way to push processed data (normalized GDB tables,
callout layers, contours) to AGOL. Every envmon workflow that ends in a map or
dashboard is blocked until this exists. The arcgis Python API provides
`FeatureLayerManager.overwrite()` and `ContentManager.add()` + `.publish()`
as the two canonical publish paths. This plan implements a thin, testable
`publish_or_overwrite_layer` wrapper over those paths.

---

## Goals

1. `core/agol/publish.py` — `publish_or_overwrite_layer(gis, config, qa)`
   that idempotently creates or overwrites a hosted feature service.
2. Fully testable without a live AGOL session (injected `gis` mock).
3. Wired as `autogis agol publish-layer` CLI subcommand.
4. arcpy-free: works in the cloud/CI tier with arcgis only.
5. QA-emitting: all publish outcomes (created, overwritten, failed) produce
   `QARecord` entries.

## Non-Goals

- Multi-layer publish (one item per call for this pass).
- Spatial reference reprojection (caller's responsibility).
- Related-table publish — deferred to envmon roadmap §6 phase 2.
- Sync from AGOL back to GDB (`SyncAGOLFeatureLayerToGDB`) — separate plan.

---

## Architecture

```
autogis/
  core/agol/
    __init__.py          ← empty (package marker)
    publish.py           ← publish_or_overwrite_layer + PublishConfig
  adapters/cli.py        ← new @agol.command('publish-layer')
tests/
  test_agol_publish.py   ← injected mock GIS, no live AGOL
```

### `PublishConfig` (dataclass)

```python
@dataclass
class PublishConfig:
    title: str           # hosted service / item title
    tags: list[str]      # AGOL tags
    description: str = ""
    folder: str | None = None   # AGOL folder (None = root)
    share_with: str = "org"     # "private" | "org" | "everyone"
    overwrite: bool = True      # if item exists, overwrite; else create
```

### Publish flow

```
publish_or_overwrite_layer(gis, config, source_path, qa)
  ↓
search gis.content for title match
  ↓
found + config.overwrite=True?
  yes → FeatureLayerManager(existing_layer.url, gis).overwrite(source_path)
  no  → gis.content.add(item_properties, data=source_path).publish()
  ↓
QARecord(INFO | ERROR) → qa
```

`source_path` is a zip of an FGDB or a JSON FeatureSet file. The caller
(adapter or test) is responsible for producing it; `publish.py` does not
read arcpy or zip files itself.

---

## Constraints

- `publish_or_overwrite_layer` MUST NOT import `arcpy` or access the filesystem
  beyond reading `source_path` (which is already prepared by the caller).
- All arcgis calls inside `publish.py` are lazy (`import arcgis` inside the
  function body, behind `try/except`).
- Partial publish failures (service created but sharing failed) must be caught
  and emitted as `SEV_ERROR` QA records, not exceptions — the caller decides
  whether to abort.
