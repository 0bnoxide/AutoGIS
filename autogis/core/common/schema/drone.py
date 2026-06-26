# autogis/core/common/schema/drone.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import ClassVar, Optional


@dataclass
class DroneFlight:
    table_name: ClassVar[str] = "DroneFlights"
    flight_id: str
    project_id: str
    site_id: str
    flight_date: date
    pilot: str = ""
    drone_model: str = ""
    sensor: str = ""
    flight_altitude_m: Optional[float] = None
    overlap_forward_pct: Optional[float] = None
    overlap_side_pct: Optional[float] = None
    gcp_used: bool = False
    checkpoint_count: int = 0
    processing_software: str = ""
    output_crs: str = ""
    vertical_datum: str = ""
    orthomosaic_path: str = ""
    dsm_path: str = ""
    dem_path: str = ""
    point_cloud_path: str = ""
    qa_status: str = "pending"

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DroneControlPoint:
    table_name: ClassVar[str] = "DroneControlPoints"
    point_id: str
    flight_id: str
    northing: float
    easting: float
    elevation: float
    point_type: str
    residual_h: Optional[float] = None
    residual_v: Optional[float] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DroneCheckpoint:
    table_name: ClassVar[str] = "DroneCheckpoints"
    checkpoint_id: str
    flight_id: str
    northing: float
    easting: float
    elevation: float
    residual_h: Optional[float] = None
    residual_v: Optional[float] = None
    within_tolerance: Optional[bool] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DroneProductRecord:
    table_name: ClassVar[str] = "DroneProductRegistry"
    product_id: str
    flight_id: str
    product_type: str
    path: str
    crs: str = ""
    vertical_datum: str = ""
    resolution_m: Optional[float] = None
    qa_status: str = "pending"

    def to_row(self) -> dict:
        return asdict(self)
