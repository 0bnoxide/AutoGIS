"""wqx_outbound.py — outbound EPA WQX submission mapping (Phase 8, slice 1).

Headless, arcpy-free. The outbound complement to ``wqx_reader`` (which reads a
WQP result CSV *into* canonical fields). This maps canonical result rows *out*
to WQX submission columns, validates the fields WQX requires, and packages
rejected records + provenance so nothing silently disappears.

*** DRAFT — the WQX column vocabulary is inherited from ``wqx_reader`` /
``config/lab_profiles/wqx.yaml``, which still carry their own DRAFT banner and
_TODO vocabularies. A produced package is NOT certified to pass the agency
validator; that is a Proposed owner-sign-off gate item (see ADR). ***

Design:
- WQX column names are anchored on the *verified* constants in ``wqx_reader``
  (2026-07-09 paper mapping) — never hand-authored from memory.
- Coordinates are not in canonical result records (they live on the wells
  feature class, LOCAL). So a monitoring-location metadata CSV is an explicit
  input contract for latitude/longitude/datum.
- Hard-required fields (identifiers, coordinates, a value+units for detections,
  a method) route failing rows to a rejections list with a reason; qualifier
  validation is opt-in via a configurable allowed set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from . import wqx_reader as _wr  # verified WQX column-name constants

# ---------------------------------------------------------------------------
# WQX target columns (anchored on wqx_reader's verified constants + wqx.yaml)
# ---------------------------------------------------------------------------

COL_MONLOC = "MonitoringLocationIdentifier"          # wqx.yaml: location_id
COL_ACTIVITY = "ActivityIdentifier"                  # wqx.yaml: sample_id
COL_ACTIVITY_DATE = "ActivityStartDate"              # wqx.yaml: event_date
COL_MEDIA = _wr._COL_MATRIX                           # "ActivityMediaName"
COL_CHARACTERISTIC = _wr._COL_ANALYTE                 # "CharacteristicName"
COL_RESULT = _wr._COL_RESULT                          # "ResultMeasureValue"
COL_RESULT_UNIT = _wr._COL_RESULT_UNIT               # "ResultMeasure/MeasureUnitCode"
COL_CONDITION = _wr._COL_CONDITION                    # "ResultDetectionConditionText"
COL_QUALIFIER = "MeasureQualifierCode"               # wqx.yaml: qualifier
COL_METHOD = "ResultAnalyticalMethod/MethodIdentifier"
COL_METHOD_NAME = "ResultAnalyticalMethod/MethodName"
COL_LIMIT_VALUE = _wr._COL_LIMIT_VALUE               # "DetectionQuantitationLimitMeasure/MeasureValue"
COL_LIMIT_UNIT = _wr._COL_LIMIT_UNIT                 # ".../MeasureUnitCode"
COL_LIMIT_TYPE = _wr._COL_LIMIT_TYPE                 # "DetectionQuantitationLimitTypeName"
COL_LAT = "LatitudeMeasure"
COL_LON = "LongitudeMeasure"
COL_DATUM = "HorizontalCoordinateReferenceSystemDatumName"

# Output column order (deterministic).
SUBMISSION_COLUMNS = [
    COL_MONLOC, COL_LAT, COL_LON, COL_DATUM,
    COL_ACTIVITY, COL_ACTIVITY_DATE, COL_MEDIA,
    COL_CHARACTERISTIC, COL_RESULT, COL_RESULT_UNIT, COL_CONDITION,
    COL_QUALIFIER, COL_METHOD, COL_METHOD_NAME,
    COL_LIMIT_VALUE, COL_LIMIT_UNIT, COL_LIMIT_TYPE,
]

# Reverse of the reader's matrix_map (canonical -> WQX media). Unmapped passes
# through unchanged (with a QA warning).
_MEDIA_OUT = {"GW": "Groundwater", "SOIL": "Soil", "SO": "Soil"}
_ND_CONDITION = "Not Detected"
_RL_TYPE = "Reporting Limit"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------------------
# Input contracts
# ---------------------------------------------------------------------------

@dataclass
class WqxSourceRow:
    """One canonical result to submit. Field names are canonical (== wqx.yaml
    ``columns`` keys); round-trips via records_csv."""
    site_id: str
    location_id: str
    event_date: str          # ISO YYYY-MM-DD
    matrix: str
    sample_id: str
    analyte: str
    result: Optional[float] = None
    units: str = ""
    qualifier: str = ""
    reporting_limit: Optional[float] = None
    method: str = ""
    method_name: str = ""
    is_nondetect: int = 0


@dataclass
class MonitoringLocation:
    """Coordinate metadata for a monitoring location (not in result records)."""
    location_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    horizontal_datum: str = ""


@dataclass
class WqxExportConfig:
    """Configurable validation policy."""
    # If non-empty, MeasureQualifierCode must be in this set or the row is
    # rejected. Empty (default) = permissive pass-through (qualifier validation
    # opt-in). Populate from a project WQX domain list.
    allowed_qualifiers: frozenset = frozenset()
    default_datum: str = "NAD83"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "WqxExportConfig":
        base = cls()
        if not data:
            return base
        if data.get("allowed_qualifiers"):
            base.allowed_qualifiers = frozenset(
                str(q).strip() for q in data["allowed_qualifiers"])
        if data.get("default_datum"):
            base.default_datum = str(data["default_datum"])
        return base


@dataclass
class WqxExportResult:
    submission: List[dict] = field(default_factory=list)   # valid WQX rows
    rejections: List[dict] = field(default_factory=list)   # {**source, reason}
    provenance: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mapping + validation
# ---------------------------------------------------------------------------

def _valid_coords(loc: Optional[MonitoringLocation]) -> Optional[str]:
    """Return a rejection reason if coordinates are missing/invalid, else None."""
    if loc is None:
        return "no monitoring-location metadata (coordinates) for location_id"
    if loc.latitude is None or loc.longitude is None:
        return "monitoring location missing latitude/longitude"
    if not (-90.0 <= loc.latitude <= 90.0):
        return f"latitude {loc.latitude} out of range [-90, 90]"
    if not (-180.0 <= loc.longitude <= 180.0):
        return f"longitude {loc.longitude} out of range [-180, 180]"
    return None


def _validate(row: WqxSourceRow, loc: Optional[MonitoringLocation],
              cfg: WqxExportConfig) -> Optional[str]:
    """Hard-required WQX validation. Returns a rejection reason or None."""
    if not (row.location_id or "").strip():
        return "missing MonitoringLocationIdentifier (location_id)"
    if not (row.sample_id or "").strip():
        return "missing ActivityIdentifier (sample_id)"
    if not _ISO_DATE.match((row.event_date or "").strip()):
        return f"invalid/missing ActivityStartDate: {row.event_date!r}"
    if not (row.analyte or "").strip():
        return "missing CharacteristicName (analyte)"
    if not (row.method or "").strip():
        return "missing ResultAnalyticalMethod/MethodIdentifier (method)"
    if not row.is_nondetect:
        if row.result is None:
            return "detection has no ResultMeasureValue"
        if not (row.units or "").strip():
            return "detection has no ResultMeasure/MeasureUnitCode (units)"
    coord_reason = _valid_coords(loc)
    if coord_reason:
        return coord_reason
    if cfg.allowed_qualifiers and (row.qualifier or "").strip():
        if row.qualifier.strip() not in cfg.allowed_qualifiers:
            return f"MeasureQualifierCode {row.qualifier!r} not in allowed set"
    return None


def _to_wqx(row: WqxSourceRow, loc: MonitoringLocation,
            cfg: WqxExportConfig, qa: QACollector) -> dict:
    media = _MEDIA_OUT.get((row.matrix or "").strip().upper())
    if media is None and (row.matrix or "").strip():
        media = row.matrix
        qa.add(SEV_WARNING, "wqx_out_unmapped_matrix",
               f"matrix {row.matrix!r} has no WQX media mapping; passed through",
               location_id=row.location_id)
    limit = row.reporting_limit
    return {
        COL_MONLOC: row.location_id,
        COL_LAT: loc.latitude,
        COL_LON: loc.longitude,
        COL_DATUM: loc.horizontal_datum or cfg.default_datum,
        COL_ACTIVITY: row.sample_id,
        COL_ACTIVITY_DATE: row.event_date,
        COL_MEDIA: media or "",
        COL_CHARACTERISTIC: row.analyte,
        COL_RESULT: "" if row.is_nondetect else row.result,
        COL_RESULT_UNIT: row.units,
        COL_CONDITION: _ND_CONDITION if row.is_nondetect else "",
        COL_QUALIFIER: row.qualifier,
        COL_METHOD: row.method,
        COL_METHOD_NAME: row.method_name,
        COL_LIMIT_VALUE: "" if limit is None else limit,
        COL_LIMIT_UNIT: row.units if limit is not None else "",
        COL_LIMIT_TYPE: _RL_TYPE if limit is not None else "",
    }


def map_to_wqx(
    rows: Sequence[WqxSourceRow],
    locations: Sequence[MonitoringLocation],
    cfg: Optional[WqxExportConfig] = None,
    qa: Optional[QACollector] = None,
) -> WqxExportResult:
    """Map canonical rows to WQX submission rows, splitting off rejects.

    Deterministic: submission rows sorted by (location, activity, characteristic).
    """
    if cfg is None:
        cfg = WqxExportConfig()
    if qa is None:
        qa = QACollector()
    loc_index: Dict[str, MonitoringLocation] = {
        (l.location_id or "").strip(): l for l in locations}

    result = WqxExportResult()
    for row in rows:
        loc = loc_index.get((row.location_id or "").strip())
        reason = _validate(row, loc, cfg)
        if reason:
            rej = {"location_id": row.location_id, "sample_id": row.sample_id,
                   "analyte": row.analyte, "reason": reason}
            result.rejections.append(rej)
            qa.add(SEV_WARNING, "wqx_out_rejected",
                   f"Rejected {row.sample_id}/{row.analyte}: {reason}",
                   location_id=row.location_id, sample_id=row.sample_id)
            continue
        result.submission.append(_to_wqx(row, loc, cfg, qa))

    result.submission.sort(
        key=lambda r: (r[COL_MONLOC], r[COL_ACTIVITY], r[COL_CHARACTERISTIC]))
    qa.add(SEV_INFO, "wqx_out_summary",
           f"WQX export: {len(result.submission)} submitted, "
           f"{len(result.rejections)} rejected of {len(rows)} row(s)")
    return result


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _demo() -> None:
    rows = [
        WqxSourceRow("S", "MW-1", "2026-01-15", "GW", "MW-1-A", "Benzene",
                     result=5.0, units="ug/L", method="8260", is_nondetect=0),
        WqxSourceRow("S", "MW-1", "2026-01-15", "GW", "MW-1-A", "Toluene",
                     result=None, units="ug/L", reporting_limit=1.0,
                     method="8260", is_nondetect=1),
        # rejects: no coords (MW-9), detection without units, missing method
        WqxSourceRow("S", "MW-9", "2026-01-15", "GW", "MW-9-A", "Lead",
                     result=2.0, units="ug/L", method="6020", is_nondetect=0),
        WqxSourceRow("S", "MW-1", "2026-01-15", "GW", "MW-1-B", "MTBE",
                     result=3.0, units="", method="8260", is_nondetect=0),
        WqxSourceRow("S", "MW-1", "2026-01-15", "GW", "MW-1-C", "Xylene",
                     result=3.0, units="ug/L", method="", is_nondetect=0),
    ]
    locs = [MonitoringLocation("MW-1", latitude=40.0, longitude=-105.0,
                               horizontal_datum="NAD83")]
    res = map_to_wqx(rows, locs)

    assert len(res.submission) == 2  # Benzene detect + Toluene ND
    assert len(res.rejections) == 3
    reasons = {r["analyte"]: r["reason"] for r in res.rejections}
    assert "coordinates" in reasons["Lead"]
    assert "units" in reasons["MTBE"]
    assert "method" in reasons["Xylene"]

    benz = next(r for r in res.submission if r[COL_CHARACTERISTIC] == "Benzene")
    assert benz[COL_MEDIA] == "Groundwater" and benz[COL_RESULT] == 5.0
    assert benz[COL_LAT] == 40.0 and benz[COL_DATUM] == "NAD83"
    tol = next(r for r in res.submission if r[COL_CHARACTERISTIC] == "Toluene")
    assert tol[COL_CONDITION] == _ND_CONDITION and tol[COL_RESULT] == ""
    assert tol[COL_LIMIT_VALUE] == 1.0 and tol[COL_LIMIT_TYPE] == _RL_TYPE

    # opt-in qualifier validation rejects unknown codes
    cfg = WqxExportConfig.from_dict({"allowed_qualifiers": ["U", "J"]})
    rows2 = [WqxSourceRow("S", "MW-1", "2026-01-15", "GW", "MW-1-A", "Benzene",
                          result=5.0, units="ug/L", qualifier="ZZ",
                          method="8260")]
    r2 = map_to_wqx(rows2, locs, cfg)
    assert len(r2.rejections) == 1 and "MeasureQualifierCode" in r2.rejections[0]["reason"]

    # deterministic order
    assert res.submission == sorted(
        res.submission,
        key=lambda r: (r[COL_MONLOC], r[COL_ACTIVITY], r[COL_CHARACTERISTIC]))
    print("wqx_outbound _demo OK")


if __name__ == "__main__":
    _demo()
