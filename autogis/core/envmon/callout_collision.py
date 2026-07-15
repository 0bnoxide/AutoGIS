"""Collision detection and automatic placement for analytical callouts.

Pure Python (no arcpy). Operates on axis-aligned rectangles in map units.

Placement contract (per spec):
* User overrides from Env_CalloutPlacementOverrides are honored first.
  LockedPlacement=1 rows are NEVER moved (PlacementMethod=OVERRIDE_LOCKED).
  Unlocked overrides are used as the starting candidate
  (PlacementMethod=OVERRIDE_UNLOCKED) but may be auto-adjusted on
  collision.
* Otherwise quadrants are tried in order NE, NW, SE, SW, E, W, N, S.
* A candidate is rejected if it overlaps any placed box, any point
  buffer, any prohibited polygon (approximated by rect), or leaves the
  map extent.
* If every candidate collides, the lowest-collision-score candidate is
  used and the callout is flagged AUTO_COLLISION_WARNING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .callout_geometry import quadrant_offsets, QUADRANT_ORDER_DEFAULT

Rect = Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax

PM_OVERRIDE_LOCKED = "OVERRIDE_LOCKED"
PM_OVERRIDE_UNLOCKED = "OVERRIDE_UNLOCKED"
PM_AUTO_NO_COLLISION = "AUTO_NO_COLLISION"
PM_AUTO_COLLISION_WARNING = "AUTO_COLLISION_WARNING"
PM_FAILED = "FAILED"


def rect_intersection_area(a: Rect, b: Rect) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0.0 or h <= 0.0:
        return 0.0
    return w * h


def rect_within(inner: Rect, outer: Rect) -> bool:
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def point_buffer_rect(pt: Tuple[float, float], buffer_dist: float) -> Rect:
    x, y = pt
    return (x - buffer_dist, y - buffer_dist, x + buffer_dist, y + buffer_dist)


@dataclass
class CalloutRequest:
    callout_id: str
    location_id: str
    source_point: Tuple[float, float]
    box_width: float
    box_height: float
    # From Env_CalloutPlacementOverrides (origin = lower-left in map units)
    override_origin: Optional[Tuple[float, float]] = None
    locked: bool = False


@dataclass
class PlacementResult:
    callout_id: str
    location_id: str
    origin: Tuple[float, float]            # lower-left of placed box
    rect: Rect
    placement_method: str
    quadrant: Optional[str] = None
    collision_score: float = 0.0
    collided_with: List[str] = field(default_factory=list)


@dataclass
class CollisionReport:
    a_id: str
    b_kind: str                            # CALLOUT | POINT_BUFFER | PROHIBITED | EXTENT
    b_id: str
    overlap_area: float


def detect_callout_collisions(
    placed: Sequence[PlacementResult],
    point_buffers: Dict[str, Rect],
    prohibited: Optional[Dict[str, Rect]] = None,
    extent: Optional[Rect] = None,
    tolerance: float = 0.0,
) -> List[CollisionReport]:
    """Report every overlap among placed boxes / buffers / prohibited / extent."""
    reports: List[CollisionReport] = []
    prohibited = prohibited or {}
    boxes = list(placed)
    for i, p in enumerate(boxes):
        for q in boxes[i + 1:]:
            area = rect_intersection_area(p.rect, q.rect)
            if area > tolerance:
                reports.append(CollisionReport(p.callout_id, "CALLOUT", q.callout_id, area))
        for pid, buf in point_buffers.items():
            # A callout is allowed to be near its own source point but not on it.
            area = rect_intersection_area(p.rect, buf)
            if area > tolerance:
                reports.append(CollisionReport(p.callout_id, "POINT_BUFFER", pid, area))
        for zid, z in prohibited.items():
            area = rect_intersection_area(p.rect, z)
            if area > tolerance:
                reports.append(CollisionReport(p.callout_id, "PROHIBITED", zid, area))
        if extent is not None and not rect_within(p.rect, extent):
            reports.append(CollisionReport(p.callout_id, "EXTENT", "MAP_EXTENT", 0.0))
    return reports


def _candidate_score(
    rect: Rect,
    placed_rects: Sequence[Tuple[str, Rect]],
    point_buffers: Dict[str, Rect],
    prohibited: Dict[str, Rect],
    extent: Optional[Rect],
    off_extent_penalty: float,
) -> Tuple[float, List[str]]:
    score = 0.0
    hits: List[str] = []
    for rid, r in placed_rects:
        a = rect_intersection_area(rect, r)
        if a > 0.0:
            score += a
            hits.append(f"CALLOUT:{rid}")
    for pid, buf in point_buffers.items():
        a = rect_intersection_area(rect, buf)
        if a > 0.0:
            score += a
            hits.append(f"POINT_BUFFER:{pid}")
    for zid, z in prohibited.items():
        a = rect_intersection_area(rect, z)
        if a > 0.0:
            score += a
            hits.append(f"PROHIBITED:{zid}")
    if extent is not None and not rect_within(rect, extent):
        score += off_extent_penalty
        hits.append("EXTENT:MAP_EXTENT")
    return score, hits


def place_callouts(
    requests: Sequence[CalloutRequest],
    extent: Optional[Rect],
    point_buffer_dist: float,
    standoff: float,
    quadrant_order: Sequence[str] = QUADRANT_ORDER_DEFAULT,
    prohibited: Optional[Dict[str, Rect]] = None,
    tolerance: float = 0.0,
) -> List[PlacementResult]:
    """Greedy placement: locked overrides first, then north-to-south.

    Returns one PlacementResult per request (never drops a callout).
    """
    prohibited = dict(prohibited or {})
    point_buffers = {
        r.callout_id: point_buffer_rect(r.source_point, point_buffer_dist)
        for r in requests
    }
    off_extent_penalty = 4.0 * max(
        (r.box_width * r.box_height for r in requests), default=1.0
    )

    results: List[PlacementResult] = []
    placed_rects: List[Tuple[str, Rect]] = []

    def rect_at(req: CalloutRequest, origin: Tuple[float, float]) -> Rect:
        ox, oy = origin
        return (ox, oy, ox + req.box_width, oy + req.box_height)

    # 1) Locked overrides claim their space unconditionally.
    locked = [r for r in requests if r.locked and r.override_origin is not None]
    for req in locked:
        rect = rect_at(req, req.override_origin)
        score, hits = _candidate_score(
            rect, placed_rects, point_buffers, prohibited, extent, off_extent_penalty
        )
        results.append(PlacementResult(
            callout_id=req.callout_id, location_id=req.location_id,
            origin=req.override_origin, rect=rect,
            placement_method=PM_OVERRIDE_LOCKED,
            collision_score=score, collided_with=hits,
        ))
        placed_rects.append((req.callout_id, rect))

    # 2) Remaining callouts, north-to-south for stable, readable stacking.
    rest = [r for r in requests if r not in locked]
    rest.sort(key=lambda r: -r.source_point[1])

    for req in rest:
        candidates: List[Tuple[str, Tuple[float, float]]] = []
        if req.override_origin is not None:
            candidates.append(("OVERRIDE", req.override_origin))
        for quad, dx, dy in quadrant_offsets(
            req.box_width, req.box_height, standoff, quadrant_order
        ):
            sx, sy = req.source_point
            candidates.append((quad, (sx + dx, sy + dy)))

        best: Optional[Tuple[float, str, Tuple[float, float], List[str]]] = None
        chosen: Optional[Tuple[str, Tuple[float, float]]] = None
        for quad, origin in candidates:
            rect = rect_at(req, origin)
            score, hits = _candidate_score(
                rect, placed_rects, point_buffers, prohibited, extent,
                off_extent_penalty,
            )
            if score <= tolerance:
                chosen = (quad, origin)
                break
            if best is None or score < best[0]:
                best = (score, quad, origin, hits)

        if chosen is not None:
            quad, origin = chosen
            rect = rect_at(req, origin)
            method = (PM_OVERRIDE_UNLOCKED if quad == "OVERRIDE"
                      else PM_AUTO_NO_COLLISION)
            results.append(PlacementResult(
                callout_id=req.callout_id, location_id=req.location_id,
                origin=origin, rect=rect, placement_method=method,
                quadrant=None if quad == "OVERRIDE" else quad,
                collision_score=0.0,
            ))
            placed_rects.append((req.callout_id, rect))
        else:
            # Every candidate collides: take the least-bad one and warn.
            assert best is not None
            score, quad, origin, hits = best
            rect = rect_at(req, origin)
            results.append(PlacementResult(
                callout_id=req.callout_id, location_id=req.location_id,
                origin=origin, rect=rect,
                placement_method=PM_AUTO_COLLISION_WARNING,
                quadrant=None if quad == "OVERRIDE" else quad,
                collision_score=score, collided_with=hits,
            ))
            placed_rects.append((req.callout_id, rect))

    return results
