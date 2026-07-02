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
