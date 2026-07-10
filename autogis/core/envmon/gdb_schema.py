"""Geodatabase schema + record dataclasses.

Schema dictionaries and record dataclasses are pure Python (importable by the
normalizers and unit tests without ArcGIS). create_or_update_gdb_schema()
imports arcpy lazily and is additive only: missing tables/fields are created,
nothing is ever deleted.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from datetime import date
from typing import Optional

# field tuples: (name, esri_type, length_or_None)
T = "TEXT"; D = "DOUBLE"; L = "LONG"; DT = "DATE"; SH = "SHORT"

_SRC = [("SourceWorkbook", T, 255), ("SourceSheet", T, 64),
        ("SourceRow", L, None), ("SourceColumn", T, 8), ("SourceCell", T, 12)]

TABLE_SCHEMAS = {
    "Env_ImportBatch": [
        ("ImportBatchID", T, 64), ("SiteID", T, 32), ("SiteName", T, 128),
        ("SourceWorkbook", T, 255), ("SourceWorkbookHash", T, 64),
        ("ImportDateTime", DT, None), ("ImportedBy", T, 64),
        ("ParserProfile", T, 128), ("EventDate", DT, None),
        ("ImportMode", T, 32), ("QAStatus", T, 16), ("SourceSheets", T, 512),
        ("AnalyticalRecordCount", L, None), ("WaterLevelRecordCount", L, None),
        ("SoilRecordCount", L, None), ("MetalRecordCount", L, None),
        ("IBIRecordCount", L, None), ("RPDRecordCount", L, None),
        ("WarningCount", L, None), ("ErrorCount", L, None), ("Notes", T, 512)],
    "Env_WaterLevels": [
        ("ImportBatchID", T, 64), ("SiteID", T, 32), ("LocationID", T, 32),
        ("EventDate", DT, None), ("SampleDateRaw", T, 64),
        ("MonitoringPointElevation_ft", D, None), ("DepthToWater_ft", D, None),
        ("GroundwaterElevation_ft", D, None),
        ("GroundwaterElevationRawText", T, 64), ("IsDry", SH, None),
        ("IsMeasured", SH, None), ("MeasurementStatus", T, 16),
        ("UseForContour", SH, None), ("ExclusionReason", T, 128),
        ("SourceWorkbook", T, 255), ("SourceSheet", T, 64),
        ("SourceRow", L, None), ("SourceColumn_MPE", T, 8),
        ("SourceColumn_DTW", T, 8), ("SourceColumn_GWE", T, 8)],
    "Env_Samples": [
        ("ImportBatchID", T, 64), ("SiteID", T, 32), ("Matrix", T, 16),
        ("LocationID", T, 32), ("SampleID", T, 64), ("ParentSampleID", T, 64),
        ("SampleDate", DT, None), ("SampleDateRaw", T, 64),
        ("DepthTop_ft", D, None), ("DepthBottom_ft", D, None),
        ("DepthIntervalText", T, 32), ("IsDuplicate", SH, None),
        ("DuplicateType", T, 32), ("LabSampleID", T, 64)] + _SRC[:3],
    "Env_AnalyticalResults": [
        ("ImportBatchID", T, 64), ("SiteID", T, 32), ("Matrix", T, 16),
        ("LocationID", T, 32), ("SampleID", T, 64), ("ParentSampleID", T, 64),
        ("SampleDate", DT, None), ("DepthTop_ft", D, None),
        ("DepthBottom_ft", D, None), ("DepthIntervalText", T, 32),
        ("AnalyticalGroup", T, 32), ("MethodGroup", T, 32),
        ("AnalyteName", T, 128), ("AnalyteCanonicalName", T, 128),
        ("AnalyteAbbreviation", T, 32), ("ResultRawText", T, 64),
        ("ResultNumeric", D, None), ("ReportingLimit", D, None),
        ("DetectionLimit", D, None), ("Units", T, 16), ("Qualifier", T, 16),
        ("IsNonDetect", SH, None), ("IsDetected", SH, None),
        ("IsEstimated", SH, None), ("IsDiluted", SH, None),
        ("IsNotAnalyzed", SH, None), ("IsNotSampled", SH, None),
        ("IsNotMeasured", SH, None), ("ScreeningLevel", D, None),
        ("ScreeningLevelSource", T, 64), ("ExceedsScreeningLevel", SH, None),
        ("DisplayText", T, 64), ("DisplayColorClass", T, 16),
        # --- Step-1 canonical expansion (ADR-0075, SCHEMA_VERSION 2.2) ---
        ("ResultFraction", T, 32), ("QCType", T, 32),
        ("MethodDilutionKey", T, 64), ("MethodID", T, 64),
        ("MethodName", T, 128), ("AnalysisDate", DT, None),
        ("LimitType", T, 32), ("LabName", T, 128),
        ("PrepMethodID", T, 64), ("PrepDate", DT, None),
        ("ResultBasis", T, 16), ("MethodSpeciation", T, 32)] + _SRC,
    "Env_RPDResults": [
        ("ImportBatchID", T, 64), ("SiteID", T, 32), ("EventDate", DT, None),
        ("ParentLocationID", T, 32), ("DuplicateLocationID", T, 32),
        ("AnalyteName", T, 128), ("ParentResultRaw", T, 64),
        ("DuplicateResultRaw", T, 64), ("ParentResultNumeric", D, None),
        ("DuplicateResultNumeric", D, None), ("RPDValue", D, None),
        ("RL", D, None), ("FiveTimesRL", D, None), ("RPDStatus", T, 16),
        ("CalculationError", T, 128), ("SourceWorkbook", T, 255),
        ("SourceSheet", T, 64), ("SourceRow", L, None)],
    "Env_ImportQA": [
        ("ImportBatchID", T, 64), ("Severity", T, 12), ("Category", T, 64),
        ("SiteID", T, 32), ("LocationID", T, 32), ("SampleID", T, 64),
        ("SampleDate", T, 32), ("AnalyteName", T, 128), ("Message", T, 512),
        ("RecommendedAction", T, 256)] + _SRC,
    "Env_CalloutPlacementOverrides": [
        ("SiteID", T, 32), ("EventDate", DT, None), ("MapType", T, 32),
        ("FigureSpecID", T, 64), ("LocationID", T, 32), ("SampleID", T, 64),
        ("AnchorX", D, None), ("AnchorY", D, None), ("OffsetX", D, None),
        ("OffsetY", D, None), ("PreferredQuadrant", T, 4),
        ("LockedPlacement", SH, None), ("Notes", T, 256)],
    "Env_FigureRegistry": [
        ("FigureSpecID", T, 64), ("SiteID", T, 32), ("MapType", T, 32),
        ("FigureNumber", T, 16), ("FigureTitle", T, 256),
        ("EventDate", DT, None), ("LayoutName", T, 128),
        ("OutputFileName", T, 256), ("FigureSpecPath", T, 256),
        ("LastExportDate", DT, None), ("ExportStatus", T, 32)],
    "Env_CurrentEventWide": [
        ("SiteID", T, 32), ("FigureSpecID", T, 64), ("EventDate", DT, None),
        ("Matrix", T, 16), ("LocationID", T, 32), ("SampleID", T, 64),
        ("SampleDate", DT, None), ("DepthIntervalText", T, 32),
        ("HasExceedance", SH, None), ("HasDetection", SH, None),
        ("HasOnlyNonDetects", SH, None),
        ("HasMissingRequiredAnalytes", SH, None),
        ("LabelText_Fallback", T, 2000), ("ImportBatchID", T, 64)],

    # ------------------------------------------------------------------
    # Schema version tracking (v2 — added 2026-06-26)
    # ------------------------------------------------------------------
    "Env_SchemaVersion": [
        ("SchemaVersion", T, 16), ("UpgradedAt", DT, None),
        ("PreviousVersion", T, 16), ("TablesCreated", L, None),
        ("FieldsAdded", L, None), ("UpgradedBy", T, 64),
        ("Notes", T, 256)],

    # ------------------------------------------------------------------
    # Envmon extension
    # ------------------------------------------------------------------
    "Env_CurrentWaterLevelEvent": [
        ("SiteID", T, 32), ("LocationID", T, 32), ("EventDate", DT, None),
        ("DTW_ft", D, None), ("GWE_ft", D, None), ("Status", T, 32),
        ("UseForModel", SH, None), ("ExclusionReason", T, 128),
        ("MeasuredBy", T, 64), ("ImportBatchID", T, 64)],

    # ------------------------------------------------------------------
    # Boring domain
    # ------------------------------------------------------------------
    "BoringLocations": [
        ("BoringID", T, 32), ("SiteID", T, 32), ("LocationType", T, 32),
        ("Northing", D, None), ("Easting", D, None),
        ("GroundElevation_ft", D, None), ("TOCElevation_ft", D, None),
        ("Status", T, 32), ("CoordinateSystem", T, 64),
        ("VerticalDatum", T, 32), ("DrillingStartDate", DT, None),
        ("DrillingEndDate", DT, None), ("Driller", T, 64),
        ("LoggedBy", T, 64), ("TotalDepth_ft", D, None),
        ("CompletionType", T, 32)],
    "LithologyIntervals": [
        ("BoringID", T, 32), ("TopDepth_ft", D, None), ("BottomDepth_ft", D, None),
        ("USCS", T, 16), ("PrimaryMaterial", T, 64), ("SecondaryMaterial", T, 64),
        ("Color", T, 32), ("Moisture", T, 32), ("DensityConsistency", T, 32),
        ("Plasticity", T, 32), ("Odor", T, 32), ("Staining", T, 32),
        ("PID_ppm", D, None), ("Description", T, 512), ("GraphicPattern", T, 64),
        ("Reviewed", SH, None)],
    "BoringSamples": [
        ("SampleID", T, 64), ("BoringID", T, 32), ("SampleType", T, 32),
        ("TopDepth_ft", D, None), ("BottomDepth_ft", D, None),
        ("Recovery_pct", D, None), ("BlowCounts", T, 32),
        ("LabSubmitted", SH, None), ("Matrix", T, 16),
        ("AnalyticalGroup", T, 32), ("PhotoID", T, 64), ("COCNumber", T, 32)],
    "WellConstruction": [
        ("BoringID", T, 32), ("ComponentType", T, 32),
        ("TopDepth_ft", D, None), ("BottomDepth_ft", D, None),
        ("Diameter_in", D, None), ("Material", T, 64),
        ("SlotSize", T, 16), ("Notes", T, 256)],
    "GroundwaterObservations": [
        ("BoringID", T, 32), ("ObservationDatetime", DT, None),
        ("DepthToWater_ft", D, None), ("ObservationType", T, 32),
        ("ReferencePoint", T, 64), ("Notes", T, 256)],
    "BoringPhotos": [
        ("PhotoID", T, 64), ("BoringID", T, 32), ("SampleID", T, 64),
        ("Depth_ft", D, None), ("PhotoPath", T, 256), ("Caption", T, 256),
        ("TakenBy", T, 64), ("PhotoDatetime", DT, None)],
    "BoringComments": [
        ("CommentID", T, 64), ("BoringID", T, 32), ("Reviewer", T, 64),
        ("CommentText", T, 512), ("Severity", T, 16), ("AssignedTo", T, 64),
        ("Status", T, 32), ("ResolutionNote", T, 256), ("ResolvedDate", DT, None)],

    # ------------------------------------------------------------------
    # Survey domain
    # ------------------------------------------------------------------
    "SurveyPoints_Raw": [
        ("PointID", T, 64), ("Northing", D, None), ("Easting", D, None),
        ("Elevation_ft", D, None), ("FeatureCode", T, 32),
        ("Description", T, 256), ("HRMS_ft", D, None), ("VRMS_ft", D, None),
        ("PDOP", D, None), ("Satellites", L, None),
        ("FixType", T, 32), ("CorrectionSource", T, 64),
        ("OccupationTime_s", D, None), ("RodHeight_ft", D, None),
        ("CollectedAt", T, 32), ("Operator", T, 64)],
    "SurveyPoints_QA": [
        ("PointID", T, 64), ("QAStatus", T, 32),
        ("QAFlags", T, 512), ("Approved", SH, None)],
    "LevelLoopRuns": [
        ("RunID", T, 64), ("SiteID", T, 32), ("SurveyDate", DT, None),
        ("BenchmarkID", T, 32), ("KnownElevation_ft", D, None),
        ("Misclosure_ft", D, None), ("ClosureTolerance_ft", D, None),
        ("Adjusted", SH, None), ("Operator", T, 64), ("Notes", T, 256)],
    "LevelLoopObservations": [
        ("RunID", T, 64), ("SetupID", T, 32), ("PointID", T, 64),
        ("Backsight_ft", D, None), ("Foresight_ft", D, None),
        ("IntermediateSight_ft", D, None), ("HI_ft", D, None),
        ("Elevation_ft", D, None)],
    "ElevationHistory": [
        ("LocationID", T, 32), ("ElevationType", T, 32),
        ("Elevation_ft", D, None), ("VerticalDatum", T, 32),
        ("SurveyDate", DT, None), ("SurveyMethod", T, 64),
        ("SourceRunID", T, 64), ("ApprovedForUse", SH, None),
        ("Superseded", SH, None)],

    # ------------------------------------------------------------------
    # Drone domain
    # ------------------------------------------------------------------
    "DroneFlights": [
        ("FlightID", T, 64), ("ProjectID", T, 32), ("SiteID", T, 32),
        ("FlightDate", DT, None), ("Pilot", T, 64), ("DroneModel", T, 64),
        ("Sensor", T, 64), ("FlightAltitude_m", D, None),
        ("OverlapForward_pct", D, None), ("OverlapSide_pct", D, None),
        ("GCPUsed", SH, None), ("CheckpointCount", L, None),
        ("ProcessingSoftware", T, 64), ("OutputCRS", T, 64),
        ("VerticalDatum", T, 32), ("OrthomosaicPath", T, 256),
        ("DSMPath", T, 256), ("DEMPath", T, 256),
        ("PointCloudPath", T, 256), ("QAStatus", T, 32)],
    "DroneControlPoints": [
        ("PointID", T, 64), ("FlightID", T, 64),
        ("Northing", D, None), ("Easting", D, None), ("Elevation_ft", D, None),
        ("PointType", T, 16), ("ResidualH_m", D, None), ("ResidualV_m", D, None)],
    "DroneCheckpoints": [
        ("CheckpointID", T, 64), ("FlightID", T, 64),
        ("Northing", D, None), ("Easting", D, None), ("Elevation_ft", D, None),
        ("ResidualH_m", D, None), ("ResidualV_m", D, None),
        ("WithinTolerance", SH, None)],
    "DroneProductRegistry": [
        ("ProductID", T, 64), ("FlightID", T, 64), ("ProductType", T, 32),
        ("ProductPath", T, 256), ("CRS", T, 64), ("VerticalDatum", T, 32),
        ("Resolution_m", D, None), ("QAStatus", T, 32)],

    # ------------------------------------------------------------------
    # Dashboard domain
    # ------------------------------------------------------------------
    "Dash_SiteStatus": [
        ("SiteID", T, 32), ("SiteName", T, 128),
        ("ActiveEvents", L, None), ("OpenQAIssues", L, None),
        ("ReportDueDate", DT, None), ("LastUpdated", T, 32)],
    "Dash_EventStatus": [
        ("SiteID", T, 32), ("EventID", T, 64),
        ("WellsPlanned", L, None), ("WellsSampled", L, None),
        ("LabReceived", SH, None), ("FiguresReady", SH, None),
        ("ReportReady", SH, None), ("LastUpdated", T, 32)],
    "Dash_WellStatus": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("Status", T, 32), ("GWE_ft", D, None), ("GWEDelta_ft", D, None),
        ("LastUpdated", T, 32)],
    "Dash_CurrentExceedances": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("Analyte", T, 128), ("Result", D, None), ("Units", T, 16),
        ("ScreeningLevel", D, None), ("ScreeningSource", T, 64),
        ("LastUpdated", T, 32)],
    "Dash_GWLevelSummary": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("GWE_ft", D, None), ("PriorGWE_ft", D, None), ("Delta_ft", D, None),
        ("Trend", T, 16), ("LastUpdated", T, 32)],
    "Dash_AnalyticalSummary": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("Analyte", T, 128), ("Result", D, None), ("Units", T, 16),
        ("IsDetection", SH, None), ("IsExceedance", SH, None),
        ("LastUpdated", T, 32)],
    "Dash_FieldQA": [
        ("SiteID", T, 32), ("EventID", T, 64), ("IssueType", T, 32),
        ("LocationID", T, 32), ("Description", T, 256), ("LastUpdated", T, 32)],
    "Dash_LabQA": [
        ("SiteID", T, 32), ("EventID", T, 64), ("IssueType", T, 32),
        ("LocationID", T, 32), ("Analyte", T, 128),
        ("Description", T, 256), ("LastUpdated", T, 32)],
    "Dash_OpenIssues": [
        ("SiteID", T, 32), ("EventID", T, 64), ("Domain", T, 32),
        ("Severity", T, 16), ("Description", T, 256),
        ("AssignedTo", T, 64), ("LastUpdated", T, 32)],
    "Dash_ReportReadiness": [
        ("SiteID", T, 32), ("EventID", T, 64),
        ("FieldReady", SH, None), ("LabReady", SH, None),
        ("GISReady", SH, None), ("QAReady", SH, None),
        ("ModelReady", SH, None), ("ReportReady", SH, None),
        ("OverallReady", SH, None), ("LastUpdated", T, 32)],
}

FEATURE_SCHEMAS = {
    # name: (geometry_type, fields). MonitoringWells/SoilBorings are usually
    # pre-existing site layers; created as placeholders + QA when missing.
    "MonitoringWells": ("POINT", [
        ("SiteID", T, 32), ("LocationID", T, 32), ("WellID", T, 32),
        ("WellType", T, 32), ("Status", T, 32), ("GroundElev_ft", D, None),
        ("TOC_ft", D, None), ("ScreenTop_ft", D, None),
        ("ScreenBottom_ft", D, None), ("InstallDate", DT, None),
        ("AbandonDate", DT, None), ("Notes", T, 256)]),
    "SoilBorings": ("POINT", [
        ("SiteID", T, 32), ("LocationID", T, 32), ("BoringType", T, 32),
        ("Status", T, 32), ("GroundElev_ft", D, None),
        ("TotalDepth_ft", D, None), ("Notes", T, 256)]),
    "Env_CalloutBoxes": ("POLYGON", [
        ("SiteID", T, 32), ("EventDate", DT, None), ("MapType", T, 32),
        ("FigureSpecID", T, 64), ("LocationID", T, 32), ("SampleID", T, 64),
        ("Matrix", T, 16), ("CalloutID", T, 64), ("AnchorX", D, None),
        ("AnchorY", D, None), ("WidthMapUnits", D, None),
        ("HeightMapUnits", D, None), ("PlacementMethod", T, 32),
        ("PlacementQuadrant", T, 4), ("CollisionScore", D, None),
        ("PlacementLocked", SH, None), ("CollisionStatus", T, 32),
        ("ImportBatchID", T, 64)]),
    "Env_CalloutGridLines": ("POLYLINE", [
        ("SiteID", T, 32), ("EventDate", DT, None), ("MapType", T, 32),
        ("FigureSpecID", T, 64), ("LocationID", T, 32), ("CalloutID", T, 64),
        ("GridLineType", T, 16), ("RowNum", L, None), ("ColNum", L, None),
        ("StyleClass", T, 32)]),
    "Env_CalloutLeaderLines": ("POLYLINE", [
        ("SiteID", T, 32), ("EventDate", DT, None), ("MapType", T, 32),
        ("FigureSpecID", T, 64), ("LocationID", T, 32), ("SampleID", T, 64),
        ("CalloutID", T, 64), ("LeaderStyle", T, 32),
        ("SourcePointX", D, None), ("SourcePointY", D, None),
        ("TargetPointX", D, None), ("TargetPointY", D, None)]),
    "Env_CalloutCellAnchors": ("POINT", [
        ("SiteID", T, 32), ("EventDate", DT, None), ("MapType", T, 32),
        ("FigureSpecID", T, 64), ("LocationID", T, 32), ("SampleID", T, 64),
        ("Matrix", T, 16), ("CalloutID", T, 64), ("RowNum", L, None),
        ("ColNum", L, None), ("RowSpan", L, None), ("ColSpan", L, None),
        ("TextValue", T, 128), ("TextRawValue", T, 128),
        ("TextStyleClass", T, 32), ("DisplayColorClass", T, 16),
        ("IsHeader", SH, None), ("IsGroupHeader", SH, None),
        ("IsAnalyteName", SH, None), ("IsResultValue", SH, None),
        ("IsExceedance", SH, None), ("IsDetected", SH, None),
        ("IsNonDetect", SH, None), ("IsNotSampled", SH, None),
        ("HorizontalAlignment", T, 8), ("VerticalAlignment", T, 8),
        ("FontSize", D, None), ("Rotation", D, None),
        ("SourceAnalyteName", T, 128), ("SourceFieldName", T, 64)]),
    "Env_GWContourPoints": ("POINT", [
        ("SiteID", T, 32), ("EventDate", DT, None), ("LocationID", T, 32),
        ("GroundwaterElevation_ft", D, None), ("UseForContour", SH, None),
        ("ExclusionReason", T, 128)]),
    "Env_GWContours_Draft": ("POLYLINE", [
        ("SiteID", T, 32), ("EventDate", DT, None),
        ("ContourElevation", D, None), ("ContourInterval", D, None),
        ("InterpolationMethod", T, 32), ("ReviewStatus", T, 16),
        ("Reviewer", T, 64), ("ReviewDate", DT, None), ("Notes", T, 256)]),
    "Env_GWFlowArrow_Draft": ("POLYLINE", [
        ("SiteID", T, 32), ("EventDate", DT, None),
        ("PlacementMethod", T, 32), ("ReviewStatus", T, 16),
        ("Notes", T, 256)]),
    "Env_PlumeBoundary_Draft": ("POLYGON", [
        ("SiteID", T, 32), ("AnalyteFilter", T, 128), ("HullMethod", T, 16),
        ("KNeighbors", L, None), ("NExceedancePoints", L, None),
        ("ReviewStatus", T, 16), ("Notes", T, 256)]),
}

UNIQUE_KEYS = {
    "Env_WaterLevels": ["SiteID", "LocationID", "EventDate"],
    "Env_Samples": ["SiteID", "Matrix", "SampleID", "SampleDate"],
    "Env_AnalyticalResults": ["SiteID", "Matrix", "LocationID", "SampleID",
                              "SampleDate", "AnalyteCanonicalName",
                              "DepthIntervalText", "SourceCell",
                              "ResultFraction", "QCType",
                              "MethodDilutionKey"],
    "Env_RPDResults": ["SiteID", "EventDate", "ParentLocationID",
                       "AnalyteName"],
}


def _norm_key_part(v):
    """Normalize one key part exactly as the idempotent-append dedup does.

    NULL and empty-string collapse to the same key part: an existing GDB row
    read back with a NULL discriminator (arcpy yields ``None``) must dedup
    against a freshly normalized record whose defaulted discriminator is
    ``""`` — otherwise a self-heal schema upgrade re-imports the same legacy
    source as a duplicate (ADR-0075)."""
    if v is None:
        return ""
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        return v.strip().upper()
    return v


def compute_unique_key(record_dict: dict, table_name: str) -> tuple:
    """The exact key append_records_idempotent dedups on. Pure, arcpy-free —
    the load-bearing seam the synthetic key-distinctness tests exercise."""
    return tuple(_norm_key_part(record_dict.get(k))
                 for k in UNIQUE_KEYS[table_name])


# ---------------------------------------------------------------------------
# Record dataclasses produced by normalizers (field names == schema names)
# ---------------------------------------------------------------------------
@dataclass
class WaterLevelRecord:
    ImportBatchID: str; SiteID: str; LocationID: str
    EventDate: Optional[date]; SampleDateRaw: str
    MonitoringPointElevation_ft: Optional[float]
    DepthToWater_ft: Optional[float]
    GroundwaterElevation_ft: Optional[float]
    GroundwaterElevationRawText: str
    IsDry: int; IsMeasured: int; MeasurementStatus: str
    UseForContour: int; ExclusionReason: str
    SourceWorkbook: str; SourceSheet: str; SourceRow: int
    SourceColumn_MPE: str = ""; SourceColumn_DTW: str = ""
    SourceColumn_GWE: str = ""


@dataclass
class SampleRecord:
    ImportBatchID: str; SiteID: str; Matrix: str; LocationID: str
    SampleID: str; ParentSampleID: str; SampleDate: Optional[date]
    SampleDateRaw: str; DepthTop_ft: Optional[float]
    DepthBottom_ft: Optional[float]; DepthIntervalText: str
    IsDuplicate: int; DuplicateType: str; LabSampleID: str
    SourceWorkbook: str; SourceSheet: str; SourceRow: int


@dataclass
class AnalyticalResultRecord:
    ImportBatchID: str; SiteID: str; Matrix: str; LocationID: str
    SampleID: str; ParentSampleID: str; SampleDate: Optional[date]
    DepthTop_ft: Optional[float]; DepthBottom_ft: Optional[float]
    DepthIntervalText: str; AnalyticalGroup: str; MethodGroup: str
    AnalyteName: str; AnalyteCanonicalName: str; AnalyteAbbreviation: str
    ResultRawText: str; ResultNumeric: Optional[float]
    ReportingLimit: Optional[float]; DetectionLimit: Optional[float]
    Units: str; Qualifier: str
    IsNonDetect: int; IsDetected: int; IsEstimated: int; IsDiluted: int
    IsNotAnalyzed: int; IsNotSampled: int; IsNotMeasured: int
    ScreeningLevel: Optional[float]; ScreeningLevelSource: str
    ExceedsScreeningLevel: Optional[int]
    DisplayText: str; DisplayColorClass: str
    SourceWorkbook: str; SourceSheet: str; SourceRow: int
    SourceColumn: str; SourceCell: str
    # --- Step-1 canonical expansion (ADR-0075). Key discriminators default
    # "" (never None — idempotency); dates are not key parts, default None.
    ResultFraction: str = ""
    QCType: str = ""
    MethodDilutionKey: str = ""
    MethodID: str = ""
    MethodName: str = ""
    AnalysisDate: Optional[date] = None
    LimitType: str = ""
    LabName: str = ""
    PrepMethodID: str = ""
    PrepDate: Optional[date] = None
    ResultBasis: str = ""
    MethodSpeciation: str = ""


@dataclass
class RPDRecord:
    ImportBatchID: str; SiteID: str; EventDate: Optional[date]
    ParentLocationID: str; DuplicateLocationID: str; AnalyteName: str
    ParentResultRaw: str; DuplicateResultRaw: str
    ParentResultNumeric: Optional[float]
    DuplicateResultNumeric: Optional[float]
    RPDValue: Optional[float]; RL: Optional[float]
    FiveTimesRL: Optional[float]; RPDStatus: str; CalculationError: str
    SourceWorkbook: str; SourceSheet: str; SourceRow: int


# ---------------------------------------------------------------------------
# arcpy schema creation (lazy import)
# ---------------------------------------------------------------------------
def create_or_update_gdb_schema(gdb_path, spatial_reference=None,
                                qa=None):  # pragma: no cover - requires arcpy
    """Create the file GDB plus any missing tables/feature classes/fields.

    Additive only. Pre-existing user feature classes (MonitoringWells,
    SoilBorings) are left untouched if present; if absent they are created as
    empty placeholder schemas and a QA ERROR is raised instead of inventing
    geometry (spec: missing inputs -> placeholder schema + QA error).
    """
    import arcpy
    from pathlib import Path as _P
    from ..common.qa import QACollector, SEV_ERROR
    qa = qa or QACollector()
    gdb_path = _P(gdb_path)
    if not gdb_path.exists():
        arcpy.management.CreateFileGDB(str(gdb_path.parent), gdb_path.name)
    sr = spatial_reference or arcpy.SpatialReference(4326)

    def _ensure_fields(target, fields):
        existing = {f.name.upper() for f in arcpy.ListFields(target)}
        for name, ftype, length in fields:
            if name.upper() not in existing:
                arcpy.management.AddField(target, name, ftype,
                                          field_length=length or None)

    for name, fields in TABLE_SCHEMAS.items():
        target = str(gdb_path / name)
        if not arcpy.Exists(target):
            arcpy.management.CreateTable(str(gdb_path), name)
        _ensure_fields(target, fields)
    for name, (geom, fields) in FEATURE_SCHEMAS.items():
        target = str(gdb_path / name)
        if not arcpy.Exists(target):
            arcpy.management.CreateFeatureclass(
                str(gdb_path), name, geom, spatial_reference=sr)
            if name in ("MonitoringWells", "SoilBorings"):
                qa.add(SEV_ERROR, "missing_required_map_layer",
                       f"{name} did not exist; an EMPTY placeholder was "
                       f"created. Populate it with surveyed locations before "
                       f"producing figures.",
                       recommended_action=f"load real {name} features")
        _ensure_fields(target, fields)
    return qa
