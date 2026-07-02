# autogis/core/common/schema/__init__.py
from __future__ import annotations

# to_row() contract note: date and datetime fields are returned as Python objects
# (not strings). The arcpy adapter layer (autogis/adapters/) is responsible for
# converting these to the format expected by arcpy.da.InsertCursor — typically
# datetime.datetime for GDB DateTime fields. Do not call .isoformat() inside
# to_row(); keep the data model type-agnostic.

from .envmon import EnvSample, EnvAnalyticalResult, EnvImportQA, EnvWaterLevelEvent
from .boring import (
    BoringLocation, LithologyInterval, BoringSample, WellConstruction,
    GroundwaterObservation, BoringPhoto, BoringComment,
)
from .attachments import AttachmentIndex
from .survey import (
    SurveyPointRaw, SurveyPointQA, LevelLoopRun, LevelLoopObservation,
    ElevationHistory,
)
from .drone import DroneFlight, DroneControlPoint, DroneCheckpoint, DroneProductRecord
from .dashboard import (
    DashSiteStatus, DashEventStatus, DashWellStatus, DashCurrentExceedances,
    DashGWLevelSummary, DashAnalyticalSummary, DashFieldQA, DashLabQA,
    DashOpenIssues, DashReportReadiness,
)

__all__ = [
    "EnvSample", "EnvAnalyticalResult", "EnvImportQA", "EnvWaterLevelEvent",
    "BoringLocation", "LithologyInterval", "BoringSample", "WellConstruction",
    "GroundwaterObservation", "BoringPhoto", "BoringComment",
    "AttachmentIndex",
    "SurveyPointRaw", "SurveyPointQA", "LevelLoopRun", "LevelLoopObservation",
    "ElevationHistory",
    "DroneFlight", "DroneControlPoint", "DroneCheckpoint", "DroneProductRecord",
    "DashSiteStatus", "DashEventStatus", "DashWellStatus", "DashCurrentExceedances",
    "DashGWLevelSummary", "DashAnalyticalSummary", "DashFieldQA", "DashLabQA",
    "DashOpenIssues", "DashReportReadiness",
]
