"""Migrate wide-format legacy CSV/XLSX to normalised long-format schema (Tool 2.4).

Headless, arcpy-free. Accepts a wide-format environmental table where rows are
sampling events and analyte result columns span the header. A mapping config
(YAML) names the metadata columns; remaining columns are treated as analytes.

Output: two CSVs — sample_records and analytical_result_records — ready for
validate-db / apply-screening / reconcile-locations.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING


@dataclass
class MigrationConfig:
    """Mapping of wide-format metadata column names."""
    location_col: str = "LocationID"
    date_col: str = "SampleDate"
    matrix_col: Optional[str] = "Matrix"
    sample_id_col: Optional[str] = None    # auto-generated if None
    site_id: str = ""
    batch_id: str = ""
    default_matrix: str = "GW"
    default_units: str = "ug/L"
    nondetect_prefix: str = "<"            # most common: "<5.0" → nondetect

    @classmethod
    def from_dict(cls, d: dict) -> "MigrationConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LegacyResultRow:
    SiteID: str
    BatchID: str
    SampleID: str
    LocationID: str
    SampleDate: str
    Matrix: str
    AnalyteCanonicalName: str
    ResultValue: Optional[float]
    ResultUnits: str
    IsNondetect: bool
    OriginalValue: str
    SourceRow: int


def _parse_date(raw: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(raw.strip(), fmt).date()
        except ValueError:
            pass
    return None


_BLANK_VALUES = frozenset(("-", "N/A", "NA", "n/a", "n/A", "N/a"))


def _parse_result(raw: str, nd_prefix: str) -> tuple[Optional[float], bool, str]:
    """Return (value_or_None, is_nondetect, original)."""
    raw = raw.strip()
    if not raw or raw in _BLANK_VALUES:
        return None, False, raw
    is_nd = raw.upper().startswith(nd_prefix.upper()) or raw.startswith("<")
    # Strip the ND prefix exactly, then common qualifier chars.
    numeric_str = raw
    if is_nd and nd_prefix and raw.upper().startswith(nd_prefix.upper()):
        numeric_str = raw[len(nd_prefix):]
    numeric_str = numeric_str.lstrip("<>UuJj ").strip()
    try:
        return float(numeric_str), is_nd, raw
    except ValueError:
        return None, is_nd, raw


def migrate_wide_csv(
    source_path: Path,
    config: MigrationConfig,
    *,
    units_map: Optional[Dict[str, str]] = None,
    qa: Optional[QACollector] = None,
) -> List[LegacyResultRow]:
    """Read wide-format CSV and return long-format LegacyResultRow list.

    Args:
        source_path: Path to wide-format CSV.
        config: Column mapping configuration.
        units_map: Optional dict of analyte_name -> units override.
        qa: QA collector (created if not supplied).

    Returns:
        List of LegacyResultRow, one per non-blank analyte value.
    """
    if qa is None:
        qa = QACollector()
    units_map = units_map or {}
    batch_id = config.batch_id or str(uuid.uuid4())[:8].upper()

    with Path(source_path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        headers = reader.fieldnames or []

    meta_cols = {config.location_col, config.date_col}
    if config.matrix_col:
        meta_cols.add(config.matrix_col)
    if config.sample_id_col:
        meta_cols.add(config.sample_id_col)

    # Remaining headers are analyte columns.
    analyte_cols = [h for h in headers if h not in meta_cols]
    if not analyte_cols:
        raise ValueError("No analyte columns found after excluding metadata columns.")

    results: List[LegacyResultRow] = []

    for row_idx, row in enumerate(rows, start=2):
        loc = row.get(config.location_col, "").strip()
        date_raw = row.get(config.date_col, "").strip()
        matrix = row.get(config.matrix_col or "", config.default_matrix).strip() or config.default_matrix
        sample_id = row.get(config.sample_id_col or "", "").strip()

        if not loc:
            qa.add(SEV_WARNING, "missing_location",
                   f"Row {row_idx}: empty LocationID — row skipped",
                   site_id=config.site_id)
            continue

        parsed_date = _parse_date(date_raw)
        if not parsed_date and date_raw:
            qa.add(SEV_WARNING, "bad_date",
                   f"Row {row_idx}: cannot parse date '{date_raw}'",
                   site_id=config.site_id, location_id=loc)

        if not sample_id:
            # Non-lifecycle identity, only invented when the historical
            # source has none — deliberately NOT the lifecycle format;
            # sample_id.parse_sample_id returns None for it.
            sample_id = f"{loc}_{date_raw}_{row_idx}"

        for analyte in analyte_cols:
            raw_val = row.get(analyte, "").strip()
            if not raw_val or raw_val in _BLANK_VALUES:
                continue
            val, is_nd, orig = _parse_result(raw_val, config.nondetect_prefix)
            if val is None and not is_nd:
                qa.add(SEV_WARNING, "unparseable_result",
                       f"Row {row_idx} analyte '{analyte}': "
                       f"cannot parse '{raw_val}'",
                       site_id=config.site_id, location_id=loc)
            units = units_map.get(analyte, config.default_units)
            results.append(LegacyResultRow(
                SiteID=config.site_id,
                BatchID=batch_id,
                SampleID=sample_id,
                LocationID=loc,
                SampleDate=parsed_date.isoformat() if parsed_date else date_raw,
                Matrix=matrix,
                AnalyteCanonicalName=analyte,
                ResultValue=val,
                ResultUnits=units,
                IsNondetect=is_nd,
                OriginalValue=orig,
                SourceRow=row_idx,
            ))

    qa.add(SEV_INFO, "migration_complete",
           f"migrate_wide_csv: {len(rows)} source rows → {len(results)} result rows",
           site_id=config.site_id)
    return results
