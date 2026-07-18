"""EQuIS v1 family EDD reader (Step 3 slice 1 of the ingestion program).

Joins the three-sheet EQuIS shape (sample + result/QC + batch) into flat row
dicts with synthesized ``__equis_*`` columns — transform logic here,
column->canonical mapping in the profile YAML (ADR-0080 pattern). Lab-QC rows
(LAB-source samples, surrogate rows) are tagged ``__equis_stream="qc"`` and
forked by run_edd_import into Env_QCResults.

Column constants target the EQuIS v1 dialect family (wmrd/epar4/nysdec) —
verified against the real B25030623 WMRD export 2026-07-10.

Spec: docs/superpowers/specs/2026-07-10-edd-step3-equis-wmrd-design.md.
arcpy-free; xlrd/openpyxl are lazy-imported in the sheet loaders only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_WARNING
from ..common.units import UnitError, convert

# EQuIS v1 family column names (TestResultQC_v1 / Sample_v1 / Batch_v1).
_COL_METHOD = "lab_anl_method_name"
_COL_FRACTION = "fraction"
_COL_COLUMN_NUM = "column_number"
_COL_TEST_TYPE = "test_type"
_COL_RESULT = "result_value"
_COL_RESULT_TYPE = "result_type_code"
_COL_DETECT_FLAG = "detect_flag"
_COL_REPORTABLE = "reportable_result"
_COL_DILUTION = "dilution_factor"
_COL_BASIS = "basis"
_COL_RESULT_UNIT = "result_unit"
_COL_LIMIT_UNIT = "detection_limit_unit"
_COL_MDL = "method_detection_limit"
_COL_RL = "reporting_detection_limit"
_COL_QL = "quantitation_limit"
_COL_QUAL_LAB = "lab_qualifiers"
_COL_QUAL_VAL = "validator_qualifiers"
_COL_QUAL_INT = "interpreted_qualifiers"
_COL_SAMPLE_TYPE = "sample_type_code"
_COL_SAMPLE_SOURCE = "sample_source"
_COL_BATCH_TYPE = "test_batch_type"
_COL_BATCH_ID = "test_batch_id"
_COL_ANALYSIS_DATE = "analysis_date"
_COL_ANALYSIS_TIME = "analysis_time"


def _get(row: dict, col: str) -> str:
    val = row.get(col)
    return "" if val is None else str(val).strip()


def _na(val: str) -> str:
    """WMRD uses literal 'NA' as its null in run discriminators."""
    return "" if val.upper() == "NA" else val


def _norm_header(text: str) -> str:
    """R2: casefold + strip ONE leading '#' (the template 'not uploaded'
    marker). No-op for the real WMRD export (lowercase, plain headers)."""
    text = text.strip()
    if text.startswith("#"):
        text = text[1:]
    return text.casefold()


def read_equis_xls(path: Path, profile,
                   qa: Optional[QACollector] = None) -> list[dict]:
    """Read an EQuIS EDD (.xls via xlrd, .xlsx via openpyxl — R1) and return
    transformed flat row dicts. The format id stays ``equis_xls``; the
    profile key, not the extension, selects this reader."""
    qa = qa if qa is not None else QACollector()
    path = Path(path)
    loader = (_load_xlsx_sheets if path.suffix.casefold() == ".xlsx"
              else _load_xls_sheets)
    sheets = loader(path, [profile.sample_sheet, profile.result_sheet,
                           profile.batch_sheet, profile.test_sheet])
    return transform_equis_sheets(sheets.get(profile.sample_sheet, []),
                                  sheets.get(profile.result_sheet, []),
                                  sheets.get(profile.batch_sheet, []),
                                  profile, qa,
                                  test_rows=sheets.get(profile.test_sheet, []))


def _load_xls_sheets(path: Path, names: list[str]) -> dict[str, list[dict]]:
    import xlrd  # required dep, lazy so nothing else pays the import
    wb = xlrd.open_workbook(str(path))
    out: dict[str, list[dict]] = {}
    for name in names:
        if not name:
            continue
        sheet = wb.sheet_by_name(name)
        if sheet.nrows == 0:
            out[name] = []
            continue
        headers = [_norm_header(_cell_text(c, wb.datemode))
                   for c in sheet.row(0)]
        rows = []
        for r in range(1, sheet.nrows):
            row = {h: _cell_text(c, wb.datemode)
                   for h, c in zip(headers, sheet.row(r)) if h}
            row["__sheet_row"] = r + 1   # 1-based, header = row 1
            rows.append(row)
        out[name] = rows
    return out


def _load_xlsx_sheets(path: Path, names: list[str]) -> dict[str, list[dict]]:
    import openpyxl  # required dep, lazy (R1)
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        out: dict[str, list[dict]] = {}
        for name in names:
            if not name:
                continue
            rows_iter = wb[name].iter_rows(values_only=True)
            first = next(rows_iter, None)
            if first is None:
                out[name] = []
                continue
            headers = [_norm_header(_xlsx_cell_text(v)) for v in first]
            rows = []
            for r, values in enumerate(rows_iter, start=2):
                row = {h: _xlsx_cell_text(v)
                       for h, v in zip(headers, values) if h}
                row["__sheet_row"] = r
                rows.append(row)
            out[name] = rows
        return out
    finally:
        wb.close()


def _xlsx_cell_text(value) -> str:
    """Normalize one openpyxl cell value to the same text contract as
    _cell_text: dates -> %m/%d/%Y [%H:%M], times -> %H:%M, int-valued floats
    without the .0 artifact, everything else stripped str."""
    import datetime
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return (value.strftime("%m/%d/%Y %H:%M")
                if (value.hour or value.minute)
                else value.strftime("%m/%d/%Y"))
    if isinstance(value, datetime.date):
        return value.strftime("%m/%d/%Y")
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _cell_text(cell, datemode: int) -> str:
    """Normalize one xlrd cell to text: BIFF dates -> ISO, int-valued floats
    without the .0 artifact, everything else stripped str."""
    import xlrd
    if cell.ctype == xlrd.XL_CELL_DATE:
        dt = xlrd.xldate_as_datetime(cell.value, datemode)
        return dt.strftime("%m/%d/%Y %H:%M") if (dt.hour or dt.minute) \
            else dt.strftime("%m/%d/%Y")
    if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
        return str(int(cell.value))
    if cell.ctype == xlrd.XL_CELL_EMPTY:
        return ""
    return str(cell.value).strip()


def _apply_source_aliases(rows: list[dict], aliases: dict[str, str]) -> None:
    """R3: bridge a dialect's renamed source columns onto the EQuIS names the
    ``_COL_*`` synthesis rules read. The source key is kept — profile
    ``columns:`` maps may still reference it. Applied after R2 (keys are
    already casefolded), before any synthesis."""
    for row in rows:
        for src, dst in aliases.items():
            if src in row and dst not in row:
                row[dst] = row[src]


def _test_key(row: dict, sample_id: str) -> tuple:
    """R4: 7-column composite key for test-sheet join: sample, method, date,
    time, fraction, column, test_type (casefolded)."""
    return (sample_id, _get(row, _COL_METHOD),
            _get(row, _COL_ANALYSIS_DATE), _get(row, _COL_ANALYSIS_TIME),
            _get(row, _COL_FRACTION), _get(row, _COL_COLUMN_NUM),
            _get(row, _COL_TEST_TYPE).casefold())


# Columns already pinned by _test_key — excluded from the payload compare so a
# benign test_type case variant ('initial' vs 'INITIAL', which _test_key
# casefolds together) is not misread as a conflicting duplicate (PR #253).
_TEST_KEY_COLS = frozenset({_COL_METHOD, _COL_ANALYSIS_DATE, _COL_ANALYSIS_TIME,
                            _COL_FRACTION, _COL_COLUMN_NUM, _COL_TEST_TYPE})


def _test_payload(row: dict) -> dict:
    """Fields of a test-sheet row NOT already fixed by ``_test_key`` — the
    content merged under each result row. Compared to tell a benign exact
    duplicate from a real conflict when two rows share the same key; key
    columns are excluded so their case/format has no vote (PR #253)."""
    return {k: v for k, v in row.items()
            if not k.startswith("__") and k not in _TEST_KEY_COLS}


def transform_equis_sheets(sample_rows: list[dict], result_rows: list[dict],
                           batch_rows: list[dict], profile,
                           qa: QACollector,
                           test_rows: Optional[list[dict]] = None) -> list[dict]:
    """Join + synthesize; returns flat rows, QC rows tagged __equis_stream."""
    test_rows = test_rows or []
    if profile.source_aliases:
        for rows in (sample_rows, result_rows, batch_rows, test_rows):
            _apply_source_aliases(rows, profile.source_aliases)
    sample_index = {}
    for s in sample_rows:
        key = profile.resolve_column(s, "sample_id")
        if key:
            sample_index[key] = s

    # (sample, method, fraction, column, test_type) -> {"prep": id, ...}
    # test_type is casefolded: the real WMRD export carries "initial" on
    # Batch_v1 vs "INITIAL" on TestResultQC_v1 (verified against the real
    # B25030623 export 2026-07-10) — case carries no meaning here, and a
    # case-sensitive join flooded every row with equis_missing_batch.
    # Batch type keys are also casefolded to handle NYSDEC's uppercase PREP/ANALYSIS
    # and Mining's enum records.
    # R6: NYSDEC's Batch_v5 adds analysis_date to the 5-column composite;
    # WMRD's 5-column join is byte-identical when the column is absent.
    join_date = bool(batch_rows and _COL_ANALYSIS_DATE in batch_rows[0]
                     and result_rows and _COL_ANALYSIS_DATE in result_rows[0])
    batch_index: dict[tuple, dict] = {}
    for b in batch_rows:
        key = (_get_sample_id(b, profile), _get(b, _COL_METHOD),
               _get(b, _COL_FRACTION), _get(b, _COL_COLUMN_NUM),
               _get(b, _COL_TEST_TYPE).casefold()) \
            + ((_get(b, _COL_ANALYSIS_DATE),) if join_date else ())
        batch_index.setdefault(key, {})[
            _get(b, _COL_BATCH_TYPE).casefold()] = _get(b, _COL_BATCH_ID)

    # R4 (ADR-0090): epar4 splits Test and Result into two sheets sharing a
    # 7-column composite; index the test sheet and merge under each result
    # row. fraction is the post-alias name (total_or_dissolved bridged by R3).
    # Two test rows sharing the composite but carrying conflicting content
    # (e.g. dilution 1 vs 5) would let file order pick which dilution/prep
    # metadata rides a frozen key — a blocking, batch-gated collision, not a
    # silent last-write-wins (PR #253; precedent ADR-0084 key-collision guard).
    test_index: dict[tuple, dict] = {}
    for t in test_rows:
        key = _test_key(t, _get_sample_id(t, profile))
        prior = test_index.get(key)
        if prior is None:
            test_index[key] = t
        elif _test_payload(prior) != _test_payload(t):
            qa.add(SEV_ERROR, "equis_test_key_collision",
                   f"Test sheet '{profile.test_sheet}' rows "
                   f"{prior.get('__sheet_row')} and {t.get('__sheet_row')} "
                   f"share test key {key} with conflicting content — import "
                   f"blocked (would attach order-dependent dilution/prep "
                   f"metadata to a frozen key)",
                   source_row=t.get("__sheet_row"))

    out = []
    for row_num, src in enumerate(result_rows, start=2):
        row_num = int(src.get("__sheet_row") or row_num)
        sample_id = _get_sample_id(src, profile)
        sample = sample_index.get(sample_id)
        if sample is None:
            qa.add(SEV_WARNING, "equis_missing_sample",
                   f"Row {row_num}: result sample '{sample_id}' not found in "
                   f"sheet '{profile.sample_sheet}' — row skipped",
                   source_row=row_num)
            continue

        row = dict(sample)
        if test_rows or profile.test_sheet:
            test = test_index.get(_test_key(src, sample_id))
            if test is None:
                qa.add(SEV_WARNING, "equis_missing_test",
                       f"Row {row_num}: no test-sheet entry for sample "
                       f"'{sample_id}' — test-side fields empty",
                       source_row=row_num)
            else:
                row.update(test)
        row.update(src)             # result columns win on collision
        row["__source_row"] = row_num
        _tag_stream(row, profile, qa, row_num)
        _synthesize_result(row, qa, row_num)
        _synthesize_qualifier(row)
        run_token = ""
        if profile.test_sheet:
            # Injective run identity: join date & time with '@' — absent from
            # normalized m/d/Y dates and H:M times, so distinct (date, time)
            # pairs never collide. Stripping the separators did: '1/23/2025'
            # + '4:56' and '12/3/2025' + '4:56' both became '1232025456' and
            # collapsed the frozen key (PR #253).
            date = _get(row, _COL_ANALYSIS_DATE)
            time = _get(row, _COL_ANALYSIS_TIME)
            run_token = f"{date}@{time}" if (date or time) else ""
        _compose_dilution_key(row, run_token)
        _route_limits(row, qa, row_num)
        _synthesize_reportable(row)
        _attach_batches(row, batch_index, batch_rows, sample_id, profile,
                        qa, row_num, join_date)
        out.append(row)
    return out


def _get_sample_id(row: dict, profile) -> str:
    return (profile.resolve_column(row, "sample_id") or "").strip()


def _tag_stream(row: dict, profile, qa: QACollector, row_num: int) -> None:
    is_lab = _get(row, _COL_SAMPLE_SOURCE).casefold() == "lab"
    is_sur = _get(row, _COL_RESULT_TYPE).upper() == "SUR"
    raw = _get(row, _COL_SAMPLE_TYPE)
    mapped = profile.value_maps.get("qc_sample_type", {}).get(raw)
    if is_sur:
        row["__equis_stream"] = "qc"
        row["__equis_qc_type"] = "SURROGATE"
        return
    if is_lab:
        row["__equis_stream"] = "qc"
        if mapped is None:
            qa.add(SEV_WARNING, "equis_unmapped_qc_type",
                   f"Row {row_num}: lab-QC sample type '{raw}' not in the "
                   f"profile qc_sample_type map — imported with the raw "
                   f"code; verify and extend the map",
                   source_row=row_num)
            mapped = raw
        row["__equis_qc_type"] = mapped
        return
    # Field stream: field-QC types (FIELD_DUP etc.) ride the analytical
    # table's QCType column via the same map; unmapped non-N types keep the
    # raw code truthy (fail-safe: canonical read hides them) + WARN.
    if raw and raw != "N" and mapped is None:
        qa.add(SEV_WARNING, "equis_unmapped_qc_type",
               f"Row {row_num}: field sample type '{raw}' not in the "
               f"profile qc_sample_type map — row imports QC-flagged "
               f"(hidden from canonical reads); verify the map",
               source_row=row_num)
        mapped = raw
    row["__equis_qc_type"] = mapped if mapped is not None else ""


def _synthesize_result(row: dict, qa: QACollector, row_num: int) -> None:
    value = _get(row, _COL_RESULT)
    if _get(row, _COL_DETECT_FLAG).casefold() == "n":
        if value:
            qa.add(SEV_WARNING, "equis_detect_flag_conflict",
                   f"Row {row_num}: detect_flag='N' with result value "
                   f"'{value}' — flag wins, row treated as non-detect",
                   source_row=row_num)
        row["__equis_result"] = "ND"
        return
    row["__equis_result"] = value


def _synthesize_qualifier(row: dict) -> None:
    # Q4 convention (paper mapping): final/interpreted qualifier wins.
    row["__equis_qualifier"] = (_get(row, _COL_QUAL_INT)
                                or _get(row, _COL_QUAL_VAL)
                                or _get(row, _COL_QUAL_LAB))


def _compose_dilution_key(row: dict, run_token: str = "") -> None:
    # Per-row fold (ADR-0080 determinism argument); WMRD's literal 'NA' nulls
    # normalized out so an undiluted INITIAL run keys compatibly with formats
    # that leave the columns blank.
    parts = [_na(_get(row, _COL_DILUTION)), _na(_get(row, _COL_TEST_TYPE)),
             _na(_get(row, _COL_COLUMN_NUM)), _na(_get(row, _COL_BASIS))]
    # ADR-0084 §1: EQuIS reports the same analyte under two methods on one
    # sample/date/fraction, and MethodID is not an Env_AnalyticalResults key
    # part — without the method run-token in the key the second method's row
    # silently loses to idempotent dedup. QC rows already carry MethodID as a
    # frozen Env_QCResults key part, so folding it there would only churn keys
    # on reimport; the method discriminator is analytical-only. Still per-row
    # deterministic — a given physical row always keys the same.
    if row.get("__equis_stream") != "qc":
        parts.append(_na(_get(row, _COL_METHOD)))
    # R9 (ADR-0090): epar4's TST composite treats analysis date/time as the
    # run identity, but neither survives into the frozen keys — the '@'-joined
    # date/time token makes reanalyses key distinctly on both tables. Bounded
    # (one date + one time, ~20 chars); the TEXT(64) overlength guard backs it.
    if run_token:
        parts.append(run_token)
    row["__equis_method_dilution_key"] = "|".join(p for p in parts if p)


def _route_limits(row: dict, qa: QACollector, row_num: int) -> None:
    result_unit = _get(row, _COL_RESULT_UNIT)
    limit_unit = _get(row, _COL_LIMIT_UNIT)
    row["__equis_units"] = result_unit or limit_unit
    for src_col, dest in ((_COL_RL, "__equis_reporting_limit"),
                          (_COL_MDL, "__equis_detection_limit"),
                          (_COL_QL, "__equis_quantitation_limit")):
        row[dest] = _convert_limit(_get(row, src_col), limit_unit,
                                   result_unit, qa, row_num)


def _convert_limit(raw: str, limit_unit: str, result_unit: str,
                   qa: QACollector, row_num: int) -> str:
    if not raw:
        return ""
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        qa.add(SEV_WARNING, "equis_bad_limit_value",
               f"Row {row_num}: cannot parse limit value '{raw}'; "
               f"limit dropped", source_row=row_num)
        return ""
    # Convert-at-load (ADR-0075 decision 5) with same-unit short-circuit;
    # empty limit unit = result units.
    converted = False
    if limit_unit and result_unit \
            and limit_unit.casefold() != result_unit.casefold():
        try:
            value = convert(value, limit_unit, result_unit)
            converted = True
        except UnitError as exc:
            qa.add(SEV_WARNING, "equis_limit_unit_mismatch",
                   f"Row {row_num}: {exc}; raw limit value kept",
                   source_row=row_num)
    return f"{value:g}" if converted else raw


def _synthesize_reportable(row: dict) -> None:
    raw = _get(row, _COL_REPORTABLE).casefold()
    row["__equis_is_reportable"] = ("1" if raw in ("yes", "y")
                                    else "0" if raw in ("no", "n") else "")


def _attach_batches(row: dict, batch_index: dict, batch_rows: list[dict],
                    sample_id: str, profile, qa: QACollector,
                    row_num: int, join_date: bool = False) -> None:
    if not batch_rows:
        _attach_inline_batch(row, qa, row_num)
        return
    key = (sample_id, _get(row, _COL_METHOD), _get(row, _COL_FRACTION),
           _get(row, _COL_COLUMN_NUM), _get(row, _COL_TEST_TYPE).casefold()) \
        + ((_get(row, _COL_ANALYSIS_DATE),) if join_date else ())
    hit = batch_index.get(key, {})
    row["__equis_prep_batch"] = hit.get("prep", "")
    row["__equis_analysis_batch"] = hit.get("analysis", "")
    if not hit:
        date_part = f", {key[5]}" if join_date else ""
        qa.add(SEV_WARNING, "equis_missing_batch",
               f"Row {row_num}: no batch-sheet entry for "
               f"({sample_id}, {key[1]}, {key[2]}, {key[3]}, {key[4]}"
               f"{date_part}) — batch ids empty", source_row=row_num)


def _attach_inline_batch(row: dict, qa: QACollector, row_num: int) -> None:
    """R5: no batch sheet — route the row's single inline
    test_batch_type/test_batch_id pair by type, case-insensitively (Mining's
    enum records uppercase PREP/ANALYSIS)."""
    row["__equis_prep_batch"] = ""
    row["__equis_analysis_batch"] = ""
    batch_id = _get(row, _COL_BATCH_ID)
    if not batch_id:
        return
    batch_type = _get(row, _COL_BATCH_TYPE).casefold()
    if batch_type == "prep":
        row["__equis_prep_batch"] = batch_id
        # The frozen Env_QCResults key carries AnalysisBatchID, not
        # PrepBatchID — without this fill, otherwise-identical QC rows from
        # two prep batches key identically and one silently loses to dedup.
        row["__equis_analysis_batch"] = batch_id
    elif batch_type == "analysis":
        row["__equis_analysis_batch"] = batch_id
    else:
        qa.add(SEV_WARNING, "equis_unknown_batch_type",
               f"Row {row_num}: inline batch type "
               f"'{_get(row, _COL_BATCH_TYPE)}' is not Prep/Analysis — "
               f"batch ids left empty", source_row=row_num)
