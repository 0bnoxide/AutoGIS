"""Export RTK survey points to feature-code-mapped CSV/GeoJSON layers (headless).

Reuses ``import_rtk_survey.parse_rtk_csv()`` as the source parser, then groups
points by a configurable feature-code -> layer-name mapping (e.g. ``MW`` ->
``MonitoringWells``, ``GCP`` -> ``DroneControlPoints``, ``BM`` ->
``Benchmarks``) and writes one CSV (+ optional GeoJSON) per layer, plus a
JSON manifest.

Scope: CSV/GeoJSON layers only. DWG/DXF/LandXML CAD export needs a template
or external library decision and is explicitly out of scope for this tool —
see the related ADR for the deferred follow-up.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import re
from pathlib import Path
from typing import Dict, List

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING
from .import_rtk_survey import RTKPoint

_DEFAULT_LAYER = "Miscellaneous"
_UNSAFE_NAME_CHARS = re.compile(r"[\\/]")


def _sanitize_layer_name(layer_name: str, *, qa: QACollector) -> str:
    """Return a filesystem-safe layer name for use as a bare file stem.

    Layer names come from a caller-supplied YAML map, so a value like
    ``"../../etc/pwn"`` must not be allowed to escape ``output_dir``. Path
    separators (either slash) are replaced with ``_``; ``""``/``"."``/``".."``
    are replaced with a fixed fallback name.
    """
    safe = _UNSAFE_NAME_CHARS.sub("_", layer_name).strip()
    if safe in ("", ".", ".."):
        safe = "_invalid_layer"
    if safe != layer_name:
        qa.add(SEV_WARNING, "unsafe_layer_name",
               f"Layer name {layer_name!r} is not filesystem-safe; "
               f"using {safe!r} instead.")
    return safe


@dataclasses.dataclass
class LayerManifestEntry:
    """One row of the export manifest: a layer and what was written for it."""
    layer_name: str
    feature_codes: str      # semicolon-joined feature codes routed to this layer
    point_count: int
    output_path: str


def load_feature_code_map(path: Path) -> Dict[str, str]:
    """Load a YAML feature-code -> layer-name mapping.

    Expected shape: ``{"MW": "MonitoringWells", "GCP": "DroneControlPoints"}``.
    An optional ``"default"`` key is used for unmapped feature codes in place
    of the built-in ``Miscellaneous`` fallback.
    """
    import yaml
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in raw.items()}


def group_points_by_layer(
    points: List[RTKPoint],
    feature_code_map: Dict[str, str],
    *,
    qa: QACollector,
) -> Dict[str, List[RTKPoint]]:
    """Group RTK points by mapped layer name.

    Points with a blank feature code, or a code absent from the map, are
    routed to ``feature_code_map["default"]`` (or ``Miscellaneous`` if no
    default is configured) rather than dropped.
    """
    default_layer = feature_code_map.get("default", _DEFAULT_LAYER)
    layers: Dict[str, List[RTKPoint]] = {}
    unmapped_codes = set()
    for pt in points:
        code = pt.feature_code.strip()
        layer = feature_code_map.get(code, default_layer) if code else default_layer
        if code and code not in feature_code_map:
            unmapped_codes.add(code)
        layers.setdefault(layer, []).append(pt)

    if unmapped_codes:
        qa.add(SEV_WARNING, "unmapped_feature_codes",
               f"{len(unmapped_codes)} feature code(s) had no mapping, routed to "
               f"{default_layer!r}: {', '.join(sorted(unmapped_codes))}")
    return layers


def write_layer_csv(points: List[RTKPoint], output_path: Path) -> None:
    """Write one CSV per layer (x=Easting, y=Northing, z=Elevation_ft)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["point_id", "x", "y", "z", "feature_code", "description"])
        for pt in points:
            writer.writerow([pt.point_id, pt.easting, pt.northing, pt.elevation_ft,
                              pt.feature_code, pt.description])


def write_layer_geojson(points: List[RTKPoint], output_path: Path) -> None:
    """Write one GeoJSON FeatureCollection per layer.

    Coordinates (x=Easting, y=Northing) pass through in the caller's CRS
    unprojected, matching the existing ``export-geojson`` tool's convention.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [pt.easting, pt.northing, pt.elevation_ft],
            },
            "properties": {
                "point_id": pt.point_id,
                "feature_code": pt.feature_code,
                "description": pt.description,
            },
        }
        for pt in points
    ]
    output_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
        encoding="utf-8",
    )


def export_survey_to_cad_gis(
    points: List[RTKPoint],
    feature_code_map: Dict[str, str],
    output_dir: Path,
    *,
    write_geojson: bool = False,
    qa: QACollector,
) -> List[LayerManifestEntry]:
    """Export RTK survey points to per-layer CSV (+ optional GeoJSON) files.

    Writes ``manifest.json`` to ``output_dir`` and returns the same manifest
    as a list of LayerManifestEntry, one per layer written.
    """
    output_dir = Path(output_dir)
    if not points:
        qa.add(SEV_INFO, "no_points", "No survey points provided; nothing exported.")
        return []

    layers = group_points_by_layer(points, feature_code_map, qa=qa)

    # Sanitize layer names for filesystem safety; merge any raw names that
    # collide after sanitization rather than letting one overwrite another.
    safe_layers: Dict[str, List[RTKPoint]] = {}
    for raw_name, layer_points in layers.items():
        safe_name = _sanitize_layer_name(raw_name, qa=qa)
        safe_layers.setdefault(safe_name, []).extend(layer_points)

    manifest: List[LayerManifestEntry] = []
    for layer_name, layer_points in sorted(safe_layers.items()):
        csv_path = output_dir / f"{layer_name}.csv"
        write_layer_csv(layer_points, csv_path)
        if write_geojson:
            write_layer_geojson(layer_points, output_dir / f"{layer_name}.geojson")
        codes = sorted({p.feature_code for p in layer_points if p.feature_code})
        manifest.append(LayerManifestEntry(
            layer_name=layer_name,
            feature_codes=";".join(codes),
            point_count=len(layer_points),
            output_path=str(csv_path),
        ))

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps([dataclasses.asdict(m) for m in manifest], indent=2),
        encoding="utf-8",
    )

    qa.add(SEV_INFO, "export_survey_cad_complete",
           f"Exported {len(points)} point(s) to {len(manifest)} layer(s) in {output_dir}")
    return manifest
