# GitHub Resource Value Map — Lazy-arcpy Python Framework

**Context:** Target framework is Python-based with **lazy arcpy** (deferred import; stays light and importable outside a full Pro/license context).

**Compatibility filter used:** Keep only resources that (a) don't need arcpy, or (b) confine arcpy to a thin I/O edge. Anything assuming a fat, eager environment is dropped. Under this filter the original 9-repo list collapses to **3 that matter**.

---

## Tier 1 — Direct value, fits lazy-arcpy cleanly

### 1. `arcgis` (Esri/arcgis-python-api) — the AGOL/Portal backbone
- **URL:** https://github.com/Esri/arcgis-python-api  •  **License:** Apache-2.0  •  **Active**
- **What it offers your project:** connect to AGOL/Portal, publish & **overwrite hosted feature services**, query/edit features, manage items/users/groups, edit web maps — the whole web-GIS automation surface.
- **Why it's compatible:** REST-based, **does not import arcpy**. Runs even outside ArcGIS Pro. It is, however, a *heavy* package (pulls pandas/shapely/etc.).
- **How to use it:** as a **declared dependency**, lazy-imported the same way you defer arcpy — pay the import cost only when an AGOL tool actually runs. Pin the version to your Pro conda env (see Tier 2). Do **not** vendor source.

### 2. Dan-Patterson/Tools_for_ArcGIS_Pro — numpy-first patterns
- **URL:** https://github.com/Dan-Patterson/Tools_for_ArcGIS_Pro  •  **License:** ⚠️ verify before copying  •  Maintained
- **What it offers your project:** numpy implementations of operations normally gated behind Standard/Advanced licenses; reusable geometry/table tools.
- **Why it's compatible:** algorithms live in **numpy**; only `arcpy.da` cursors touch the data. This is the lazy-arcpy ideal — minimal arcpy surface.
- **How to use it:** **selective vendor + pattern reference.** Discipline to preserve: keep the numpy core portable, isolate every `arcpy.da` call so it's the only Pro-bound edge. (Active geometry work is in the author's `numpy_geometry` repo if you want the source of truth.)

---

## Tier 2 — Near-zero-cost reference, not integration

### 3. Esri/arcpy — version map + debug tooling
- **URL:** https://github.com/Esri/arcpy  •  **License:** Apache-2.0  •  Active
- **What it offers:** `docs/arcgis-dist.json` (which package versions ship with which Pro release — use it to pin `arcgis`/deps to your env) and a debugpy "attach to Pro" guide. Not ArcPy source; nothing to import.

---

## Dropped under the compatibility filter

| Repo | Reason |
|------|--------|
| Esri/arcgis-pro-sdk-community-samples | C#/.NET — wrong language & runtime for a Python framework. |
| Esri/ago-assistant | JavaScript web app. Every capability is reproducible via the `arcgis` library. |
| Esri/arcgis-admin-python-scripts | Dead (beta-API era); superseded by `arcgis`. |
| Esri/solutions-geoprocessing-toolbox | Archived (2018, Pro 2.0). |
| ianhorn/...Overwrite-Hosted-Services | Does not resolve. Native `arcgis`/arcpy overwrite covers it. |
| korporalK/Archer-GIS-AI-Assitant | Separate agentic paradigm + Gemini dependency + no clear license. Study the pattern; don't integrate. |

---

## Claude Code hand-off — the short version

1. Add **`arcgis`** as a pinned, **lazy-imported** dependency (mirror the existing lazy-arcpy pattern). Never vendor it.
2. Borrow **numpy-first patterns** from Tools_for_ArcGIS_Pro **only after** confirming its license; keep numpy core portable, isolate `arcpy.da` at the edge; preserve attribution.
3. Use `arcgis-dist.json` from the Esri/arcpy repo to pin versions to the Pro conda env.
4. Ignore the dropped repos — do not clone or import them.
