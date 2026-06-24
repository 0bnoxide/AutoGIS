# arcgis Session Consolidation + Version Pin — Design

**Date:** 2026-06-23
**Status:** Approved
**Scope:** Retire the legacy `core/harvest/gis_session.py` wrapper (pre-merge
artifact); consolidate on `runtime/sessions.py`; pin the `arcgis` cloud extra
to the ArcGIS Pro 3.5.x compatible range.
**Repo integration source:** `docs/repo-integration-roadmap.md` — Tier 1A
(`arcgis` as pinned, lazy-imported dependency) + Tier 2 (Esri/arcpy
`arcgis-dist.json` for version pinning).

---

## Purpose

`docs/repo-integration-roadmap.md` mandates two things for the `arcgis` package:

1. Declare it as a **pinned, lazy-imported** `cloud` extra — *not* imported at
   module load time.
2. **Pin the version** to the range that ships with the target ArcGIS Pro
   conda environment (Pro 3.5.2 per `MERGE_PLAN.md`), using
   `Esri/arcpy:docs/arcgis-dist.json` as the canonical version map.

Currently, `pyproject.toml` declares `cloud = ["arcgis"]` (unpinned) and two
session builders exist side-by-side:

| Module | Style | Used by |
|---|---|---|
| `autogis/core/harvest/gis_session.py` | Module-level `try/except` + `GIS = None` | `autogis.core.__init__`, tests |
| `autogis/runtime/sessions.py` | Fully lazy (`from arcgis.gis import GIS` inside fn) | CLI adapter |

`cli.py` already migrated to `runtime/sessions.py`. `gis_session.py` is
a legacy artifact that still lives in `core/__init__.py`'s re-export list.
This plan removes the duplication and completes the Tier 1A requirement.

---

## Goals

1. One canonical GIS session builder: `runtime/sessions.py:agol_from_profile`.
2. `gis_session.py` → thin re-export shim (back-compat for existing test imports).
3. `pyproject.toml` cloud extra has a concrete version pin from `arcgis-dist.json`.
4. All 127 tests stay green.

## Non-Goals

- Building any new AGOL feature (publishing, sync, etc.) — that is
  `2026-06-23-agol-publish-layer`.
- Changing the lazy-import pattern in `harvester.py` or `sessions.py` (both
  already correct).

---

## Architecture

```
autogis/
  core/harvest/gis_session.py   ← thin shim: re-exports from runtime/sessions
  runtime/sessions.py           ← canonical (unchanged)
pyproject.toml                  ← arcgis pin added to [cloud]
```

The shim keeps `from autogis.core import gis_session` + `.build_gis(...)` working
so the existing test suite needs no changes. The internal canonical import is
`from autogis.runtime.sessions import agol_from_profile`.

---

## Version pin rationale

ArcGIS Pro 3.x ships one minor `arcgis` Python API version per Pro minor
(confirmed in `Esri/arcpy:docs/arcgis-dist.json`). Pro 3.5.x ships
`arcgis 2.4.x`. The pin `arcgis>=2.4,<3` allows any 2.4.x bugfix while
blocking incompatible major/minor upgrades. This is the pinning strategy
recommended in `repo-integration-roadmap.md` § Tier 2.

> **Verify before commit:** fetch the dist.json via the GitHub MCP tool and
> confirm the exact 2.x version for Pro 3.5.x. If it is not 2.4, update the
> pin accordingly.
