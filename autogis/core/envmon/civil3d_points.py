"""PNEZD point CSV + projection metadata for Civil 3D surface input (Tool 8.2).

Headless leg of ExportContoursForCivil3D: PNEZD CSV, projection note, and
(ADR-0088) point-only LandXML CgPoints export, sharing
``core.common.landxml.write_cgpoints`` with export_survey_cad.py (issue
#164). Contour polylines / TIN surfaces still require arcpy and are not yet
wired — see issue #166. CRS validation and the projection note are owned by
cad_layer_map (Tool 8.9) and reused here.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..common.landxml import CgPoint, write_cgpoints
from ..common.qa import QACollector, SEV_WARNING
from .cad_layer_map import validate_crs, write_projection_note  # noqa: F401  (re-export)


@dataclass
class PNEZDPoint:
    point_number: int
    northing: float
    easting: float
    elevation: float
    description: str


def load_gwe_points_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_pnezd(points: list, *, crs: str, start_number: int = 1,
                 qa: QACollector) -> list:
    """Build sequential PNEZD points from elevation records.

    A record with missing/blank/unparseable z is skipped with a SEV_WARNING.
    """
    validate_crs(crs, qa=qa)

    result = []
    number = start_number
    for rec in points:
        try:
            elevation = float(rec.get("z"))
        except (TypeError, ValueError):
            qa.add(SEV_WARNING, "missing_elevation",
                   f"Point {rec.get('location_id', '?')} has no usable elevation; skipped.")
            continue
        result.append(PNEZDPoint(
            point_number=number,
            northing=float(rec["y"]),
            easting=float(rec["x"]),
            elevation=elevation,
            description=rec.get("description") or rec.get("location_id", ""),
        ))
        number += 1
    return result


def write_pnezd_csv(points: list, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["point_number", "northing", "easting", "elevation", "description"])
        for p in points:
            writer.writerow([p.point_number, p.northing, p.easting, p.elevation, p.description])
    return out_path


def write_pnezd_landxml(points: list, out_path: Path) -> Path:
    """Write PNEZD points as a LandXML 1.2 ``<CgPoints>`` file (points only;
    no contour/TIN surface -- that leg still requires arcpy, see issue #166).
    """
    return write_cgpoints(
        (CgPoint(str(p.point_number), p.northing, p.easting, p.elevation,
                 description=p.description)
         for p in points),
        out_path,
    )
