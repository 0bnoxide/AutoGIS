# autogis/core/common/schema/dashboard.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import ClassVar, Optional


@dataclass
class DashSiteStatus:
    table_name: ClassVar[str] = "Dash_SiteStatus"
    site_id: str
    site_name: str = ""
    active_events: int = 0
    open_qa_issues: int = 0
    report_due_date: Optional[date] = None
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashEventStatus:
    table_name: ClassVar[str] = "Dash_EventStatus"
    site_id: str
    event_id: str
    wells_planned: int = 0
    wells_sampled: int = 0
    lab_received: bool = False
    figures_ready: bool = False
    report_ready: bool = False
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashWellStatus:
    table_name: ClassVar[str] = "Dash_WellStatus"
    site_id: str
    event_id: str
    location_id: str
    status: str = ""
    gwe_ft: Optional[float] = None
    gwe_delta_ft: Optional[float] = None
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashCurrentExceedances:
    table_name: ClassVar[str] = "Dash_CurrentExceedances"
    site_id: str
    event_id: str
    location_id: str
    analyte: str
    result: Optional[float] = None
    units: str = ""
    screening_level: Optional[float] = None
    screening_source: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashGWLevelSummary:
    table_name: ClassVar[str] = "Dash_GWLevelSummary"
    site_id: str
    event_id: str
    location_id: str
    gwe_ft: Optional[float] = None
    prior_gwe_ft: Optional[float] = None
    delta_ft: Optional[float] = None
    trend: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashAnalyticalSummary:
    table_name: ClassVar[str] = "Dash_AnalyticalSummary"
    site_id: str
    event_id: str
    location_id: str
    analyte: str
    result: Optional[float] = None
    units: str = ""
    is_detection: bool = False
    is_exceedance: bool = False
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashFieldQA:
    table_name: ClassVar[str] = "Dash_FieldQA"
    site_id: str
    event_id: str
    issue_type: str = ""
    location_id: str = ""
    description: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashLabQA:
    table_name: ClassVar[str] = "Dash_LabQA"
    site_id: str
    event_id: str
    issue_type: str = ""
    location_id: str = ""
    analyte: str = ""
    description: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashOpenIssues:
    table_name: ClassVar[str] = "Dash_OpenIssues"
    site_id: str
    event_id: str
    domain: str = ""
    severity: str = ""
    description: str = ""
    assigned_to: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashReportReadiness:
    table_name: ClassVar[str] = "Dash_ReportReadiness"
    site_id: str
    event_id: str
    field_ready: bool = False
    lab_ready: bool = False
    gis_ready: bool = False
    qa_ready: bool = False
    model_ready: bool = False
    report_ready: bool = False
    overall_ready: bool = False
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)
