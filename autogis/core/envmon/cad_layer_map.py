"""GIS -> CAD layer-mapping resolution and CRS validation (Tool 8.9, arcpy-free).

The Export-to-CAD call itself is arcpy and lives in the .pyt toolbox; this
module owns the pure mapping/validation discipline plus the projection note,
and is reused by civil3d_points.py (Tool 8.2) for CRS handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR


@dataclass
class CADLayerMapping:
    gis_layer: str
    cad_layer: str
    color: Optional[int] = None
    linetype: Optional[str] = None


@dataclass
class CADExportPlan:
    mappings: list
    crs: str
    unmapped: list
    qa: QACollector


def load_cad_mapping(path: Path) -> dict:
    """Load {gis_layer: {cad_layer: str, color: int, linetype: str}} (YAML/JSON)."""
    from ..common.config import load_config
    return load_config(path) or {}


def validate_crs(crs: str, *, qa: QACollector) -> bool:
    if not crs or not crs.strip():
        qa.add(SEV_ERROR, "missing_crs", "No coordinate system provided.",
               recommended_action="Pass --crs (e.g. EPSG:2256).")
        return False
    return True


def find_prj_conflicts(cad_output_file: Path) -> list:
    """Projection files that would make Export To CAD reproject its output.

    A CAD file with an associated ``<same-stem>.prj``, or a folder-wide
    ``esri_cad.prj`` / ``*.uprj``, gets its coordinates *projected to that
    file's CRS* on export — silently breaking the "source coordinates pass
    through unchanged" contract in projection_note.txt (issue #238).
    Docs: pro.arcgis.com .../conversion/export-to-cad.htm (Usage);
    doc.esri.com .../help/data/cad/about-cad-coordinate-systems.html.
    """
    cad_output_file = Path(cad_output_file)
    folder = cad_output_file.parent
    candidates = [cad_output_file.with_suffix(".prj"), folder / "esri_cad.prj"]
    candidates += sorted(folder.glob("*.uprj")) if folder.is_dir() else []
    return [f for f in candidates if f.is_file()]


def write_projection_note(crs: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now().isoformat(timespec="seconds")
    out_path.write_text(
        f"Coordinate system: {crs}\n"
        f"Generated: {generated}\n"
        "Coordinates pass through unprojected; the consumer must assign "
        "this coordinate system on import.\n",
        encoding="utf-8",
    )
    return out_path


def write_mapping_report(plan: "CADExportPlan", out_path: Path) -> Path:
    """Write a CSV of gis_layer,cad_layer,color,linetype for the resolved plan.

    Export-to-CAD names CAD layers after the source feature class (arcpy has
    no verified per-feature Layer-property rename wired here yet -- see issue
    #166); this report is the record of the intended mapping for manual
    reclassification in the CAD package.
    """
    import csv as _csv
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["gis_layer", "cad_layer", "color", "linetype"])
        for m in plan.mappings:
            writer.writerow([m.gis_layer, m.cad_layer, m.color or "", m.linetype or ""])
    return out_path


def resolve_cad_plan(selected_layers: list, mapping_config: dict, *, crs: str) -> CADExportPlan:
    """Resolve GIS->CAD layer mappings; flag unmapped layers and a missing CRS."""
    qa = QACollector()
    validate_crs(crs, qa=qa)

    mappings = []
    unmapped = []
    for name in selected_layers:
        entry = mapping_config.get(name)
        if isinstance(entry, dict) and entry.get("cad_layer"):
            mappings.append(CADLayerMapping(
                gis_layer=name, cad_layer=str(entry["cad_layer"]),
                color=entry.get("color"), linetype=entry.get("linetype")))
        else:
            unmapped.append(name)

    if unmapped:
        qa.add(SEV_ERROR, "unmapped_layers",
               f"{len(unmapped)} selected layer(s) have no CAD mapping: "
               f"{', '.join(sorted(unmapped))}",
               recommended_action="Add mapping entries or deselect the layers.")

    return CADExportPlan(mappings=mappings, crs=crs, unmapped=unmapped, qa=qa)
