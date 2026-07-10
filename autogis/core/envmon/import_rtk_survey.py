"""import_rtk_survey.py — parse RTK survey CSV → SurveyPoints_Raw/QA GDB tables."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_WARNING


@dataclass
class RTKColumnMap:
    point_id: str = "PointID"
    northing: str = "Northing"
    easting: str = "Easting"
    elevation_ft: str = "Elevation_ft"
    feature_code: str = "FeatureCode"
    description: str = "Description"
    hrms_ft: str = "HRMS_ft"
    vrms_ft: str = "VRMS_ft"
    fix_type: str = "FixType"
    collected_at: str = "CollectedAt"
    operator: str = "Operator"

    RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


@dataclass
class RTKPoint:
    point_id: str
    northing: float
    easting: float
    elevation_ft: float
    feature_code: str = ""
    description: str = ""
    hrms_ft: Optional[float] = None
    vrms_ft: Optional[float] = None
    pdop: Optional[float] = None
    satellites: Optional[int] = None
    fix_type: str = ""
    collected_at: str = ""
    operator: str = ""


def _f(row, key, default=None):
    v = row.get(key, "").strip()
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


# --------------------------------------------------------------------------
# Headerless PNEZD/PENZD detection (2026-07-03 design)
# --------------------------------------------------------------------------

# Columns 6+ vocabulary for the headerless extended layout / --extra-columns.
_EXTRA_COLUMN_VOCAB = (
    "hrms_ft", "vrms_ft", "pdop", "satellites", "fix_type", "collected_at",
    "operator", "feature_code",
)
# Built-in 11-column layout (columns 6-11), used when --extra-columns is absent.
_DEFAULT_11COL_EXTRA = ("hrms_ft", "vrms_ft", "pdop", "satellites", "fix_type", "collected_at")

_FIX_TYPE_SYNONYMS = {
    "FIXED": "RTK_FIXED",
    "FLOAT": "RTK_FLOAT",
    "NETWORK RTK": "NETWORK_RTK",
    "NRTK": "NETWORK_RTK",
}


def _normalize_fix_type(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return raw
    return _FIX_TYPE_SYNONYMS.get(raw.upper(), raw)


def _to_float(v: str) -> Optional[float]:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _to_int(v: str) -> Optional[int]:
    f = _to_float(v)
    return None if f is None else int(f)


def _parse_required_float(raw: str, row_num: int, label: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"row {row_num}: {label} value {raw!r} is not a valid number."
        )


def _is_headerless(first_row: list[str]) -> bool:
    """Columns 2-4 (idx 1-3) hold Coord1/Coord2/Elevation in every recognized
    headerless layout; if all three parse as floats, row 1 is data, not a header."""
    if len(first_row) < 4:
        return False
    return all(_to_float(v) is not None for v in first_row[1:4])


def _digit_count(avg_magnitude: float) -> int:
    return len(str(int(abs(avg_magnitude))))


def _resolve_coord_order(coord1_vals: list[float], coord2_vals: list[float], fmt: str):
    """Returns (northing_vals, easting_vals, warning_message_or_None)."""
    if fmt == "pnezd":
        return coord1_vals, coord2_vals, None
    if fmt == "penzd":
        return coord2_vals, coord1_vals, None

    avg1 = sum(coord1_vals) / len(coord1_vals)
    avg2 = sum(coord2_vals) / len(coord2_vals)
    d1, d2 = _digit_count(avg1), _digit_count(avg2)
    if d1 == d2:
        raise ValueError(
            "cannot auto-detect Northing/Easting column order: both columns "
            f"have the same magnitude (~{d1} digits average) — pass "
            "--format pnezd or --format penzd explicitly."
        )
    if d2 > d1:
        msg = (f"guessed_coord_order: column 2 = Easting (avg magnitude "
               f"~{avg1:,.0f}, {d1} digits), column 3 = Northing (avg "
               f"magnitude ~{avg2:,.0f}, {d2} digits) — pass --format "
               "pnezd|penzd to override if wrong.")
        return coord2_vals, coord1_vals, msg
    msg = (f"guessed_coord_order: column 2 = Northing (avg magnitude "
           f"~{avg1:,.0f}, {d1} digits), column 3 = Easting (avg "
           f"magnitude ~{avg2:,.0f}, {d2} digits) — pass --format "
           "pnezd|penzd to override if wrong.")
    return coord1_vals, coord2_vals, msg


def _parse_headered_csv(path: Path, cm: RTKColumnMap) -> list[RTKPoint]:
    out: list[RTKPoint] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            n = _f(row, cm.northing)
            e = _f(row, cm.easting)
            z = _f(row, cm.elevation_ft)
            if n is None or e is None or z is None:
                continue
            out.append(RTKPoint(
                point_id=row.get(cm.point_id, "").strip(),
                northing=n, easting=e, elevation_ft=z,
                feature_code=row.get(cm.feature_code, "").strip(),
                description=row.get(cm.description, "").strip(),
                hrms_ft=_f(row, cm.hrms_ft),
                vrms_ft=_f(row, cm.vrms_ft),
                fix_type=row.get(cm.fix_type, "").strip(),
                collected_at=row.get(cm.collected_at, "").strip(),
                operator=row.get(cm.operator, "").strip(),
            ))
    return out


def _parse_headerless_csv(
    path: Path,
    fmt: str,
    extra_columns: Optional[list[str]],
    qa: Optional[QACollector],
) -> list[RTKPoint]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if any(c.strip() for c in r)]
    if not rows:
        return []
    width = len(rows[0])

    ragged = [(i, len(r)) for i, r in enumerate(rows, start=1) if len(r) != width]
    if ragged:
        i, n = ragged[0]
        raise ValueError(
            f"ragged headerless CSV: row {i} has {n} column(s), expected "
            f"{width} (based on row 1) — {len(ragged)} row(s) disagree on "
            f"column count. Fix the file; headerless parsing assumes a "
            f"uniform column count for every row."
        )

    if extra_columns is not None:
        unknown = [c for c in extra_columns if c not in _EXTRA_COLUMN_VOCAB]
        if unknown:
            raise ValueError(
                f"unrecognized --extra-columns field(s): {', '.join(unknown)}. "
                f"Valid vocabulary: {', '.join(_EXTRA_COLUMN_VOCAB)}."
            )
        if width == 5:
            if qa is not None:
                qa.add(SEV_WARNING, "extra_columns_noop",
                       "--extra-columns given on a 5-column file; there were "
                       "no extra columns to map.")
            extra_fields: list[str] = []
        elif len(extra_columns) != width - 5:
            raise ValueError(
                f"--extra-columns names {len(extra_columns)} field(s) but "
                f"the file has {width - 5} column(s) beyond the base 5 "
                f"(columns 6-{width}) — count must match exactly, or data "
                f"would be silently dropped or misaligned."
            )
        else:
            extra_fields = list(extra_columns)
    elif width == 11:
        extra_fields = list(_DEFAULT_11COL_EXTRA)
    elif width == 5:
        extra_fields = []
    else:
        raise ValueError(
            f"headerless parsing only supports 5-column PNEZD/PENZD or "
            f"11-column extended layouts; got {width} columns. Use "
            f"--extra-columns to declare a custom layout."
        )

    coord1_vals = [_parse_required_float(r[1], i, "Coord1") for i, r in enumerate(rows, start=1)]
    coord2_vals = [_parse_required_float(r[2], i, "Coord2") for i, r in enumerate(rows, start=1)]
    northing_vals, easting_vals, warning = _resolve_coord_order(coord1_vals, coord2_vals, fmt)
    if warning and qa is not None:
        qa.add(SEV_WARNING, "guessed_coord_order", warning)

    out: list[RTKPoint] = []
    for idx, r in enumerate(rows):
        kwargs = {}
        for field_idx, field_name in enumerate(extra_fields):
            col_idx = 5 + field_idx
            raw_val = r[col_idx] if col_idx < len(r) else ""
            if field_name in ("hrms_ft", "vrms_ft", "pdop"):
                kwargs[field_name] = _to_float(raw_val)
            elif field_name == "satellites":
                kwargs[field_name] = _to_int(raw_val)
            elif field_name == "fix_type":
                kwargs[field_name] = _normalize_fix_type(raw_val)
            else:
                kwargs[field_name] = raw_val.strip()
        out.append(RTKPoint(
            point_id=r[0].strip(),
            northing=northing_vals[idx],
            easting=easting_vals[idx],
            elevation_ft=_parse_required_float(r[3], idx + 1, "Elevation"),
            description=r[4].strip() if len(r) > 4 else "",
            **kwargs,
        ))
    return out


def parse_rtk_csv(
    path: Path,
    column_map: Optional[RTKColumnMap] = None,
    coord_format: str = "auto",
    extra_columns: Optional[list[str]] = None,
    qa: Optional[QACollector] = None,
) -> list[RTKPoint]:
    cm = column_map or RTKColumnMap()
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        first_row = next(csv.reader(fh), None)
    if first_row is None:
        return []

    if not _is_headerless(first_row):
        if (coord_format != "auto" or extra_columns) and qa is not None:
            qa.add(SEV_WARNING, "format_options_ignored",
                   "--format/--extra-columns are no-ops on headered CSV input.")
        return _parse_headered_csv(path, cm)

    return _parse_headerless_csv(path, coord_format, extra_columns, qa)


_RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


def assign_qa_flags(
    point: RTKPoint,
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> list[str]:
    flags: list[str] = []
    if point.hrms_ft is not None and point.hrms_ft > hrms_threshold_ft:
        flags.append("hrms_exceeds_threshold")
    if point.vrms_ft is not None and point.vrms_ft > vrms_threshold_ft:
        flags.append("vrms_exceeds_threshold")
    if point.fix_type and point.fix_type.upper() not in _RTK_FIX_TYPES:
        flags.append("fix_type_not_rtk")
    return flags


def import_rtk_survey(
    gdb_path: str,
    site_id: str,
    batch_id: str,
    points: list[RTKPoint],
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> None:
    """Write RTKPoint list to SurveyPoints_Raw and SurveyPoints_QA (ArcGIS Pro).

    Raises RuntimeError when either target table is missing: silently skipping
    the write while the CLI still printed "Imported N points" turned a wrong
    --gdb into false success (2026-07-10 QA session).
    """
    import json
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    raw_table = str(_P(gdb) / "SurveyPoints_Raw")
    qa_table = str(_P(gdb) / "SurveyPoints_QA")

    missing = [name for name, table in (("SurveyPoints_Raw", raw_table),
                                        ("SurveyPoints_QA", qa_table))
               if not _ax.Exists(table)]
    if missing:
        # ASCII only: this message crosses a cp1252 subprocess boundary.
        raise RuntimeError(
            f"{' and '.join(missing)} not found in {gdb} -- run "
            f"`autogis envmon upgrade-schema --gdb {gdb}` first, then re-import."
        )

    with _ax.da.InsertCursor(raw_table,
                             ["PointID", "Northing", "Easting", "Elevation_ft",
                              "FeatureCode", "Description", "HRMS_ft", "VRMS_ft",
                              "PDOP", "Satellites",
                              "FixType", "CollectedAt", "Operator"]) as cur:
        for pt in points:
            cur.insertRow([pt.point_id, pt.northing, pt.easting, pt.elevation_ft,
                           pt.feature_code, pt.description, pt.hrms_ft, pt.vrms_ft,
                           pt.pdop, pt.satellites,
                           pt.fix_type, pt.collected_at, pt.operator])

    with _ax.da.InsertCursor(qa_table,
                             ["PointID", "QAStatus", "QAFlags", "Approved"]) as cur:
        for pt in points:
            flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
            status = "FAIL" if flags else "PASS"
            cur.insertRow([pt.point_id, status, json.dumps(flags), 0])
