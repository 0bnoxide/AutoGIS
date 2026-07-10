"""EPA WQX / Water Quality Portal result-CSV reader (Step 2 of the ingestion program).

Loads a flat WQP physical/chemical result CSV and applies the WQX-specific
load-time transforms a flat column map cannot express, writing synthesized
``__wqx_*`` columns onto each row dict. The output honors the reader-seam
contract — a flat list of row dicts — consumed by ``normalize_edd_rows``
through the ``wqx`` profile, which maps canonical fields to real WQX columns
or to the synthesized ones. Transform logic lives here; column->canonical
mapping stays in YAML (ADR-0075 frozen seam).

Spec: docs/superpowers/specs/2026-07-10-wqx-step2-import-design.md.
arcpy-free; stdlib + core.common only.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_WARNING
from ..common.units import UnitError, convert

# Source column names, verified against real exports in the 2026-07-09
# paper mapping (docs/superpowers/specs/2026-07-09-edd-paper-mapping-outcome.md).
_COL_RESULT = "ResultMeasureValue"
_COL_RESULT_UNIT = "ResultMeasure/MeasureUnitCode"
_COL_CONDITION = "ResultDetectionConditionText"
_COL_LIMIT_VALUE = "DetectionQuantitationLimitMeasure/MeasureValue"
_COL_LIMIT_UNIT = "DetectionQuantitationLimitMeasure/MeasureUnitCode"
_COL_LIMIT_TYPE = "DetectionQuantitationLimitTypeName"
_COL_ANALYTE = "CharacteristicName"
_COL_SPECIATION = "MethodSpeciationName"
_COL_DILUTION = "SubstanceDilutionFactor"
_COL_STAT_BASE = "StatisticalBaseCode"
_COL_BASIS = "ResultWeightBasisText"
_COL_MATRIX_SUB = "ActivityMediaSubdivisionName"
_COL_MATRIX = "ActivityMediaName"
_COL_STATUS = "ResultStatusIdentifier"
_COL_ACTIVITY_TYPE = "ActivityTypeCode"


def _get(row: dict, col: str) -> str:
    val = row.get(col)
    return "" if val is None else str(val).strip()


def read_wqx_csv(path: Path, profile, qa: Optional[QACollector] = None) -> list[dict]:
    """Read a WQP result CSV and return transformed flat row dicts."""
    qa = qa if qa is not None else QACollector()
    with Path(path).open(newline="", encoding=profile.encoding) as fh:
        rows = list(csv.DictReader(fh))
    return transform_wqx_rows(rows, profile, qa)


def transform_wqx_rows(rows: list[dict], profile, qa: QACollector) -> list[dict]:
    """Apply the WQX load-time transforms; returns new row dicts.

    Row numbering matches normalize_edd_rows' convention (data starts at 2).
    """
    out = []
    for row_num, src in enumerate(rows, start=2):
        if _get(src, _COL_STATUS).casefold() == "rejected":
            qa.add(SEV_WARNING, "wqx_rejected_row_skipped",
                   f"Row {row_num}: ResultStatusIdentifier='Rejected' — "
                   f"row skipped (rejected results must not reach screening)",
                   source_row=row_num)
            continue
        row = dict(src)
        _fold_analyte(row)
        _coalesce_matrix(row)
        _synthesize_result(row, profile, qa, row_num)
        _route_limit(row, profile, qa, row_num)
        _compose_dilution_key(row)
        _warn_unmapped_activity_type(row, profile, qa, row_num)
        out.append(row)
    return out


def _fold_analyte(row: dict) -> None:
    # Key-safety convention (ADR-0075): where speciation is populated,
    # AnalyteCanonicalName must incorporate it, so as-N vs as-NO3 rows of the
    # same characteristic never collide in the frozen key.
    name = _get(row, _COL_ANALYTE)
    speciation = _get(row, _COL_SPECIATION)
    row["__wqx_analyte"] = f"{name} {speciation}" if name and speciation else name


def _coalesce_matrix(row: dict) -> None:
    # resolve_column does not fall through on empty cells (CSV always supplies
    # ""), so the subdivision-else-media coalesce must happen here.
    row["__wqx_matrix"] = _get(row, _COL_MATRIX_SUB) or _get(row, _COL_MATRIX)


def _synthesize_result(row: dict, profile, qa: QACollector, row_num: int) -> None:
    condition = _get(row, _COL_CONDITION)
    value = _get(row, _COL_RESULT)
    mapped = profile.value_maps.get("detection_condition", {}).get(condition)

    if condition and mapped == "ND":
        if value:
            qa.add(SEV_WARNING, "wqx_result_condition_conflict",
                   f"Row {row_num}: detection condition '{condition}' with a "
                   f"result value '{value}' — condition wins, row treated as "
                   f"non-detect",
                   source_row=row_num)
        row["__wqx_result"] = "ND"
        return
    if condition and mapped is None and not value:
        # Unmapped condition + empty value would parse BLANK -> IsNotAnalyzed=1
        # with zero trace; the normalizer never surfaces parse warnings.
        qa.add(SEV_WARNING, "wqx_unmapped_detection_condition",
               f"Row {row_num}: ResultDetectionConditionText '{condition}' not "
               f"in the profile detection_condition map and no result value — "
               f"row will import as not-analyzed; verify and extend the map",
               source_row=row_num)
    # mapped == "" (explicit not-an-ND) or no condition: the value stands.
    row["__wqx_result"] = value


def _route_limit(row: dict, profile, qa: QACollector, row_num: int) -> None:
    row["__wqx_reporting_limit"] = ""
    row["__wqx_detection_limit"] = ""
    raw = _get(row, _COL_LIMIT_VALUE)
    if not raw:
        return
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        qa.add(SEV_WARNING, "wqx_bad_limit_value",
               f"Row {row_num}: cannot parse limit value '{raw}'; limit dropped",
               source_row=row_num)
        return

    # Convert-at-load policy (ADR-0075 decision 5): limit in result units.
    limit_unit = _get(row, _COL_LIMIT_UNIT)
    result_unit = _get(row, _COL_RESULT_UNIT)
    # Same-unit short-circuit — unregistered-but-equal units (pH, deg C, NTU)
    # need no conversion and must not warn. Empty limit unit = result units.
    if limit_unit and result_unit and limit_unit.casefold() != result_unit.casefold():
        try:
            value = convert(value, limit_unit, result_unit)
        except UnitError as exc:
            qa.add(SEV_WARNING, "wqx_limit_unit_mismatch",
                   f"Row {row_num}: {exc}; raw limit value kept",
                   source_row=row_num)

    limit_type = _get(row, _COL_LIMIT_TYPE)
    route = profile.value_maps.get("limit_type_route", {}).get(limit_type)
    if route not in ("RL", "DL"):
        qa.add(SEV_WARNING, "wqx_unmapped_limit_type",
               f"Row {row_num}: limit type '{limit_type}' not in the profile "
               f"limit_type_route map; defaulting to ReportingLimit "
               f"(LimitType column keeps the raw name)",
               source_row=row_num)
        route = "RL"
    if route == "DL":
        row["__wqx_detection_limit"] = str(value)
    else:
        row["__wqx_reporting_limit"] = str(value)


def _compose_dilution_key(row: dict) -> None:
    # WQX MethodDilutionKey recipe (ADR-0080): unconditional |-join of the
    # non-empty run discriminators. Per-row deterministic and cross-file
    # stable — a conditional dual-reported fold would give the same physical
    # row different keys across import batches and break idempotent dedup.
    parts = (_get(row, _COL_DILUTION), _get(row, _COL_STAT_BASE),
             _get(row, _COL_BASIS))
    row["__wqx_method_dilution_key"] = "|".join(p for p in parts if p)


def _warn_unmapped_activity_type(row: dict, profile, qa: QACollector,
                                 row_num: int) -> None:
    # ActivityTypeCode is WQX's ONLY QC discriminator; an unmapped code passes
    # through truthy (fail-safe: canonical read drops the row) but must not do
    # so silently.
    code = _get(row, _COL_ACTIVITY_TYPE)
    if code and code not in profile.value_maps.get("qc_type", {}):
        qa.add(SEV_WARNING, "wqx_unmapped_activity_type",
               f"Row {row_num}: ActivityTypeCode '{code}' not in the profile "
               f"qc_type map — row imports QC-flagged (hidden from canonical "
               f"reads); verify and extend the map",
               source_row=row_num)
