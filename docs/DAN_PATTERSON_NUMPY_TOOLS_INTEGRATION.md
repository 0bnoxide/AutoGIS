# Dan Patterson Numpy Tools Integration Plan

**Date:** 2026-06-25  
**License:** Free use (confirmed via direct contact with Dan Patterson)  
**Status:** ✅ COMPLETE — vendored to `autogis/core/common/npg/`; public API at `autogis/core/common/numpy_geom.py`

---

## Permission Confirmation

**Author:** Dan Patterson <dan_patterson@carleton.ca>  
**License Terms:** Free use  
**Date Confirmed:** 2026-06-25  
**Source Repos:**
- `https://github.com/Dan-Patterson/Tools_for_ArcGIS_Pro`
- `https://github.com/Dan-Patterson/numpy_geometry`

---

## Attribution Block (Ready to Use)

```python
# Portions derived from Dan Patterson / numpy_geometry
# Source: https://github.com/Dan-Patterson/numpy_geometry
# Author: Dan Patterson <dan_patterson@carleton.ca>
# License: Free use (confirmed 2026-06-25)
# Adapted for AutoGIS: numpy computation cores extracted; arcpy I/O isolated at module boundary
```

---

## Vendored Algorithms (5 Functions)

All from prior recon inventory. Pure numpy cores identified; arcpy dependencies flagged and excluded.

### 1. Coordinate Rotation
**Function:** `_trans_rot_2(a, angle)`  
**Source:** `numpy_geometry/npg/npg_maths.py`  
**Use Case:** Callout coordinate rotation (OptimizeCalloutPlacement optimization)

**Input:**
- `a`: numpy array of (x, y) coordinates
- `angle`: rotation angle in degrees

**Output:**
- Rotated (x', y') array

**Why:** Replace current callout placement logic with numpy-based rotation for better performance on large datasets.

**Phase:** 3 (Map Production Optimization)

---

### 2. Convex Hull / Bounding Box
**Function:** `_ch_simple()` / convex hull implementation  
**Source:** `numpy_geometry/npg/npg_geom_ops.py`  
**Use Case:** Callout cluster bounding-box for collision detection

**Input:**
- numpy array of (x, y) points in cluster

**Output:**
- Convex hull or bounding box vertices

**Why:** Pure numpy convex hull is faster than scipy.spatial.ConvexHull for repeated small clusters.

**Phase:** 3 (Map Production Optimization)

---

### 3. Nearest-Neighbor Query
**Function:** `n_near(a, N, ordered)`  
**Source:** `numpy_geometry/npg/npg_analysis.py`  
**Use Case:** Spatial join for RPD duplicate sample location matching (normalize_rpd.py enhancement)

**Input:**
- `a`: array of sample coordinates
- `N`: number of nearest neighbors to return
- `ordered`: whether to return ordered by distance

**Output:**
- Indices and distances of N nearest neighbors per point

**Why:** Replace current location-matching logic with numpy nearest-neighbor for deterministic, fast duplicate detection.

**Phase:** 2 (Data Reliability — RPD Evaluation enhancement)

---

### 4. Polyline Simplification
**Function:** `simplify(a, tol)`  
**Source:** `numpy_geometry/npg/npg_geom_ops.py`  
**Use Case:** Polyline generalization for groundwater contours (GenerateDraftGWContours refinement)

**Input:**
- `a`: array of (x, y) vertices
- `tol`: simplification tolerance (distance units)

**Output:**
- Simplified polyline vertices (subset of input)

**Why:** Pure numpy simplification is faster than ArcGIS simplification; also keeps output arcpy-free until final export.

**Phase:** 4-5 (Advanced geostatistical modeling — contour refinement)

---

### 5. Point Densification
**Function:** `_densify_2D(a, fact)`  
**Source:** `Tools_for_ArcGIS_Pro/PolygonLineTools/Scripts/densify_geom.py`  
**Use Case:** Contour point densification for smoother visual representation

**Input:**
- `a`: array of (x, y) vertices
- `fact`: densification factor (e.g., 2 = double the points)

**Output:**
- Densified polyline vertices

**Why:** Improves contour visual quality without increasing data size; pure numpy implementation.

**Phase:** 4-5 (Advanced geostatistical modeling — contour refinement)

---

## Hard Warnings (DO NOT COPY)

**These functions create arcpy.Point / Polygon / Polyline objects and require Standard+ license:**
- `closest.connect()`
- `densify_geom.arcpnts_poly()`
- `npg_arc_npg.Geo_to_arc_shapes()`

**Approach:** Extract only the numpy computation core. Replace arcpy object creation with numpy arrays. Convert to arcpy only at final GDB write boundary (where arcpy license is already required).

---

## Integration by Phase

### Phase 2 (Data Reliability)
**RPD Duplicate Matching Enhancement**

- **Tool:** EvaluateDuplicateRPD (3.6 — existing in original roadmap)
- **Enhancement:** Add numpy `n_near()` for deterministic nearest-neighbor location matching
- **Integration Point:** `normalize_rpd.py` (spatial join logic)
- **Timeline:** +1 week to existing EvaluateDuplicateRPD schedule
- **Test Case:** H281 RPD samples with location name variations (MW-1 vs MW-01); nearest-neighbor matches parent/duplicate spatially instead of name-based

---

### Phase 3 (Map Production Optimization)
**Callout Placement Optimization + Geometry Operations**

- **Tool 1:** OptimizeCalloutPlacement (5.2 — existing)
  - **Enhancement:** Add numpy `_trans_rot_2()` for fast callout rotation
  - **Enhancement:** Add numpy `_ch_simple()` for convex hull collision detection
  - **Integration Point:** Callout placement iteration logic
  - **Timeline:** +1-2 weeks to existing OptimizeCalloutPlacement schedule
  - **Test Case:** Site with 20 callouts; optimize placement with rotation + collision detection

---

### Phase 4-5 (Advanced Geostatistical Modeling)
**Contour Refinement + Polyline Operations**

- **Tools:** RunFieldToGroundwaterModelPipeline (conditional), BuildGroundwaterSurfaceModel (conditional)
- **Enhancement 1:** Add numpy `simplify()` for contour line generalization
  - **Use Case:** Interpolated raster contours → simplified polylines → GDB/AGOL export
  - **Timeline:** When RunFieldToGroundwaterModelPipeline conditional tool is approved for build
  - **Test Case:** TIN-generated contours with 1000+ vertices; simplify to 200 vertices at 1 ft tolerance
  
- **Enhancement 2:** Add numpy `_densify_2D()` for contour visual smoothing
  - **Use Case:** Draft contours → densified for map presentation → final contours
  - **Timeline:** After RunFieldToGroundwaterModelPipeline Phase 1 (TIN/IDW) complete
  - **Test Case:** Draft contours with 50 ft vertex spacing; densify to 10 ft spacing for smoother appearance

---

## Architecture: Keep Numpy Core Portable

**Pattern:**
```
Input (arcpy geometry or GeoDataFrame)
    ↓
[Convert to numpy array]
    ↓
{Pure numpy computation — DAN PATTERSON CODE}
    ↓
[Convert back to GIS format]
    ↓
Output (arcpy geometry or GeoDataFrame)
```

**Benefit:** All numpy operations are license-agnostic and portable. Only the I/O boundaries (input conversion, output creation) require arcpy.

**Example module structure:**
```python
# autogis/core/common/numpy_geom.py  (shipped — see actual file for try/except fallbacks)

from autogis.core.common.npg import npg_maths, npg_geom_ops, npg_analysis

def rotate_points(xy_array, angle_degrees): ...
def convex_hull(xy_array): ...
def nearest_neighbors(xy_array, k=1): ...
def simplify_polyline(xy_array, tolerance): ...
def densify_polyline(xy_array, factor): ...
```

---

## Vendoring Steps

### Step 1: Extract Source Files (Week 1)
1. Clone `numpy_geometry` repo
2. Copy `/npg` module (keep directory structure)
3. Copy specific functions from `Tools_for_ArcGIS_Pro`:
   - `npg_maths._trans_rot_2()`
   - `npg_geom_ops._ch_simple()`
   - `npg_geom_ops.simplify()`
   - `npg_geom_ops._densify_2D()`
   - `npg_analysis.n_near()`
4. Location: `autogis/core/common/vendor/numpy_geometry/`
5. Add attribution headers to all files

### Step 2: Wrapper Module (Week 1)
1. Create `autogis/core/common/numpy_geom.py`
2. Wrap 5 functions (arcpy-free interface)
3. Document usage + caveats
4. Add unit tests (numpy arrays only, no arcpy dependency)

### Step 3: Integration Points (Weeks 2-3)
1. **EvaluateDuplicateRPD** (Phase 2) — integrate `n_near()` for RPD location matching
2. **OptimizeCalloutPlacement** (Phase 3) — integrate `_trans_rot_2()` + `_ch_simple()`
3. **BuildGroundwaterSurfaceModel** (Phase 4-5) — integrate `simplify()` + `_densify_2D()`

### Step 4: Testing (Week 3)
1. Unit tests for wrapper module (numpy arrays)
2. Integration tests (end-to-end with arcpy I/O at boundaries)
3. Regression tests (existing OptimizeCalloutPlacement, EvaluateDuplicateRPD output unchanged)

### Step 5: Documentation (Week 3)
1. Update CONTRIBUTING.md with vendor policy
2. Add LICENSE reference to README
3. Document performance improvements in release notes

---

## Updated Implementation Roadmap Impact

### Phase 2 (Data Reliability)
- EvaluateDuplicateRPD: +1 week for numpy integration
- **New baseline:** 21 weeks (was 20)

### Phase 3 (Map Production)
- OptimizeCalloutPlacement: +1-2 weeks for numpy integration
- **New baseline:** 15-16 weeks (was 14)

### Phase 4-5 (Geostatistical Modeling)
- RunFieldToGroundwaterModelPipeline (conditional): +1-2 weeks for contour refinement
- BuildGroundwaterSurfaceModel (conditional): +1-2 weeks for contour refinement
- **Impact:** Deferred until conditional tools approved; adds 2-4 weeks when built

**Overall timeline impact:** +2-3 weeks across Phases 2-3; minimal impact if conditional tools deferred.

---

## File Structure (Vendored Code)

```
autogis/
  core/
    common/
      npg/                        [Absorbed from Dan Patterson — modified in place]
        __init__.py
        npg_maths.py              [Contains _trans_rot_2()]
        npg_geom_ops.py           [Contains simplify(), _ch_simple(), _densify_2D()]
        npg_analysis.py           [Contains n_near()]
      numpy_geom.py               [AutoGIS public API — arcpy-free, try/except fallbacks]
tests/
  core/
    common/
      test_numpy_geom.py          [Unit tests for numpy_geom.py]
```

---

## Commit Message Template

```
feat(vendor): integrate Dan Patterson numpy_geometry tools

Pull in 5 pure-numpy algorithms from Dan Patterson's numpy_geometry repo:
- _trans_rot_2(): coordinate rotation (callout placement)
- _ch_simple(): convex hull (collision detection)
- n_near(): nearest-neighbor (RPD location matching)
- simplify(): polyline simplification (contour refinement)
- _densify_2D(): point densification (contour smoothing)

Wrapper module (numpy_geom.py) provides arcpy-free interface;
all I/O conversion happens at module boundaries only.

Attribution: Dan Patterson <dan_patterson@carleton.ca>
License: Free use (confirmed 2026-06-25)
Source: https://github.com/Dan-Patterson/numpy_geometry

Vendored code location: autogis/core/common/vendor/numpy_geometry/

Fixes: #XXX (Phase 2/3 performance improvements)
```

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| License dispute later | Direct email confirmation on file; attribution block in code + docs |
| Code changes upstream | Vendor copy is frozen; flag upstream changes as breaking if we need them later |
| arcpy dependency creep | Wrapper enforces numpy-only interface; arcpy-dependent functions explicitly excluded |
| Performance regression | Regression tests verify existing tool outputs unchanged; new numpy paths tested separately |
| Integration complexity | Phase-staged integration (start Phase 2, defer Phase 4-5 until conditional tools approved) |

---

## Next Steps

1. **Confirm scope** — are all 5 algorithms correct for your roadmap priorities?
2. **Assign owner** — who will handle vendoring + wrapper module?
3. **Schedule** — insert into Phase 2/3 schedules, or defer to conditional-tool phase?
4. **Create issue** — link this document to a GitHub issue for tracking

Once scope is confirmed, proceed directly to **Step 1: Extract Source Files**.
