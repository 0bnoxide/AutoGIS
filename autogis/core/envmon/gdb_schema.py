"""Geodatabase schema + record dataclasses.

Schema dictionaries and record dataclasses are pure Python (importable by the
normalizers and unit tests without ArcGIS). create_or_update_gdb_schema()
imports arcpy lazily and is additive only: missing tables/fields are created,
nothing is ever deleted.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import List, Optional

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
        ("DisplayText", T, 64), ("DisplayColorClass", T, 16)] + _SRC,
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
}

UNIQUE_KEYS = {
    "Env_WaterLevels": ["SiteID", "LocationID", "EventDate"],
    "Env_Samples": ["SiteID", "Matrix", "SampleID", "SampleDate"],
    "Env_AnalyticalResults": ["SiteID", "Matrix", "LocationID", "SampleID",
                              "SampleDate", "AnalyteCanonicalName",
                              "DepthIntervalText", "SourceCell"],
    "Env_RPDResults": ["SiteID", "EventDate", "ParentLocationID",
                       "AnalyteName"],
}


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


def record_to_row(record, field_names: List[str]) -> list:
    d = asdict(record) if not isinstance(record, dict) else record
    return [d.get(f) for f in field_names]


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
