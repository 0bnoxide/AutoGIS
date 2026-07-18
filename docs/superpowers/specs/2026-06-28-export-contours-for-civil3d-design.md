# ExportContoursForCivil3D Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** ExportContoursForCivil3D (Roadmap §8, "Create Civil 3D Contour/Surface Support Files")
**Priority:** LOW — Civil 3D surface-input handoff; narrower than BuildCADExportPackage (8.9)
**Runtime:** CLI ✓ (point CSV + metadata, headless) / LOCAL (LandXML/DWG via `.pyt`)

**Implementation note (2026-07-17):** ADR-0088 made point-only CgPoints
LandXML headless. ADR-0089 completes the LOCAL path by exporting an existing
ArcGIS Pro TIN as a named LandXML surface; Civil 3D derives contours from that
surface, so no separate contour-polyline artifact is emitted.

---

## Relationship to BuildCADExportPackage (8.9)

`BuildCADExportPackage` is the general GIS→CAD layer exporter. **This tool is the
surface-specific sibling:** it exports draft groundwater contours and the underlying
elevation points as *Civil 3D surface inputs* (point CSV for a TIN, contour polylines,
optional LandXML), not a full layered base map. They are kept distinct because the outputs
and consumers differ (a Civil 3D surface vs. a CAD drawing); shared concerns (CRS handling,
projection note) reuse `cad_layer_map`'s validation.

---

## Problem

Civil designers build surfaces from point data and contour breaklines. Handing them a
PDF or a styled DWG forces re-digitizing. They need the raw points (PNEZD CSV) and contour
polylines in a coordinate system they can import, with a projection note — not a finished
map.

---

## Approach

**Chosen:** Split by dependency. The **PNEZD point CSV** (point number, northing, easting,
elevation, description) and the metadata/projection note are pure-stdlib and emitted by an
arcpy-free core function — fully headless and testable. The **contour polylines and optional
LandXML/TIN** export is arcpy (or a Civil-3D-aware exporter) and routes through the `.pyt`
toolbox. The CLI emits the CSV + metadata headless and guards-and-redirects for the
polyline/LandXML step.

**Rejected: folding into BuildCADExportPackage.** Different deliverable (surface inputs vs.
layered drawing) and different headless surface (PNEZD CSV is fully headless here). Folding
would bloat 8.9's mapping model with surface concerns.

**Rejected: a LandXML writer in core.** LandXML/TIN authoring is niche; gate it behind the
arcpy/Civil path and ship the universally-importable PNEZD CSV headless first. (ponytail:
CSV now, LandXML when a designer actually needs the pre-built TIN.)

---

## Architecture

```
autogis/
  core/envmon/
    civil3d_points.py         ← NEW (arcpy-free: PNEZD CSV + metadata)
    cad_layer_map.py          ← EXISTS after 8.9 (CRS/projection-note reuse)
  adapters/
    toolbox.pyt               ← add ExportContoursForCivil3D tool (polyline/LandXML)
    cli.py                    ← add export-civil3d command (CSV headless; LandXML guarded)
  runtime/
    capabilities.py           ← register "export-civil3d" (LandXML path requires arcpy)
tests/envmon/
  test_civil3d_points.py      ← NEW (arcpy-free)
```

---

## Public API

Arcpy-free core (`civil3d_points.py`):

```python
@dataclass
class PNEZDPoint:
    point_number: int
    northing: float
    easting: float
    elevation: float
    description: str

def build_pnezd(
    points: list[dict],
    *,
    crs: str,
    start_number: int = 1,
) -> list[PNEZDPoint]:
    """Build sequential PNEZD points from elevation records."""

def write_pnezd_csv(points: list[PNEZDPoint], out_path: Path) -> Path: ...
def write_projection_note(crs: str, out_path: Path) -> Path: ...
```

---

## CLI Command

```
autogis envmon export-civil3d \
  --points <gwe_points.csv> \
  --crs EPSG:2256 \
  --out-dir <civil3d/> \
  [--landxml]            # arcpy path: clean guard error when arcpy absent
```

---

## Test Strategy

`tests/envmon/test_civil3d_points.py` — arcpy-free:

1. `build_pnezd` numbers points sequentially from `start_number`.
2. Northing/easting/elevation map from the source records.
3. `write_pnezd_csv` emits a header + one row per point in PNEZD order.
4. `write_projection_note` records the CRS.
5. A point missing elevation → skipped + WARNING.
6. `--landxml` raises a clean guard error when arcpy is absent.
