"""load_geostat_qa_gdb.py — build the scratch QA geodatabase (runs in Pro env).

Loads the synthetic CSVs written by ``make_geostat_qa_data.py`` into a fresh
file GDB with the real AutoGIS schema, so the geostat LOCAL tools run against
exactly the tables they read in production (MonitoringWells, Env_WaterLevels).

Run from the ArcGIS Pro conda env (arcgispro-py3-autogis) — see
docs/arcpy-environment.md:

    python docs/qa/load_geostat_qa_gdb.py
    python docs/qa/load_geostat_qa_gdb.py --data-dir DIR --gdb PATH

Defaults: data-dir = ~/Desktop/AutoGIS-QA/geostat, gdb = <data-dir>/QASITE.gdb
(re-running deletes and rebuilds the GDB — it is scratch by definition).
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

# UTM zone 18N (NAD83) — arbitrary but real; matches the generator's
# UTM-like meter coordinates.
EPSG = 26918


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_dir = Path.home() / "Desktop" / "AutoGIS-QA" / "geostat"
    ap.add_argument("--data-dir", type=Path, default=default_dir)
    ap.add_argument("--gdb", type=Path, default=None)
    args = ap.parse_args()
    gdb = args.gdb or (args.data_dir / "QASITE.gdb")

    import arcpy  # Pro env only — fails fast and loud anywhere else
    from autogis.core.envmon.gdb_schema import create_or_update_gdb_schema

    if arcpy.Exists(str(gdb)):
        arcpy.management.Delete(str(gdb))
        print(f"Deleted existing {gdb}")
    create_or_update_gdb_schema(
        gdb, spatial_reference=arcpy.SpatialReference(EPSG))
    print(f"Schema created: {gdb}")

    wells = _rows(args.data_dir / "wells.csv")
    fields = ["SHAPE@XY", "SiteID", "LocationID", "WellID", "WellType",
              "Status", "GroundElev_ft", "TOC_ft"]
    with arcpy.da.InsertCursor(str(gdb / "MonitoringWells"), fields) as cur:
        for w in wells:
            cur.insertRow(((float(w["X"]), float(w["Y"])), w["SiteID"],
                           w["LocationID"], w["WellID"], w["WellType"],
                           w["Status"], float(w["GroundElev_ft"]),
                           float(w["TOC_ft"])))
    print(f"Inserted {len(wells)} MonitoringWells")

    levels = _rows(args.data_dir / "waterlevels.csv")
    fields = ["SiteID", "LocationID", "EventDate",
              "GroundwaterElevation_ft", "IsDry", "IsMeasured",
              "MeasurementStatus", "UseForContour", "ExclusionReason"]
    with arcpy.da.InsertCursor(str(gdb / "Env_WaterLevels"), fields) as cur:
        for r in levels:
            gwe = r["GroundwaterElevation_ft"]
            cur.insertRow((r["SiteID"], r["LocationID"], r["EventDate"],
                           float(gwe) if gwe else None, int(r["IsDry"]),
                           int(r["IsMeasured"]), r["MeasurementStatus"],
                           int(r["UseForContour"]), r["ExclusionReason"]))
    print(f"Inserted {len(levels)} Env_WaterLevels rows")
    print(f"READY: {gdb} — proceed with docs/qa/geostat-live-pro-qa.md")


if __name__ == "__main__":
    main()
