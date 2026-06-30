"""register_drone_flight.py — drone flight inventory YAML → DroneFlights GDB write.

``load_flight_yaml`` and ``validate_flight_record`` are arcpy-free and fully
unit-testable. ``write_drone_flight`` requires arcpy (ArcGIS Pro) and is marked
``# pragma: no cover``.

Reuses the canonical ``DroneFlight`` dataclass from
``autogis.core.common.schema.drone`` — no parallel record type.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from ..common.qa import QACollector, SEV_ERROR
from ..common.schema.drone import DroneFlight


def _coerce_date(value) -> date:
    """Accept a date, datetime, or ISO-8601 string; return a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _opt_float(value):
    return None if value is None else float(value)


def load_flight_yaml(path: Path) -> DroneFlight:
    """Load a drone flight inventory YAML into a :class:`DroneFlight`."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return DroneFlight(
        flight_id=str(data.get("flight_id", "")),
        project_id=str(data.get("project_id", "")),
        site_id=str(data.get("site_id", "")),
        flight_date=_coerce_date(data["flight_date"]) if data.get("flight_date") else date.min,
        pilot=str(data.get("pilot", "")),
        drone_model=str(data.get("drone_model", "")),
        sensor=str(data.get("sensor", "")),
        flight_altitude_m=_opt_float(data.get("flight_altitude_m")),
        overlap_forward_pct=_opt_float(data.get("overlap_forward_pct")),
        overlap_side_pct=_opt_float(data.get("overlap_side_pct")),
        gcp_used=bool(data.get("gcp_used", False)),
        checkpoint_count=int(data.get("checkpoint_count", 0)),
        processing_software=str(data.get("processing_software", "")),
        output_crs=str(data.get("output_crs", "")),
        vertical_datum=str(data.get("vertical_datum", "")),
        orthomosaic_path=str(data.get("orthomosaic_path", "")),
        dsm_path=str(data.get("dsm_path", "")),
        dem_path=str(data.get("dem_path", "")),
        point_cloud_path=str(data.get("point_cloud_path", "")),
        qa_status=str(data.get("qa_status", "pending")),
    )


def validate_flight_record(rec: DroneFlight, qa: QACollector) -> None:
    """Validate a :class:`DroneFlight`, writing issues to *qa*."""
    for f_name in ("flight_id", "site_id", "pilot", "drone_model", "sensor"):
        if not getattr(rec, f_name):
            qa.add(SEV_ERROR, "missing_required_field",
                   f"DroneFlight missing required field {f_name!r}")
    if rec.flight_date == date.min:
        qa.add(SEV_ERROR, "missing_required_field",
               "DroneFlight missing required field 'flight_date'")
    if rec.flight_altitude_m is not None and rec.flight_altitude_m <= 0:
        qa.add(SEV_ERROR, "invalid_altitude",
               f"flight_altitude_m must be positive, got {rec.flight_altitude_m}")


def write_drone_flight(  # pragma: no cover
    gdb_path: str,
    rec: DroneFlight,
) -> None:
    """Insert one DroneFlight row into the DroneFlights table (ArcGIS Pro)."""
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(_P(gdb_path) / "DroneFlights")
    if not _ax.Exists(table):
        return
    fields = [
        "FlightID", "ProjectID", "SiteID", "FlightDate", "Pilot", "DroneModel",
        "Sensor", "FlightAltitude_m", "OverlapForward_pct", "OverlapSide_pct",
        "GCPUsed", "CheckpointCount", "ProcessingSoftware", "OutputCRS",
        "VerticalDatum", "OrthomosaicPath", "DSMPath", "DEMPath",
        "PointCloudPath", "QAStatus",
    ]
    with _ax.da.InsertCursor(table, fields) as cur:
        cur.insertRow([
            rec.flight_id, rec.project_id, rec.site_id, rec.flight_date,
            rec.pilot, rec.drone_model, rec.sensor, rec.flight_altitude_m,
            rec.overlap_forward_pct, rec.overlap_side_pct, int(rec.gcp_used),
            rec.checkpoint_count, rec.processing_software, rec.output_crs,
            rec.vertical_datum, rec.orthomosaic_path, rec.dsm_path,
            rec.dem_path, rec.point_cloud_path, rec.qa_status,
        ])
