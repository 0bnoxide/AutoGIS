# numpy-geometry Recon Deltas

**Date:** 2026-06-23
**Source plan:** docs/superpowers/plans/2026-06-23-numpy-geo-recon.md

---

## Verdict table

| Agent | Claim | Verdict | Delta |
|---|---|---|---|
| N1 | Tools_for_ArcGIS_Pro has top-level LICENSE file? | confirmed | not found |
| N1 | numpy_geometry has top-level LICENSE file? | confirmed | not found |
| N1 | Individual Python files carry license headers? | confirmed | no headers found |
| N1 | Vendor copy permitted under found license? | needs-human | no license → default copyright applies |
| N2 | Coordinate rotation / affine transform (numpy)? | confirmed | npg_maths._trans_rot_2(), rotatepnts.trans_rot() |
| N2 | Convex hull / bounding-box (numpy)? | confirmed | npg_geom_ops._ch_scipy_(), _ch_simple_() |
| N2 | Nearest-neighbor / spatial-join (numpy)? | confirmed | npg_analysis.n_near(), closest_n() |
| N2 | Contour smoothing / polyline generalization (numpy)? | confirmed | npg_geom_ops.simplify(), densify_geom._densify_2D() |
| N2 | Functions stay pure numpy / arcpy.da only? | needs-human | mixed — output stage creates arcpy geometry objects in several functions |

---

## License classification

**Tools_for_ArcGIS_Pro:** No LICENSE file present. No SPDX identifier.
**numpy_geometry:** No LICENSE file present. No SPDX identifier.
**Individual files:** No copyright/license headers in any inspected Python file (npGeo.py, npg_io.py, npg_analysis.py, tbx_tools.py, __init__.py). Files contain author attribution (Dan Patterson, GitHub link) but no machine-readable license terms.

**Vendor-permitted:** needs-human

Under default copyright law (both US and Canada), absence of an explicit license means **all rights are reserved by the author**. Vendor copying without a license grant is legally risky regardless of attribution.

Author contact: Dan Patterson (Carleton University) — dan_patterson@carleton.ca (from repo bio).

---

## Algorithm shortlist (study-only until license confirmed)

The following pure-numpy functions are candidates for vendor copy **pending license grant**. All compute over `numpy.ndarray` inputs; none of the below create `arcpy.Point / Polygon / Polyline` objects.

| Function | Module | AutoGIS use case |
|---|---|---|
| `_trans_rot_2(a, angle)` | `numpy_geometry/npg/npg_maths.py` | Callout coordinate rotation for map layouts |
| `_ch_scipy_() / _ch_simple_()` | `numpy_geometry/npg/npg_geom_ops.py` | Bounding-box / convex hull for callout cluster placement |
| `n_near(a, N, ordered)` | `numpy_geometry/npg/npg_analysis.py` | Nearest-neighbor for spatial join in normalize_rpd.py |
| `simplify(a, tol)` | `numpy_geometry/npg/npg_geom_ops.py` | Contour / polyline generalization for GW contours |
| `_densify_2D(a, fact)` | `Tools_for_ArcGIS_Pro/PolygonLineTools/Scripts/densify_geom.py` | Contour point densification |

**WARNING — arcpy geometry objects in output stage:** Functions like `closest.connect()`, `densify_geom.arcpnts_poly()`, and `npg_arc_npg.Geo_to_arc_shapes()` create `arcpy.Point / Polygon / Polyline` objects in their output paths. These require ArcGIS Standard license and must NOT be copied — only the pure-numpy computation cores are candidates.

---

## Draft attribution block

Ready to paste into any vendored file header once license is confirmed:

```python
# Portions derived from Dan Patterson / numpy_geometry
# Source: https://github.com/Dan-Patterson/numpy_geometry
# Author: Dan Patterson <dan_patterson@carleton.ca>
# Adapted for AutoGIS under [LICENSE TO BE CONFIRMED — see docs/superpowers/specs/2026-06-23-numpy-geo-deltas.md]
```

---

## needs-human queue

### ITEM 1 — License grant required before any vendor copy

**Question for user:** May we reach out to Dan Patterson to request an explicit license grant (e.g. MIT or Apache-2.0) for the 5 pure-numpy functions listed in the algorithm shortlist above? Alternatively, do you have an existing relationship with him, or prefer to study the patterns only (no copy)?

**Context:** Both repos have no LICENSE file. Default copyright applies. The algorithms themselves are high-value (rotation, convex hull, n_near, simplify) and the pure-numpy cores are clean. The ask to the author is low-stakes — open educational repos with no monetization, and a simple "MIT license OK" email resolves the block.

**Options:**
1. Contact Dan Patterson to request MIT / Apache-2.0 license grant → unblocks vendor copy
2. Study patterns only → reimplement from scratch with no IP risk
3. Use scipy equivalents for convex hull; numpy-native for rotation; no vendor needed

### ITEM 2 — arcpy.da boundary for n_near / simplify

**Question for user:** N2 confirmed `n_near()` and `simplify()` stay in pure numpy **for their computation**. However if we call them via the existing script wrappers (closest.py, densify_geom.py), those wrappers do create arcpy geometry objects for output. AutoGIS would need to call the inner functions directly, bypassing the wrappers. Is that acceptable?

**Impact if unanswered:** none — this is a copy-implementation decision, not a license question.

---

## Status

**BLOCKED — do not vendor; study patterns only until needs-human items above are resolved.**

User decision required before implementation proceeds.

---

## Disposition

- [ ] User provides license guidance (Item 1 above)
- [ ] If vendor permitted: proceed to `docs/superpowers/plans/2026-06-24-numpy-geo-vendor.md`
- [ ] If study-only: implement from scratch; use scipy.spatial.ConvexHull + numpy for rotation
