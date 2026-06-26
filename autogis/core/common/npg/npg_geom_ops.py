# Absorbed from Dan Patterson / numpy_geometry
# Source: https://github.com/Dan-Patterson/numpy_geometry
# Author: Dan Patterson <dan_patterson@carleton.ca>
# License: Free use (confirmed 2026-06-25)
# Modified in place for AutoGIS. See git log for changes.
#
# -*- coding: utf-8 -*-
# noqa: D205, D208, D400, F403
r"""
--------------------------------------
npg_geom_ops: Geometry focused methods
--------------------------------------

**Geometry focused methods that work with Geo arrays or np.ndarrays.**

----

Script :
    npg_geom_ops.py

Author :
    Dan_Patterson

    `<https://github.com/Dan-Patterson>`_.

Modified :
    2026-03-26

Purpose
-------
Geometry focused methods that work with Geo arrays or np.ndarrays.
In the case of the former, the methods may be being called from Geo methods
in such things as a list comprehension.

Notes
-----
AutoGIS note: This file contains only the pure-numpy functions from Dan
Patterson's original npg_geom_ops.py. Functions that required arcpy or
the npg ecosystem (npGeo, npg_geom_hlp, npg_pip, npg_prn, scipy.spatial)
are excluded with the EXCLUDED marker.

Functions that called _base_() (a Geo-array unwrapper) have been updated
to inline the equivalent: if hasattr(a, 'IFT'): a = a.XY

"""

# pylint: disable=C0103,C0201,C0209,C0302,C0415
# pylint: disable=R0902,R0904,R0912,R0913,R0914,R0915
# pylint: disable=W0105,W0201,W0212,W0221,W0611,W0612,W0613,W0621
# pylint: disable=E0401,E0611,E1101,E1121

import sys
import numpy as np

from numpy.lib.recfunctions import unstructured_to_structured as uts  # noqa
from numpy.lib.recfunctions import structured_to_unstructured as stu  # noqa
from numpy.lib.recfunctions import repack_fields  # noqa

# EXCLUDED: from scipy.spatial import ConvexHull as CH  — requires scipy
# EXCLUDED: from scipy.spatial import Delaunay          — requires scipy
# EXCLUDED: from npg import npGeo, npg_geom_hlp, npg_pip
# EXCLUDED: from npg.npg_helpers import _view_as_struct_
# EXCLUDED: from npg.npg_geom_hlp import (_bit_min_max_, _bit_area_, _base_, _e_2d_)
# EXCLUDED: from npg.npg_maths import _angles_3pnt_
# EXCLUDED: from npg.npg_pip import np_wn
# EXCLUDED: from npg.npg_prn import prn_q, prn_tbl

fmt_ = {"bool": lambda x: repr(x.astype(np.int32)),
        "float_kind": '{: 0.3f}'.format}
np.set_printoptions(precision=3, threshold=100, edgeitems=10, linewidth=80,
                    suppress=True,
                    formatter=fmt_,
                    floatmode='maxprec_equal',
                    legacy='1.25')  # legacy=False or legacy='1.25'
np.ma.masked_print_option.set_display('-')  # change to a single -

script = sys.argv[0]  # print this should you need to locate the script

# -- See script header

__all__ = [
    'densify_by_factor',               # (1) densify/simplify
    'densify_by_distance',
    'simplify',
    '_ch_simple_',                     # (2) convex hull — pure numpy
    '_ch_simple',                      # alias without trailing underscore
]

__helpers__ = [
    '_add_pnts_on_line_',
    '_pnt_on_segment_',
    '_is_pnt_on_line_',
    '_dist_along_',
    '_percent_along_',
]

__imports__ = [
    'uts', 'stu',       # np.lib.recfunctions (retained, no arcpy dependency)
]


# ---- ---------------------------
# ---- helpers (pure numpy, no npg dependency)
#

def _base_(a):
    """Return the XY coordinates of a Geo array, or pass through ndarray.

    Inlined from npg.npg_geom_hlp._base_ to avoid npg ecosystem dependency.
    """
    if hasattr(a, 'IFT'):
        return a.XY
    return a


def _is_pnt_on_line_(start, end, xy, tolerance=0.0):
    """Perform a distance check of whether a point is on a line.

    Parameters
    ----------
    start, end, xy : points, array-like
    tolerance : float
        Acceptable distance from the line.

    Notes
    -----
    `tolerance` is normally not needed unless you want to examine points
    quite close to a segment::

        eps = 2**-52 = 2.220446049250313e-16
        np.finfo(float).eps = 2.220446049250313e-16

    """
    #
    def sq_dist(a, b):
        """Add math.sqrt() for actual distance."""
        return (b[0] - a[0])**2 + (b[1] - a[1])**2
    #
    dl = sq_dist(start, end)  # -- line distance
    ds = sq_dist(start, xy)   # -- distance to start from pnt `xy`
    de = sq_dist(end, xy)     # -- distance to end from pnt `xy`
    d0, d1, d2 = np.sqrt([ds, de, dl])  # -- return the sqrt values
    if tolerance == 0.0:
        return d0 + d1 == d2
    d = (d0 + d1) - d2
    return -tolerance <= d <= tolerance


def _add_pnts_on_line_(a, spacing=1, is_percent=False):
    """Add points, at a fixed spacing, to an array representing a line.

    **See**  `densify_by_distance` for documentation.

    Parameters
    ----------
    a : array
        A sequence of `points`, x,y pairs, representing the bounds of a polygon
        or polyline object.
    spacing : number
        Spacing between the points to be added to the line.
    is_percent : boolean
        Express the densification as a percent of the total length.

    Notes
    -----
    densify by distance
    Called by `densify_by_distance`.

    """
    a = _base_(a)
    N = len(a) - 1                                    # segments
    dxdy = a[1:, :] - a[:-1, :]                       # coordinate differences
    leng = np.sqrt(np.einsum('ij,ij->i', dxdy, dxdy))  # segment lengths
    if is_percent:                                    # as percentage
        spacing = abs(spacing)
        spacing = min(spacing / 100, 1.)
        steps = (sum(leng) * spacing) / leng          # step distance
    else:
        steps = leng / spacing                        # step distance
    deltas = dxdy / (steps.reshape(-1, 1))            # coordinate steps
    pnts = np.empty((N,), dtype='O')                  # construct an `O` array
    for i in range(N):              # cycle through the segments and make
        num = np.arange(steps[i])   # the new points
        pnts[i] = np.array((num, num)).T * deltas[i] + a[i]
    a0 = a[-1].reshape(1, -1)       # create the final point and concatenate
    vals = np.concatenate((*pnts, a0), axis=0)
    return vals


def _pnt_on_segment_(pnt, seg):
    """Orthogonal projection of a point onto a 2 point line segment.

    Returns the intersection point, if the point is between the segment end
    points, otherwise, it returns the distance to the closest endpoint.

    Parameters
    ----------
    pnt : array-like
        `x,y` coordinate pair as list or ndarray
    seg : array-like
        `from-to points`, of x,y coordinates as an ndarray or equivalent.

    Notes
    -----
    >>> seg = np.array([[0, 0], [10, 10]])  # p0, p1
    >>> p = [10, 0]
    >>> pnt_on_seg(seg, p)
    array([5., 5.])

    Generically, with cross products and norms.

    np.cross for 2D arrays was deprecated in NumPy 2.0 use

    def cross2d(x, y):
        return x[..., 0] * y[..., 1] - x[..., 1] * y[..., 0]

    >>> d = np.linalg.norm(np.cross(p1 - p0, p0 - p))/np.linalg.norm(p1 - p0)
    >>> # becomes
    >>> d = np.linalg.norm(cross2d(p1 - p0, p0 - p))/np.linalg.norm(p1 - p0)
    """
    x0, y0, x1, y1, dx, dy = *pnt, *seg[0], *(seg[1] - seg[0])
    dist_ = dx * dx + dy * dy  # squared length
    u = ((x0 - x1) * dx + (y0 - y1) * dy) / dist_
    u = max(min(u, 1), 0)
    xy = np.array([dx, dy]) * u + [x1, y1]
    d = xy - pnt
    return xy, np.hypot(d[0], d[1])


def _dist_along_(a, dist=0):
    """Add a point along a poly feature at a distance from the start point.

    Parameters
    ----------
    dist : number
      `dist` is assumed to be a value between 0 and to total length of the
      poly feature.  If <= 0, the first point is returned.  If >= total
      length the last point is returned.

    Notes
    -----
    Determine the segment lengths and the cumulative length.  From the latter,
    locate the desired distance relative to it and the indices of the start
    and end points.

    The coordinates of those points and the remaining distance is used to
    derive the location of the point on the line.

    See Also
    --------
    _percent_along_ : function
        Similar to this function but measures distance as a percentage.
    """
    a = _base_(a)
    dxdy = a[1:, :] - a[:-1, :]                        # coordinate differences
    leng = np.sqrt(np.einsum('ij,ij->i', dxdy, dxdy))  # segment lengths
    cumleng = np.concatenate(([0], np.cumsum(leng)))   # cumulative length
    if dist <= 0:              # check for faulty distance or start point
        return a[0]
    if dist >= cumleng[-1]:    # check for distance greater than cumulative
        return a[-1]
    _end_ = np.digitize(dist, cumleng)
    x1, y1 = a[_end_]
    _start_ = _end_ - 1
    x0, y0 = a[_start_]
    t = (dist - cumleng[_start_]) / leng[_start_]
    xt = x0 * (1. - t) + (x1 * t)
    yt = y0 * (1. - t) + (y1 * t)
    return np.array([xt, yt])


def _percent_along_(a, percent=0):
    """Add a point along a poly feature at a distance from the start point.

    The distance is specified as a percentage of the total poly feature length.

    See Also
    --------
    _dist_along_ : function
        Similar to this function but measures distance as a finite value from
        the start point.

    Requires
    --------
    Called by `pnt_on_poly`.
    """
    a = _base_(a)
    if percent > 1.:
        percent /= 100.
    dxdy = a[1:, :] - a[:-1, :]                        # coordinate differences
    leng = np.sqrt(np.einsum('ij,ij->i', dxdy, dxdy))  # segment lengths
    cumleng = np.concatenate(([0], np.cumsum(leng)))
    perleng = cumleng / cumleng[-1]
    if percent <= 0:              # check for faulty distance or start point
        return a[0]
    if percent >= perleng[-1]:    # check for greater distance than cumulative
        return a[-1]
    _end_ = np.digitize(percent, perleng)
    x1, y1 = a[_end_]
    _start_ = _end_ - 1
    x0, y0 = a[_start_]
    t = percent - perleng[_start_]
    xt = x0 * (1. - t) + (x1 * t)
    yt = y0 * (1. - t) + (y1 * t)
    return np.array([xt, yt])


# ---- ---------------------------
# ---- (1) densify / simplify
#

def densify_by_factor(a, factor=2):
    """Densify a 2D array using np.interp.

    Parameters
    ----------
    a : array
        A 2D array of points representing a polyline/polygon boundary.
    factor : number
        The factor to density the line segments by.

    Notes
    -----
    The original construction of `c` rather than the zero's approach.

    >>> c0 = c0.reshape(n, -1)
    >>> c1 = c1.reshape(n, -1)
    >>> c = np.concatenate((c0, c1), axis=1)
    """
    a = np.squeeze(a)
    n_fact = len(a) * factor
    b = np.arange(0, n_fact, factor)
    b_new = np.arange(n_fact - 1)     # Where you want to interpolate
    c0 = np.interp(b_new, b, a[:, 0])
    c1 = np.interp(b_new, b, a[:, 1])
    n = c0.shape[0]
    c = np.zeros((n, 2))
    c[:, 0] = c0
    c[:, 1] = c1
    # check for, and remove duplicate end points if it is present.
    if (c[-2] == c[-1]).all():
        return c[:-1]
    return c


def densify_by_distance(a, spacing):
    r"""Return the wrapper for `pnts_on_line`.

    Example
    -------
    >>> a = np.array([[0., 0.], [3., 4.], [3., 0.], [0., 0.]])  # 3x4x5 rule
    >>> a.T
    array([[0., 3., 3., 0.],
           [0., 4., 0., 0.]])
    >>> pnts_on_line(a, spacing=2).T  # take the transpose to facilitate view
    ... array([[0. , 1.2, 2.4, 3. , 3. , 3. , 1. , 0. ],
    ...        [0. , 1.6, 3.2, 4. , 2. , 0. , 0. , 0. ]])

    Notes
    -----
    The return value could be np.vstack((*pnts, a[-1])) using the last point
    directly, but np.concatenate with a reshaped a[-1] is somewhat faster.
    All entries to the stacking must be ndim=2.

    References
    ----------
    `<https://stackoverflow.com/questions/54665326/adding-points-per-pixel-
    along-some-axis-for-2d-polygon>`_.

    `<https://stackoverflow.com/questions/51512197/python-equidistant-points
    -along-a-line-joining-set-of-points/51514725>`_.
    """
    return _add_pnts_on_line_(a, spacing)


def simplify(arr, tol=1e-6):
    """Remove redundant points on a poly perimeter."""
    if arr.base is not None:
        arr = arr.base  # get the base of the array
    x1, y1 = arr[:-2].T
    x2, y2 = arr[1:-1].T
    x3, y3 = arr[2:].T
    result = x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
    whr = np.nonzero(np.abs(result) >= tol)[0]
    bits = arr[1:-1][whr]
    keep = np.concatenate((arr[0, None], bits, arr[-1, None]), axis=0)
    return keep


# ---- ---------------------------
# ---- (2) convex hulls
#

# EXCLUDED: _ch_scipy_ — requires scipy.spatial.ConvexHull
# def _ch_scipy_(points):
#     # EXCLUDED: requires scipy — use numpy_geom wrapper instead
#     pass


def _ch_simple_(points):
    r"""Calculate the convex hull for given points.

    Removes null_pnts, finds the unique points, then determines the hull from
    the remaining.
    """
    def _x_(o, a, b):
        """Cross product for vectors o-a and o-b... a<--o-->b."""
        xo, yo = o
        xa, ya = a
        xb, yb = b
        return (xa - xo) * (yb - yo) - (ya - yo) * (xb - xo)
    # --
    _, idx = np.unique(points, return_index=True, axis=0)
    points = points[idx]
    if len(points) <= 3:
        return points
    # Build lower hull
    lower = []
    for p in points:
        while len(lower) >= 2 and _x_(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    # Build upper hull
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and _x_(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    ch = np.array(lower[:-1] + upper)[::-1]  # sort clockwise
    if np.all(ch[0] != ch[-1]):
        ch = np.concatenate((ch, [ch[0]]), axis=0)  # np.vstack((ch, ch[0]))
    return ch


# AutoGIS addition: alias without trailing underscore (brief requirement)
_ch_simple = _ch_simple_


# AutoGIS addition: not in Dan Patterson's original.
# _densify_2D adds evenly-spaced intermediate points along each segment of a
# 2D polyline/polygon array.  Equivalent to densify_by_distance but operates
# on a plain Nx2 ndarray (no Geo-array wrapping).
def _densify_2D(a, spacing=1.0):
    """Add intermediate points along each segment of a 2D coordinate array.

    Parameters
    ----------
    a : ndarray, shape (N, 2)
        Sequence of (x, y) coordinates representing a polyline or polygon ring.
    spacing : float
        Approximate distance between inserted points.  Points are placed at
        integer multiples of `spacing` measured from each segment's start.

    Returns
    -------
    ndarray, shape (M, 2)
        Densified coordinate array.  M >= N.

    Notes
    -----
    Unlike densify_by_factor (which uses np.interp and therefore changes the
    sample positions of *all* vertices), _densify_2D inserts new points only
    *between* existing vertices, preserving the original vertex locations.

    Example
    -------
    >>> a = np.array([[0., 0.], [0., 10.], [10., 10.]])
    >>> _densify_2D(a, spacing=3.0).T
    array([[ 0.,  0.,  0.,  0.,  0.,  3.,  6.,  9., 10.],
           [ 0.,  3.,  6.,  9., 10., 10., 10., 10., 10.]])
    """
    a = np.asarray(a, dtype=float)
    if a.ndim != 2 or a.shape[1] != 2:
        raise ValueError("_densify_2D expects an (N, 2) array")
    if len(a) < 2:
        return a.copy()

    parts = []
    for i in range(len(a) - 1):
        p0 = a[i]
        p1 = a[i + 1]
        seg_len = np.hypot(*(p1 - p0))
        if seg_len == 0.0 or spacing <= 0.0:
            parts.append(p0[None, :])
            continue
        n_steps = int(seg_len / spacing)  # number of intermediate points
        if n_steps < 1:
            parts.append(p0[None, :])
        else:
            t = np.arange(0, n_steps) / (seg_len / spacing)  # t in [0,1)
            pts = p0 + t[:, None] * (p1 - p0)
            parts.append(pts)
    parts.append(a[-1][None, :])  # always include the final vertex
    return np.concatenate(parts, axis=0)


# ===========================================================================
#
if __name__ == "__main__":
    """optional location for parameters"""
    # optional controls here
