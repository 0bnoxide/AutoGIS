# autogis/core/common/schema/survey.py
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import ClassVar, Optional
import json


@dataclass
class SurveyPointRaw:
    table_name: ClassVar[str] = "SurveyPoints_Raw"
    point_id: str
    northing: Optional[float]
    easting: Optional[float]
    elevation: Optional[float]
    feature_code: str = ""
    description: str = ""
    hrms: Optional[float] = None
    vrms: Optional[float] = None
    fix_type: str = ""
    correction_source: str = ""
    occupation_time_s: Optional[float] = None
    rod_height: Optional[float] = None
    collected_at: Optional[str] = None
    operator: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class SurveyPointQA:
    table_name: ClassVar[str] = "SurveyPoints_QA"
    point_id: str
    qa_status: str
    qa_flags: list = field(default_factory=list)
    approved: bool = False

    def to_row(self) -> dict:
        d = asdict(self)
        d["qa_flags"] = json.dumps(d["qa_flags"])
        return d


@dataclass
class LevelLoopRun:
    table_name: ClassVar[str] = "LevelLoopRuns"
    run_id: str
    site_id: str
    survey_date: date
    benchmark_id: str
    known_elevation: float
    misclosure_ft: Optional[float] = None
    closure_tolerance_ft: Optional[float] = None
    adjusted: bool = False
    operator: str = ""
    notes: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class LevelLoopObservation:
    table_name: ClassVar[str] = "LevelLoopObservations"
    run_id: str
    setup_id: str
    point_id: str
    backsight: Optional[float] = None
    foresight: Optional[float] = None
    intermediate_sight: Optional[float] = None
    hi: Optional[float] = None
    elevation: Optional[float] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class ElevationHistory:
    table_name: ClassVar[str] = "ElevationHistory"
    location_id: str
    elevation_type: str
    elevation: float
    vertical_datum: str
    survey_date: date
    survey_method: str
    source_run_id: str
    approved_for_use: bool
    superseded: bool

    def to_row(self) -> dict:
        return asdict(self)
