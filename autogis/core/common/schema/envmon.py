# autogis/core/common/schema/envmon.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import ClassVar, Optional


@dataclass
class EnvSample:
    table_name: ClassVar[str] = "Env_Samples"
    site_id: str
    location_id: str
    event_date: date
    matrix: str
    sample_id: str
    depth_top_ft: Optional[float] = None
    depth_bot_ft: Optional[float] = None
    sampled_by: str = ""
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class EnvAnalyticalResult:
    table_name: ClassVar[str] = "Env_AnalyticalResults"
    sample_id: str
    analyte: str
    result: Optional[float]
    units: str
    qualifier: str = ""
    reporting_limit: Optional[float] = None
    method: str = ""
    lab: str = ""
    is_nondetect: bool = False
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class EnvImportQA:
    table_name: ClassVar[str] = "Env_ImportQA"
    run_id: str
    severity: str
    category: str
    message: str
    site_id: str = ""
    location_id: str = ""
    sample_id: str = ""
    source_row: Optional[int] = None
    source_sheet: str = ""
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class EnvWaterLevelEvent:
    table_name: ClassVar[str] = "Env_CurrentWaterLevelEvent"
    site_id: str
    location_id: str
    event_date: date
    dtw_ft: Optional[float]
    gwe_ft: Optional[float]
    status: str
    use_for_model: bool = True
    exclusion_reason: str = ""
    measured_by: str = ""
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)
