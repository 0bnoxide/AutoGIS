"""AutoGIS public API over Dan Patterson's numpy geometry utilities (npg/).

All functions accept and return plain numpy arrays. No arcpy, no GIS objects,
no side effects. Safe to import without an ArcGIS Pro license.

Attribution: Dan Patterson <dan_patterson@carleton.ca>
Source: https://github.com/Dan-Patterson/numpy_geometry
License: Free use (confirmed 2026-06-25)
"""
from __future__ import annotations
import numpy as np


# ---------------------------------------------------------------------------
# rotate_points
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_maths import _trans_rot_2 as _rot
    # NOTE: _trans_rot_2 rotates about the array centroid, not the origin.
    # Raise AttributeError to force the pure-numpy fallback below.
    raise AttributeError("_trans_rot_2 rotates about centroid, not origin")
except (ImportError, AttributeError):
    def rotate_points(xy: np.ndarray, angle_deg: float) -> np.ndarray:
        """Rotate (x,y) points about the origin by angle_deg (counter-clockwise).

        Used by callout placement.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)
        angle_deg : float
            Rotation angle in degrees, counter-clockwise.

        Returns
        -------
        ndarray, shape (N, 2)
        """
        theta = np.radians(angle_deg)
        c, s = np.cos(theta), np.sin(theta)
        R = np.array([[c, -s], [s, c]])
        return (R @ xy.T).T


# ---------------------------------------------------------------------------
# convex_hull
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_geom_ops import _ch_simple as _ch

    def convex_hull(xy: np.ndarray) -> np.ndarray:
        """Convex hull vertices of (x,y) points. Used by callout collision.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)

        Returns
        -------
        ndarray, shape (M, 2)  where M <= N (interior points excluded).
            The closing duplicate vertex (if appended by npg) is stripped.
        """
        result = _ch(xy)
        # _ch_simple_ appends a closing point equal to result[0]; remove it.
        if len(result) > 1 and np.allclose(result[0], result[-1]):
            result = result[:-1]
        return result

except (ImportError, AttributeError):
    def convex_hull(xy: np.ndarray) -> np.ndarray:
        """Convex hull via gift wrapping (pure numpy fallback)."""
        pts = xy.tolist()
        n = len(pts)
        if n < 3:
            return xy
        start = min(range(n), key=lambda i: (pts[i][0], pts[i][1]))
        hull = []
        current = start
        while True:
            hull.append(current)
            next_pt = (current + 1) % n
            for i in range(n):
                ax = pts[next_pt][0] - pts[current][0]
                ay = pts[next_pt][1] - pts[current][1]
                bx = pts[i][0] - pts[current][0]
                by = pts[i][1] - pts[current][1]
                if ax * by - ay * bx > 0:
                    next_pt = i
            current = next_pt
            if current == start:
                break
        return np.array([pts[i] for i in hull])


# ---------------------------------------------------------------------------
# nearest_neighbors
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_analysis import n_near as _nn
    # NOTE: n_near has a hardcoded N > 1 guard (k=1 returns input unchanged)
    # and sorts by X coordinate, scrambling row indices. Force fallback.
    raise AttributeError("n_near N>1 guard and X-sort incompatible with contract")
except (ImportError, AttributeError):
    def nearest_neighbors(
        xy: np.ndarray, k: int = 1
    ) -> tuple[np.ndarray, np.ndarray]:
        """K nearest neighbors per point.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)
        k : int
            Number of neighbors to return per point.

        Returns
        -------
        idx : ndarray, shape (N, k)  — zero-based row indices of neighbors
        dists : ndarray, shape (N, k) — Euclidean distances to those neighbors
        """
        diff = xy[:, np.newaxis, :] - xy[np.newaxis, :, :]
        dist = np.sqrt((diff ** 2).sum(axis=-1))
        np.fill_diagonal(dist, np.inf)
        idx = np.argsort(dist, axis=1)[:, :k]
        dists = np.take_along_axis(dist, idx, axis=1)
        return idx, dists


# ---------------------------------------------------------------------------
# simplify_polyline
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_geom_ops import simplify as _simplify

    def simplify_polyline(xy: np.ndarray, tolerance: float) -> np.ndarray:
        """Douglas-Peucker-style simplification via cross-product area.

        Used by contour generalization.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)
        tolerance : float
            Minimum cross-product area to keep an intermediate vertex.
            Pass 0.0 to keep all vertices.

        Returns
        -------
        ndarray, shape (M, 2)  where M <= N
        """
        if tolerance == 0.0 or len(xy) <= 2:
            return xy
        return _simplify(xy, tol=tolerance)

except (ImportError, AttributeError):
    def _dp_reduce(xy: np.ndarray, tol: float) -> list[int]:
        if len(xy) <= 2:
            return list(range(len(xy)))
        start, end = xy[0], xy[-1]
        seg = end - start
        seg_len = np.linalg.norm(seg)
        if seg_len == 0:
            dists = np.linalg.norm(xy - start, axis=1)
        else:
            t = np.dot(xy - start, seg) / (seg_len ** 2)
            proj = start + np.outer(t, seg)
            dists = np.linalg.norm(xy - proj, axis=1)
        i_max = int(np.argmax(dists))
        if dists[i_max] <= tol:
            return [0, len(xy) - 1]
        left = _dp_reduce(xy[:i_max + 1], tol)
        right = _dp_reduce(xy[i_max:], tol)
        return left[:-1] + [i + i_max for i in right]

    def simplify_polyline(xy: np.ndarray, tolerance: float) -> np.ndarray:
        """Douglas-Peucker simplification (pure numpy fallback)."""
        if tolerance == 0.0 or len(xy) <= 2:
            return xy
        keep = _dp_reduce(xy, tolerance)
        return xy[keep]


# ---------------------------------------------------------------------------
# densify_polyline
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_geom_ops import _densify_2D as _densify

    def densify_polyline(xy: np.ndarray, factor: int) -> np.ndarray:
        """Add intermediate vertices along each segment.

        Used by contour smoothing.

        Parameters
        ----------
        xy : ndarray, shape (N, 2)
        factor : int
            Number of equal sub-segments per original segment.
            factor=2 inserts one midpoint per segment.

        Returns
        -------
        ndarray, shape (M, 2)  where M > N (for factor > 1)
        """
        if factor <= 1 or len(xy) < 2:
            return xy
        # _densify_2D takes a spacing distance, not a factor count.
        # Compute the minimum segment length and divide by factor so that
        # every segment gets at least `factor` sub-intervals.
        lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        min_len = lengths.min()
        spacing = min_len / factor
        if spacing <= 0:
            return xy
        return _densify(xy, spacing=spacing)

except (ImportError, AttributeError):
    def densify_polyline(xy: np.ndarray, factor: int) -> np.ndarray:
        """Linear interpolation densification (pure numpy fallback)."""
        if factor <= 1 or len(xy) < 2:
            return xy
        parts = []
        for i in range(len(xy) - 1):
            t = np.linspace(0, 1, factor + 1, endpoint=False)
            seg = xy[i] + np.outer(t, xy[i + 1] - xy[i])
            parts.append(seg)
        parts.append(xy[-1:])
        return np.concatenate(parts, axis=0)
