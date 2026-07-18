# BuildCADExportPackage Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildCADExportPackage (Tool 8.9)
**Priority:** MEDIUM — Civil 3D-ready DWG/DXF exports for the survey/engineering handoff
**Runtime:** LOCAL (arcpy) — routes through the `.pyt` toolbox (ADR-0006)

**Implementation note (2026-07-17):** ADR-0089 applies the configured CAD
layer name, color, and linetype to scratch feature-class copies before
`ExportCAD`; source feature classes remain unchanged.

---

## Problem

Civil engineers want site base maps, excavation extents, well locations, contours, and
plume boundaries as DWG/DXF with a sane layer structure. ArcGIS's Export-to-CAD produces
files, but mapping GIS layers to CAD layers, choosing the coordinate system, and recording
the projection note is manual and inconsistent per handoff.

---

## Approach

**Chosen:** arcpy-bound CAD exporter on the Tools 2–8 pattern. The Export-to-CAD call and
DWG/DXF write are arcpy in the `.pyt` toolbox. The **layer-mapping resolution** (GIS layer
→ CAD layer name/color/linetype from a mapping config, plus the validation that every
selected layer has a mapping and the CRS is set) is pure and lives in an arcpy-free core
helper, fully tested without Pro. The tool also writes a layer-mapping report and a
projection note alongside the CAD output.

ADR-0002 keeps core arcpy-free; ADR-0006 keeps the `.pyt` toolbox as the UI; the CLI
guards-and-redirects.

**Rejected: `ezdxf` headless DXF authoring.** Would add a dependency and re-implement what
Export-to-CAD already does correctly for Pro users; the value here is the mapping/validation
discipline, which is extracted to core.

**Rejected: silent default layer mapping.** A selected layer with no mapping entry is a QA
ERROR — unmapped geometry in a CAD handoff is a defect, not a default.

---

## Architecture

```
autogis/
  core/envmon/
    cad_layer_map.py          ← NEW (arcpy-free: mapping resolution + validation)
  adapters/
    toolbox.pyt               ← add BuildCADExportPackage tool class (arcpy export)
    cli.py                    ← add build-cad-package command: _guard + redirect
  runtime/
    capabilities.py           ← register "build-cad-package" (requires arcpy)
tests/envmon/
  test_cad_layer_map.py       ← NEW (arcpy-free)
  test_cli_guards.py          ← extend: build-cad-package guard fires headless
```

---

## Public API

Arcpy-free core (`cad_layer_map.py`):

```python
@dataclass
class CADLayerMapping:
    gis_layer: str
    cad_layer: str
    color: int | None
    linetype: str | None

@dataclass
class CADExportPlan:
    mappings: list[CADLayerMapping]
    crs: str
    unmapped: list[str]       # selected layers with no mapping -> blocking
    qa: QACollector

def resolve_cad_plan(
    selected_layers: list[str],
    mapping_config: dict,
    *,
    crs: str,
) -> CADExportPlan:
    """Resolve GIS->CAD layer mappings; flag unmapped layers and a missing CRS."""
```

CLI: `_guard("build-cad-package")` then a `ClickException` directing to the `.pyt` toolbox.

---

## CLI Command

```
autogis envmon build-cad-package --layers <layers.txt> --mapping <cad_map.yaml> --crs EPSG:2256
# headless: clean guard error -> use the .pyt toolbox tool inside ArcGIS Pro
```

---

## Test Strategy

Arcpy-free:

1. `resolve_cad_plan` maps each selected layer to its CAD layer per config.
2. A selected layer with no mapping → `unmapped` non-empty, blocking ERROR.
3. Color/linetype pass through from the mapping config.
4. Missing CRS → QA ERROR.
5. Layer present in config but not selected is ignored.
6. `build-cad-package` CLI raises a clean guard error when arcpy is absent.
