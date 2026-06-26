from __future__ import annotations
import numpy as np
import pytest
from autogis.core.common.numpy_geom import (
    rotate_points, convex_hull, nearest_neighbors,
    simplify_polyline, densify_polyline,
)


def test_rotate_points_90_degrees():
    """Rotating (1,0) by 90 degrees should give approximately (0,1)."""
    xy = np.array([[1.0, 0.0]])
    result = rotate_points(xy, 90.0)
    assert result.shape == (1, 2)
    assert abs(result[0, 0]) < 1e-10
    assert abs(result[0, 1] - 1.0) < 1e-10


def test_rotate_points_0_degrees_unchanged():
    xy = np.array([[3.0, 4.0], [1.0, 2.0]])
    result = rotate_points(xy, 0.0)
    np.testing.assert_allclose(result, xy, atol=1e-10)


def test_rotate_points_360_degrees_unchanged():
    xy = np.array([[3.0, 4.0]])
    result = rotate_points(xy, 360.0)
    np.testing.assert_allclose(result, xy, atol=1e-10)


def test_convex_hull_returns_array():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                   [0.0, 1.0], [0.5, 0.5]])
    hull = convex_hull(xy)
    assert isinstance(hull, np.ndarray)
    assert hull.shape[1] == 2


def test_convex_hull_interior_point_excluded():
    """The interior point (0.5, 0.5) must not appear in the hull."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                   [0.0, 1.0], [0.5, 0.5]])
    hull = convex_hull(xy)
    assert len(hull) <= 4


def test_nearest_neighbors_returns_indices_and_distances():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 0.0]])
    idx, dists = nearest_neighbors(xy, k=1)
    assert idx.shape == (3, 1)
    assert dists.shape == (3, 1)


def test_nearest_neighbors_correct_match():
    """Point 0 (0,0) is closest to Point 1 (1,0), not Point 2 (10,0)."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 0.0]])
    idx, dists = nearest_neighbors(xy, k=1)
    assert idx[0, 0] == 1
    assert abs(dists[0, 0] - 1.0) < 1e-10


def test_nearest_neighbors_k2():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [10.0, 0.0]])
    idx, dists = nearest_neighbors(xy, k=2)
    assert idx.shape == (4, 2)


def test_simplify_polyline_reduces_vertices():
    """A collinear line should simplify to just endpoints."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0],
                   [3.0, 0.0], [4.0, 0.0]])
    result = simplify_polyline(xy, tolerance=0.01)
    assert len(result) <= 2


def test_simplify_polyline_preserves_endpoints():
    xy = np.array([[0.0, 0.0], [1.0, 0.5], [2.0, 0.0]])
    result = simplify_polyline(xy, tolerance=0.01)
    np.testing.assert_allclose(result[0], xy[0])
    np.testing.assert_allclose(result[-1], xy[-1])


def test_simplify_polyline_zero_tolerance_keeps_all():
    xy = np.array([[0.0, 0.0], [1.0, 0.5], [2.0, 0.0]])
    result = simplify_polyline(xy, tolerance=0.0)
    assert len(result) == len(xy)


def test_densify_polyline_increases_vertices():
    xy = np.array([[0.0, 0.0], [2.0, 0.0]])
    result = densify_polyline(xy, factor=2)
    assert len(result) > len(xy)


def test_densify_polyline_preserves_endpoints():
    xy = np.array([[0.0, 0.0], [4.0, 0.0]])
    result = densify_polyline(xy, factor=4)
    np.testing.assert_allclose(result[0], xy[0])
    np.testing.assert_allclose(result[-1], xy[-1])


def test_densify_polyline_midpoint_correct():
    """Densify [[0,0],[2,0]] by factor 2 should include [1,0]."""
    xy = np.array([[0.0, 0.0], [2.0, 0.0]])
    result = densify_polyline(xy, factor=2)
    midpoints = result[1:-1]
    assert any(abs(p[0] - 1.0) < 1e-10 and abs(p[1]) < 1e-10
               for p in midpoints)
