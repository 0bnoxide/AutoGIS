# autogis/core/common/schema/boring.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import ClassVar, Optional


@dataclass
class BoringLocation:
    table_name: ClassVar[str] = "BoringLocations"
    boring_id: str
    site_id: str
    location_type: str
    northing: Optional[float]
    easting: Optional[float]
    ground_elevation: Optional[float]
    toc_elevation: Optional[float]
    status: str
    coordinate_system: str = ""
    vertical_datum: str = ""
    drilling_start_date: Optional[date] = None
    drilling_end_date: Optional[date] = None
    driller: str = ""
    logged_by: str = ""
    total_depth_ft: Optional[float] = None
    completion_type: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class LithologyInterval:
    table_name: ClassVar[str] = "LithologyIntervals"
    boring_id: str
    top_depth: float
    bottom_depth: float
    uscs: str = ""
    primary_material: str = ""
    secondary_material: str = ""
    color: str = ""
    moisture: str = ""
    density_consistency: str = ""
    plasticity: str = ""
    odor: str = ""
    staining: str = ""
    pid_ppm: Optional[float] = None
    description: str = ""
    graphic_pattern: str = ""
    reviewed: bool = False

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class BoringSample:
    table_name: ClassVar[str] = "BoringSamples"
    sample_id: str
    boring_id: str
    sample_type: str
    top_depth: float
    bottom_depth: float
    recovery: Optional[float] = None
    blow_counts: Optional[str] = None
    lab_submitted: bool = False
    matrix: str = ""
    analytical_group: str = ""
    photo_id: str = ""
    coc_number: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class WellConstruction:
    table_name: ClassVar[str] = "WellConstruction"
    boring_id: str
    component_type: str
    top_depth: float
    bottom_depth: float
    diameter: Optional[float] = None
    material: str = ""
    slot_size: str = ""
    notes: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class GroundwaterObservation:
    table_name: ClassVar[str] = "GroundwaterObservations"
    boring_id: str
    observation_datetime: Optional[datetime]
    depth_to_water: Optional[float]
    observation_type: str = ""
    reference_point: str = ""
    notes: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class BoringPhoto:
    table_name: ClassVar[str] = "BoringPhotos"
    photo_id: str
    boring_id: str
    sample_id: str = ""
    depth: Optional[float] = None
    photo_path: str = ""
    caption: str = ""
    taken_by: str = ""
    datetime: Optional[datetime] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class BoringComment:
    table_name: ClassVar[str] = "BoringComments"
    comment_id: str
    boring_id: str
    reviewer: str = ""
    comment_text: str = ""
    severity: str = ""
    assigned_to: str = ""
    status: str = "open"
    resolution_note: str = ""
    resolved_date: Optional[date] = None

    def to_row(self) -> dict:
        return asdict(self)
