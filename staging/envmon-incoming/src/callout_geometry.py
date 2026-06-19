"""Pure-geometry construction for table-style analytical callouts.

No arcpy dependency. Everything works in map units so the calling arcpy
module only has to translate (x, y) tuples into arcpy geometries.

Conventions
-----------
* Map units are FEET or METERS (from the site spatial reference).
* Text sizes are specified in points at a reference map scale; the
  conversion is::

      map_units_per_point = reference_scale * (1/72 inch in map units)

  e.g. at 1:1,200 with feet: 1200 * (1/72 * 1/12) ft = 1.3889 ft/pt.
* A callout box origin is its LOWER-LEFT corner; rows are laid out
  top-down.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from callout_templates import CalloutTable

Point = Tuple[float, float]

INCHES_PER_POINT = 1.0 / 72.0

# Empirical text metrics for typical condensed map fonts (Arial/ Tahoma).
CHAR_WIDTH_FACTOR = 0.60   # average character width as a fraction of font size
ROW_HEIGHT_FACTOR = 1.50   # row height as a fraction of font size
BOX_PADDING_FACTOR = 0.35  # outer padding as a fraction of font size

GRIDLINE_ROW = "ROW"
GRIDLINE_COLUMN = "COLUMN"
GRIDLINE_OUTER = "OUTER_BORDER"

QUADRANT_ORDER_DEFAULT = ("NE", "NW", "SE", "SW", "E", "W", "N", "S")


def map_units_per_point(reference_scale: float, map_units: str) -> float:
    """Convert one typographic point to map units at the reference scale.

    map_units: 'feet' or 'meters' (case-insensitive; 'foot'/'meter' ok).
    """
    if reference_scale <= 0:
        raise ValueError(f"reference_scale must be > 0, got {reference_scale}")
    mu = (map_units or "").strip().lower()
    if mu in ("feet", "foot", "ft", "us_feet", "foot_us"):
        inch_in_map_units = 1.0 / 12.0
    elif mu in ("meters", "meter", "m", "metre", "metres"):
        inch_in_map_units = 0.0254
    else:
        raise ValueError(f"Unsupported map units for callout geometry: {map_units!r}")
    return reference_scale * INCHES_PER_POINT * inch_in_map_units


@dataclass
class GridLine:
    line_type: str           # ROW | COLUMN | OUTER_BORDER
    start: Point
    end: Point
    row_number: Optional[int] = None
    column_number: Optional[int] = None


@dataclass
class CellAnchor:
    x: float
    y: float
    row_number: int
    column_number: int
    cell_text: str
    style_class: str
    display_color_class: str
    h_align: str
    font_size_points: float
    is_bold: bool


@dataclass
class CalloutGeometry:
    """All geometry for one callout in map units, anchored at lower-left."""

    width: float
    height: float
    origin: Point = (0.0, 0.0)
    box_corners: List[Point] = field(default_factory=list)        # closed ring
    gridlines: List[GridLine] = field(default_factory=list)
    cell_anchors: List[CellAnchor] = field(default_factory=list)
    leader: Optional[Tuple[Point, Point]] = None                  # source pt -> box edge
    row_heights: List[float] = field(default_factory=list)
    column_widths: List[float] = field(default_factory=list)

    def translate(self, dx: float, dy: float) -> "CalloutGeometry":
        """Return a copy of this geometry shifted by (dx, dy)."""
        def t(p: Point) -> Point:
            return (p[0] + dx, p[1] + dy)

        out = CalloutGeometry(
            width=self.width,
            height=self.height,
            origin=t(self.origin),
            box_corners=[t(p) for p in self.box_corners],
            gridlines=[
                GridLine(g.line_type, t(g.start), t(g.end), g.row_number, g.column_number)
                for g in self.gridlines
            ],
            cell_anchors=[
                CellAnchor(a.x + dx, a.y + dy, a.row_number, a.column_number,
                           a.cell_text, a.style_class, a.display_color_class,
                           a.h_align, a.font_size_points, a.is_bold)
                for a in self.cell_anchors
            ],
            leader=None if self.leader is None else (t(self.leader[0]), t(self.leader[1])),
            row_heights=list(self.row_heights),
            column_widths=list(self.column_widths),
        )
        return out

    def bounds(self) -> Tuple[float, float, float, float]:
        ox, oy = self.origin
        return (ox, oy, ox + self.width, oy + self.height)



def _rows_of(table) -> List[list]:
    """Group a CalloutTable's flat cell list into row-ordered lists."""
    by_row = {}
    for c in table.cells:
        by_row.setdefault(c.row, []).append(c)
    return [sorted(by_row[r], key=lambda c: c.col)
            for r in sorted(by_row)]


def compute_box_size(
    table: CalloutTable,
    reference_scale: float,
    map_units: str,
    base_font_points: float,
) -> Tuple[float, float, List[float], List[float]]:
    """Size a callout box from its table contents.

    Returns (width, height, column_widths, row_heights) in map units.
    """
    mupp = map_units_per_point(reference_scale, map_units)
    char_w = CHAR_WIDTH_FACTOR * base_font_points * mupp
    pad = BOX_PADDING_FACTOR * base_font_points * mupp

    col_chars = table.column_char_widths()
    column_widths = [max(2, c) * char_w + 2 * pad for c in col_chars]

    rows = _rows_of(table)
    row_heights: List[float] = [ROW_HEIGHT_FACTOR * base_font_points * mupp
                                for _ in rows]

    width = sum(column_widths)
    height = sum(row_heights)
    return width, height, column_widths, row_heights


def build_callout_geometry(
    table: CalloutTable,
    reference_scale: float,
    map_units: str,
    base_font_points: float,
    origin: Point = (0.0, 0.0),
) -> CalloutGeometry:
    """Build full geometry (box ring, gridlines, anchors) at *origin*."""
    width, height, col_w, row_h = compute_box_size(
        table, reference_scale, map_units, base_font_points
    )
    ox, oy = origin
    top = oy + height

    geom = CalloutGeometry(width=width, height=height, origin=origin,
                           row_heights=row_h, column_widths=col_w)

    # Outer ring (closed, clockwise from lower-left)
    geom.box_corners = [
        (ox, oy), (ox, top), (ox + width, top), (ox + width, oy), (ox, oy)
    ]
    geom.gridlines.append(GridLine(GRIDLINE_OUTER, (ox, oy), (ox, top)))
    geom.gridlines.append(GridLine(GRIDLINE_OUTER, (ox, top), (ox + width, top)))
    geom.gridlines.append(GridLine(GRIDLINE_OUTER, (ox + width, top), (ox + width, oy)))
    geom.gridlines.append(GridLine(GRIDLINE_OUTER, (ox + width, oy), (ox, oy)))

    # Horizontal row separators (between rows; not duplicating outer border)
    y = top
    for r_idx, rh in enumerate(row_h[:-1], start=1):
        y -= rh
        geom.gridlines.append(
            GridLine(GRIDLINE_ROW, (ox, y), (ox + width, y), row_number=r_idx)
        )

    # Vertical column separators. Rows containing span cells (title rows,
    # group headers) typically span the whole table, so we only draw the
    # separator through rows whose cell structure has > 1 cell at that
    # column boundary. For simplicity and to match the CKG/ZT42 look, draw
    # full-height column lines only where *every* row has a boundary there
    # (i.e. no spanning cell crosses it); otherwise draw per-row segments.
    n_cols = len(col_w)
    col_x = [ox]
    for w in col_w:
        col_x.append(col_x[-1] + w)

    for c_idx in range(1, n_cols):
        x = col_x[c_idx]
        # Per-row segments so we never slice through a spanned title cell.
        y_top = top
        for r_idx, row in enumerate(_rows_of(table), start=1):
            rh = row_h[r_idx - 1]
            y_bot = y_top - rh
            if _row_has_boundary_at(row, c_idx):
                geom.gridlines.append(
                    GridLine(GRIDLINE_COLUMN, (x, y_bot), (x, y_top),
                             row_number=r_idx, column_number=c_idx)
                )
            y_top = y_bot

    # Cell anchors (text insertion points). Left-aligned cells anchor at
    # left padding; centered cells at the cell center. Vertical anchor is
    # the row's vertical center.
    mupp = map_units_per_point(reference_scale, map_units)
    pad = BOX_PADDING_FACTOR * base_font_points * mupp

    y_top = top
    for r_idx, row in enumerate(_rows_of(table), start=1):
        rh = row_h[r_idx - 1]
        y_mid = y_top - rh / 2.0
        for cell in row:
            span = max(1, cell.col_span)
            c0 = cell.col - 1
            x_left = col_x[min(c0, n_cols)]
            x_right = col_x[min(c0 + span, n_cols)]
            align = (cell.h_align or "LEFT").upper()
            if align == "CENTER":
                ax = (x_left + x_right) / 2.0
            elif align == "RIGHT":
                ax = x_right - pad
            else:
                ax = x_left + pad
            geom.cell_anchors.append(
                CellAnchor(
                    x=ax, y=y_mid,
                    row_number=r_idx, column_number=cell.col,
                    cell_text=cell.text,
                    style_class=cell.style_class,
                    display_color_class=cell.display_color_class,
                    h_align=align,
                    font_size_points=base_font_points,
                    is_bold=cell.is_header or cell.is_exceedance,
                )
            )
        y_top -= rh

    return geom


def _row_has_boundary_at(row, boundary_index: int) -> bool:
    """True if a cell edge in this row (list of CellSpec) falls exactly at
    column boundary_index — i.e. no spanning cell crosses it."""
    for cell in row:
        end = cell.col - 1 + max(1, cell.col_span)
        if end == boundary_index:
            return True
        if cell.col - 1 < boundary_index < end:
            return False
    return False


def leader_attachment(box_bounds: Tuple[float, float, float, float],
                      source: Point) -> Point:
    """Pick the nearest box-edge midpoint as the leader attachment point."""
    xmin, ymin, xmax, ymax = box_bounds
    candidates = [
        ((xmin + xmax) / 2.0, ymin),   # bottom
        ((xmin + xmax) / 2.0, ymax),   # top
        (xmin, (ymin + ymax) / 2.0),   # left
        (xmax, (ymin + ymax) / 2.0),   # right
    ]
    sx, sy = source
    return min(candidates, key=lambda p: math.hypot(p[0] - sx, p[1] - sy))


def quadrant_offsets(
    box_w: float,
    box_h: float,
    standoff: float,
    order: Sequence[str] = QUADRANT_ORDER_DEFAULT,
) -> List[Tuple[str, float, float]]:
    """Candidate (quadrant, dx, dy) offsets of the box LOWER-LEFT corner
    relative to the source point, for each placement quadrant."""
    s = standoff
    table = {
        "NE": (s, s),
        "NW": (-box_w - s, s),
        "SE": (s, -box_h - s),
        "SW": (-box_w - s, -box_h - s),
        "E": (s, -box_h / 2.0),
        "W": (-box_w - s, -box_h / 2.0),
        "N": (-box_w / 2.0, s),
        "S": (-box_w / 2.0, -box_h - s),
    }
    out = []
    for q in order:
        if q not in table:
            raise ValueError(f"Unknown placement quadrant {q!r}")
        dx, dy = table[q]
        out.append((q, dx, dy))
    return out
