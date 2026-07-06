"""subsurface_profile.py — GenerateSubsurfaceProfileFromBorings (headless).

Projects ``BoringLocation`` rows onto a straight 2-point profile line and
pulls each in-tolerance boring's ``LithologyInterval`` rows for rendering.
Reuses the 8.0a boring-log database read side
(:func:`autogis.core.envmon.boring_log_report.read_boring_records`) — no
parallel DB reader.

Rendering (matplotlib) is lazy-imported and optional (``pip install
"autogis[profile]"``); everything else here is arcpy-free and
matplotlib-free.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_WARNING
from .boring_log_report import read_boring_records

Point = tuple  # (northing, easting)


@dataclass
class ProfileBoringPlacement:
    boring_id: str
    station_ft: float
    offset_ft: float
    location: dict
    lithology: list


def _boring_point(locations: dict, boring_id: str) -> Point:
    bundle = locations.get(boring_id)
    if bundle is None:
        raise ValueError(f"Boring {boring_id!r} not found in the database.")
    loc = bundle["location"]
    n, e = loc.get("northing"), loc.get("easting")
    if n is None or e is None:
        raise ValueError(f"Boring {boring_id!r} has no northing/easting.")
    return (n, e)


def resolve_endpoints(
    locations: dict,
    *,
    boring_a: Optional[str] = None,
    boring_b: Optional[str] = None,
    start: Optional[Point] = None,
    end: Optional[Point] = None,
) -> tuple:
    """Resolve the profile line's two endpoints.

    Exactly one mode: a pair of boring IDs (looked up in *locations*), or a
    pair of literal (northing, easting) coordinates.
    """
    by_ids = boring_a is not None or boring_b is not None
    by_coords = start is not None or end is not None
    if by_ids and by_coords:
        raise ValueError(
            "Specify profile endpoints by boring IDs or coordinates, not both.")
    if by_ids:
        if boring_a is None or boring_b is None:
            raise ValueError("Both --boring-a and --boring-b are required.")
        return (_boring_point(locations, boring_a), _boring_point(locations, boring_b))
    if by_coords:
        if start is None or end is None:
            raise ValueError("Both --start and --end are required.")
        return (start, end)
    raise ValueError(
        "Specify profile endpoints: --boring-a/--boring-b or --start/--end.")


def project_onto_line(point: Point, a: Point, b: Point) -> tuple:
    """Return ``(station_ft, offset_ft)`` of *point* projected onto line a->b.

    ``station_ft`` is the signed distance from *a* along the line;
    ``offset_ft`` is the signed perpendicular distance.
    """
    ax, ay = a
    bx, by = b
    px, py = point
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("Profile endpoints are coincident.")
    ux, uy = dx / length, dy / length
    vx, vy = px - ax, py - ay
    station = vx * ux + vy * uy
    offset = vx * uy - vy * ux
    return station, offset


def place_borings(
    locations: dict,
    a: Point,
    b: Point,
    *,
    tolerance_ft: float,
    qa: Optional[QACollector] = None,
) -> list:
    """Project every boring in *locations* onto line a->b; keep those within
    *tolerance_ft* perpendicular offset. Borings beyond tolerance (or with no
    coordinates) are excluded with a QA warning naming them, not silently
    dropped."""
    placements = []
    excluded = []
    for boring_id, bundle in locations.items():
        loc = bundle["location"]
        n, e = loc.get("northing"), loc.get("easting")
        if n is None or e is None:
            excluded.append(boring_id)
            continue
        station, offset = project_onto_line((n, e), a, b)
        if abs(offset) > tolerance_ft:
            excluded.append(boring_id)
            continue
        placements.append(ProfileBoringPlacement(
            boring_id=boring_id, station_ft=station, offset_ft=offset,
            location=loc, lithology=bundle.get("lithology", []),
        ))
    if excluded and qa is not None:
        qa.add(SEV_WARNING, "boring_outside_tolerance",
               f"{len(excluded)} boring(s) excluded (beyond {tolerance_ft} ft "
               f"of the profile line, or missing coordinates): "
               + ", ".join(sorted(excluded)))
    placements.sort(key=lambda p: p.station_ft)
    return placements


def build_profile(
    db_path: Path,
    *,
    boring_a: Optional[str] = None,
    boring_b: Optional[str] = None,
    start: Optional[Point] = None,
    end: Optional[Point] = None,
    tolerance_ft: float = 50.0,
    qa: Optional[QACollector] = None,
) -> list:
    """End-to-end: read the boring DB, resolve endpoints, place borings."""
    locations = read_boring_records(db_path, qa=qa)
    a, b = resolve_endpoints(locations, boring_a=boring_a, boring_b=boring_b,
                              start=start, end=end)
    return place_borings(locations, a, b, tolerance_ft=tolerance_ft, qa=qa)


# ---- rendering (matplotlib, lazy-imported, optional) ------------------------

_MATPLOTLIB_HINT = ('matplotlib is required to render subsurface profiles. '
                     'Install with: pip install "autogis[profile]"')


def render_profile(placements: list, out_path: Path, *, title: str = "") -> Path:
    """Render a subsurface profile PNG/SVG: one lithology column per boring,
    positioned at its station, banded by interval. Pillow is not involved;
    matplotlib is lazy-imported here (the only place)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError as exc:
        raise ImportError(_MATPLOTLIB_HINT) from exc

    fig, ax = plt.subplots(figsize=(max(6, len(placements) * 1.5), 8))
    col_width = max((p.station_ft for p in placements), default=1.0) * 0.02 + 1.0
    for p in placements:
        ground = p.location.get("ground_elevation") or 0.0
        for iv in p.lithology:
            top = ground - iv["top_depth"]
            bottom = ground - iv["bottom_depth"]
            ax.add_patch(Rectangle(
                (p.station_ft - col_width / 2, bottom), col_width, top - bottom,
                edgecolor="black", facecolor="#d9c9a3", linewidth=0.5))
            if iv.get("uscs"):
                ax.text(p.station_ft, (top + bottom) / 2, iv["uscs"],
                        ha="center", va="center", fontsize=6)
        ax.text(p.station_ft, ground + 1, p.boring_id,
                ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax.set_xlabel("Station (ft)")
    ax.set_ylabel("Elevation (ft)")
    if title:
        ax.set_title(title)
    ax.grid(True, linestyle=":", linewidth=0.5)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path
