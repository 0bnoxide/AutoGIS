"""Export analytical results to GeoJSON FeatureCollection (Tool 10.3).

No arcpy dependency. Pure stdlib: csv, collections. (The FeatureCollection is a
plain dict; JSON serialization happens at the CLI/caller boundary.)
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from .gdb_schema import AnalyticalResultRecord
from .canonical_read import canonical_records


def load_well_coords(path: Path) -> Dict[str, Tuple[float, float]]:
    """Load location_id -> (x, y) from a CSV with columns: location_id, x, y."""
    coords: Dict[str, Tuple[float, float]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            coords[row["location_id"]] = (float(row["x"]), float(row["y"]))
    return coords


def build_geojson(
    results: List[AnalyticalResultRecord],
    coords: Dict[str, Tuple[float, float]],
    *,
    qa: QACollector,
) -> dict:
    """Build a GeoJSON FeatureCollection from analytical results.

    One Feature per location. Properties include latest value, exceedance flag,
    and sample date for each analyte found at that location.

    Args:
        results: List of AnalyticalResultRecord (arcpy-free dataclass).
        coords: Mapping of location_id -> (x, y) in the CRS of your choice.
        qa: QACollector for warnings (e.g. missing coords).

    Returns:
        GeoJSON FeatureCollection dict (serialise with json.dumps).
    """
    results = canonical_records(results, qa)

    # Group by location
    by_loc: Dict[str, List[AnalyticalResultRecord]] = defaultdict(list)
    for r in results:
        if r.IsNotAnalyzed:
            continue
        by_loc[r.LocationID].append(r)

    features = []
    missing_coords: set = set()

    for loc_id, recs in sorted(by_loc.items()):
        if loc_id not in coords:
            missing_coords.add(loc_id)
            qa.add(
                SEV_WARNING, "missing_coords",
                f"Location {loc_id!r} has no coordinates; skipped.",
            )
            continue

        x, y = coords[loc_id]

        # Use the latest record per analyte (sort by SampleDate ascending; last wins)
        by_analyte: Dict[str, AnalyticalResultRecord] = {}
        for r in sorted(recs, key=lambda r: r.SampleDate or date.min):
            by_analyte[r.AnalyteCanonicalName] = r

        props: dict = {
            "location_id": loc_id,
            "site_id": recs[0].SiteID,
        }
        seen_keys: Dict[str, str] = {}
        for analyte, r in sorted(by_analyte.items()):
            safe_key = analyte.replace(" ", "_").replace(",", "").replace("/", "_")
            if safe_key in seen_keys:
                qa.add(
                    SEV_WARNING, "analyte_key_collision",
                    f"Location {loc_id!r}: analytes {seen_keys[safe_key]!r} and "
                    f"{analyte!r} map to the same property key {safe_key!r}; "
                    f"the latter overwrites the former.",
                )
            seen_keys[safe_key] = analyte
            props[f"{safe_key}_value"] = r.DisplayText or ""
            props[f"{safe_key}_exceeds"] = (
                bool(r.ExceedsScreeningLevel)
                if r.ExceedsScreeningLevel is not None
                else None
            )
            props[f"{safe_key}_date"] = (
                r.SampleDate.isoformat() if r.SampleDate else ""
            )

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": props,
        })

    qa.add(
        SEV_INFO, "export_geojson_complete",
        f"build_geojson: {len(features)} features from {len(by_loc)} locations; "
        f"{len(missing_coords)} location(s) skipped (no coords)",
    )
    return {"type": "FeatureCollection", "features": features}
