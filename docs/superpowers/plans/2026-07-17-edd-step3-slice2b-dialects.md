# EDD Step-3 Slice 2b — mining/epar4/NYSDEC dialects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the EQuIS reader (`equis_reader.py`) with the R1–R9 structural
extensions from the merged spec
`docs/superpowers/specs/2026-07-12-edd-step3-slice2-design.md` and ship three
DRAFT dialect profiles (`mining.yaml`, `epar4.yaml`, `nysdec.yaml`) with
synthetic `.xlsx` fixtures and e2e tests.

**Architecture:** All transform logic stays in `equis_reader.py` (synthesized
`__equis_*` columns); all column→canonical mapping stays in profile YAML
(ADR-0080 pattern). The reader gains: an openpyxl `.xlsx` engine branch (R1),
load-time header normalization (R2), a `source_aliases:` bridge (R3), an
optional `test_sheet:` join (R4 — gated on the ADR in Task 5), inline-batch
fallback with case-insensitive type matching (R5), an `analysis_date`-extended
batch join (R6), and an epar4 run-identity token folded into the
`MethodDilutionKey` value recipe (R9). Zero CLI change (R8).

**Tech Stack:** Python stdlib + xlrd (existing, `.xls`) + openpyxl (existing
required dep, `.xlsx`). No new dependencies. arcpy-free throughout.

## Global Constraints

- **Branch:** all work on `feat/edd-step3-slice2b-dialects` in the worktree
  `.claude/worktrees/feat+edd-step3-slice2b-dialects` — `main` is READ-ONLY.
- **ponytail (full) applies:** laziest correct diff, reuse before writing,
  no unrequested abstractions. State this in every subagent prompt.
- **arcpy-free invariant:** `core/` and `adapters/` must import with neither
  `arcpy` nor `arcgis` present. Nothing in this plan touches arcpy.
- **Frozen keys are untouchable (ADR-0084):** never widen
  `UNIQUE_KEYS["Env_AnalyticalResults"]` (11 parts) or
  `UNIQUE_KEYS["Env_QCResults"]` (9 parts); never add run-instance ordinals.
  R9 folds into the `MethodDilutionKey` *value recipe* only (ADR-0075 §3).
- **R4 is gated:** the Task-5 ADR explicitly accepting the ADR-0075
  `LabEDDProfile` shape amendment MUST be committed before any Task-6 code.
- **DRAFT banners** on all three profiles (wqx.yaml precedent) — no real
  filled EDD exists; do not claim verification.
- **No client data in the repo:** committed fixtures are synthetic
  openpyxl-generated `.xlsx` only (template headers + invented rows).
- **Dialect QC collisions ERROR-block by design (#244):** e2e fixtures must
  avoid QC rerun collisions or assert the blocking `edd_key_collision` guard.
- **Tests:** run with `python -m pytest -q` from the worktree root; run the
  targeted file first, the full suite in the final task. Suite baseline at
  branch time: 2188 passed / 3 skipped.
- **CLI surface (R8):** `autogis envmon import-edd --edd <f.xlsx>
  --profile-path <yaml> --site <S> --gdb <g>` — zero CLI change expected;
  dispatch is entirely via `format: equis_xls`.

## File Structure

| File | Change | Task |
|---|---|---|
| `autogis/core/envmon/equis_reader.py` | R1/R2 loaders, R3 aliases, R5 inline batch, R6 join, R4 test join, R9 token | 1,2,3,4,6,7 |
| `autogis/core/envmon/edd_profile.py` | `source_aliases` + `test_sheet` fields | 2,6 |
| `docs/adr/XXXX-edd-step3-slice2b-dialects.md` | new ADR (gates R4) | 5 |
| `autogis/config/lab_profiles/mining.yaml` | new DRAFT profile | 8 |
| `autogis/config/lab_profiles/epar4.yaml` | new DRAFT profile | 9 |
| `autogis/config/lab_profiles/nysdec.yaml` | new DRAFT profile | 10 |
| `tests/envmon/test_equis_xlsx_engine.py` | R1/R2 unit tests | 1 |
| `tests/envmon/test_equis_dialect_transforms.py` | R3/R5/R6/R4/R9 unit tests | 2,3,4,6,7 |
| `tests/fixtures/make_mining_fixture.py` + `mining_edd_fixture.xlsx` | generator + fixture | 8 |
| `tests/fixtures/make_epar4_fixture.py` + `epar4_edd_fixture.xlsx` | generator + fixture | 9 |
| `tests/fixtures/make_nysdec_fixture.py` + `nysdec_edd_fixture.xlsx` | generator + fixture | 10 |
| `tests/envmon/test_mining_e2e.py` / `test_epar4_e2e.py` / `test_nysdec_e2e.py` | per-dialect e2e | 8,9,10 |

Existing pinned behavior that must NOT change: `tests/envmon/test_equis_reader.py`,
`test_equis_e2e.py`, `test_wmrd_profile.py`, `test_qc_normalizer.py`,
`test_key_collision_guard.py` all keep passing untouched (WMRD no-op pinning
for R2/R5/R6; `test_rerun_flags_and_dilution_keys` pins the exact WMRD
`MethodDilutionKey` string, proving R9 is epar4-only).

## Template facts (verified against the cleared examples folder, 2026-07-17)

Recorded here so no task re-opens the templates. Headers listed post-R2
(casefolded, `#` stripped).

- **Mining** (`Mining EDD Blank Template.xlsx`): `LabCollection` sample sheet
  (`sample_id, sample_type, medium, matrix, sample_source, parent_sample_id,
  sample_date, station_id, sample_start_depth, sample_end_depth,
  sample_depth_units, sampler, ...`); `LabResult` result sheet (`sample_id,
  analytical_method_id, analysis_date, sample_fraction, test_type,
  lab_matrix, basis, dilution_factor, prep_method, prep_date, leachate_method,
  leachate_date, lab_name, lab_sample_id, percent_moisture, result_comment,
  preservative, preservative_date, characteristic_id, characteristic_name,
  method_speciation, result_value, result_value_unit, detect_flag,
  reportable_result, lab_qualifiers, interpreted_qualifiers,
  method_detection_limit, lower_reporting_limit, quantitation_limit,
  detection_limit_unit, lab_batch_id, batch_type, result_type_code, qc_*`).
  No `column_number`, no `validator_qualifiers`, no batch sheet.
  Sample types (`activity_type_code` in `MTDEQ_Mining-enum.xml`):
  `S-ROUTINE/S-FS/S-CWOP/S-IVP/S-OTHER/F-MSR/OBS/F-HA/F-DL` (field),
  `QC-FD/QC-FB/QC-EB/QC-TB/QC-LMS/QC-LMSD/QC-FS/QC-DL/QC-IS/QC-MPS/QC-REFS/
  QC-FCC/QC-FSERB/QC-HABITAT/QC-MSR/OBS/QC-OTHER`. `sample_source` enum:
  `Lab`/`Field`. Batch types: uppercase `PREP`/`ANALYSIS` (spec R5).
- **epar4** (`epar4_blank_edd.xlsx`): `EPAR4_FSample_v1` (WMRD-like:
  `sys_sample_code, sample_name, sample_matrix_code, sample_type_code,
  sample_source, parent_sample_code, sample_date, sample_time, sys_loc_code,
  start_depth, end_depth, depth_unit, ...`); `EPAR4_TST_v1` (30 cols:
  7-col composite + `lab_matrix_code, analysis_location, basis, container_id,
  dilution_factor, lab_prep_method_name, prep_date, prep_time, ...,
  lab_name_code, qc_level, lab_sample_id, ...`); `EPAR4_RES_v1` (43 cols:
  7-col composite + `cas_rn, chemical_name, result_value, result_error_delta,
  result_type_code, reportable_result, detect_flag, lab_qualifiers,
  validator_qualifiers, interpreted_qualifiers, organic_yn,
  method_detection_limit, reporting_detection_limit, quantitation_limit,
  result_unit, detection_limit_unit, ..., qc_*, test_batch_type,
  test_batch_id, validated_yn`). Shared 7-col composite:
  `sys_sample_code, lab_anl_method_name, analysis_date, analysis_time,
  total_or_dissolved, column_number, test_type`. No batch sheet.
  Sample types (`rt_sample_type`): `N` field; `FD` field dup; `LCS/LCSD/
  MS/MSD` spikes; `MBL` lab method blank; `EB` equipment rinse blank;
  `FL` field blank; `TB/TW/TS/TA` trip blanks. Batch types
  (`rt_test_batch_type`): `Prep`/`Analysis`/`Leach`. Fractions: `D/N/T`.
  Result types: `TRG/SUR/IS/SC/TIC/Field`.
- **NYSDEC v5** (`NYSDEC_v5_20260429_Blank_EDD_Template.xlsx`): `Sample_v5`
  (`data_provider, sys_sample_code, sample_name, sample_matrix_code,
  sample_type_code, sample_source, parent_sample_code, sample_delivery_group,
  sample_date, sys_loc_code, start_depth, end_depth, depth_unit, ...`);
  `TestResultQC_v5` (66 cols — WMRD vocabulary superset incl.
  `reporting_detection_limit`, qualifier trio, `qc_*`); `Batch_v5`
  (`sys_sample_code, lab_anl_method_name, analysis_date, fraction,
  column_number, test_type, test_batch_type, test_batch_id`) — the
  `analysis_date` column is the R6 trigger. Sample types (valid-values
  workbook): `N` field; `FD/FB/EB/TB` field QC; `LB` lab blank;
  `LCS/LCSD/LD/DUP/MS/MSD` lab QC. Batch types: uppercase
  `ANALYSIS/PREP/LABQC/MATRIXQC/LEACH`. Matrix codes: `WG` groundwater,
  `WS` surface water, `SO` soil, `SS` surface soil, `SIMP` imported soil,
  `SE/SED` sediment.

---

### Task 1: R1 xlsx engine + R2 header normalization

**Files:**
- Modify: `autogis/core/envmon/equis_reader.py` (replace `read_equis_xls`
  lines 59-85; add `_norm_header`, `_load_xls_sheets`, `_load_xlsx_sheets`,
  `_xlsx_cell_text`)
- Test: `tests/envmon/test_equis_xlsx_engine.py` (new)

**Interfaces:**
- Consumes: existing `_cell_text(cell, datemode)`, `transform_equis_sheets`.
- Produces: `read_equis_xls(path, profile, qa=None)` unchanged signature,
  now dispatching `.xlsx` → openpyxl; `_load_xls_sheets(path, names) ->
  dict[str, list[dict]]` and `_load_xlsx_sheets(path, names) ->
  dict[str, list[dict]]` (blank names skipped; keys = sheet names given);
  `_xlsx_cell_text(value) -> str`; `_norm_header(text) -> str`. Task 6
  appends `profile.test_sheet` to the names list.

- [ ] **Step 1: Write the failing tests**

```python
# tests/envmon/test_equis_xlsx_engine.py
"""R1 (.xlsx engine) + R2 (header casefold + '#' strip) — slice 2b."""
import datetime
from pathlib import Path

import openpyxl
import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.equis_reader import (
    _norm_header, _xlsx_cell_text, read_equis_xls,
)


def test_xlsx_cell_text_contract():
    # same contract as the xlrd _cell_text (R1)
    assert _xlsx_cell_text(None) == ""
    assert _xlsx_cell_text("  x  ") == "x"
    assert _xlsx_cell_text(5.0) == "5"
    assert _xlsx_cell_text(5.5) == "5.5"
    assert _xlsx_cell_text(7) == "7"
    assert _xlsx_cell_text(datetime.datetime(2025, 3, 17, 14, 2)) \
        == "03/17/2025 14:02"
    assert _xlsx_cell_text(datetime.datetime(2025, 3, 17)) == "03/17/2025"
    assert _xlsx_cell_text(datetime.date(2025, 3, 17)) == "03/17/2025"
    assert _xlsx_cell_text(datetime.time(14, 2)) == "14:02"


def test_norm_header_casefold_and_hash_strip():
    assert _norm_header("#Sample_ID") == "sample_id"
    assert _norm_header("Detect_Flag") == "detect_flag"
    assert _norm_header("sys_sample_code") == "sys_sample_code"   # WMRD no-op
    assert _norm_header("##x") == "#x"                            # ONE '#'
    assert _norm_header("") == ""


def _profile(**over):
    kw = dict(
        profile_id="t", lab_name="T", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sample_id"},
        matrix_map={}, nondetect_qualifiers=["U"],
        sample_sheet="Samples", result_sheet="Results", batch_sheet="",
        value_maps={"qc_sample_type": {"N": ""}},
    )
    kw.update(over)
    return LabEDDProfile(**kw)


def test_read_xlsx_titlecase_headers_land_on_equis_names(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Samples"
    ws.append(["#Sample_ID", "Sample_Type", "Sample_Source", "Matrix"])
    ws.append(["S-1", "N", "Field", "GW"])
    rs = wb.create_sheet("Results")
    rs.append(["#Sample_ID", "Result_Value", "Detect_Flag",
               "Analysis_Date", "Dilution_Factor"])
    rs.append(["S-1", 12.0, "Y", datetime.datetime(2025, 3, 17, 14, 2), 1])
    path = tmp_path / "t.xlsx"
    wb.save(path)

    rows = read_equis_xls(path, _profile(), QACollector())
    assert len(rows) == 1
    row = rows[0]
    assert row["__equis_result"] == "12"           # int-valued float
    assert row["analysis_date"] == "03/17/2025 14:02"
    assert row["sample_source"] == "Field"          # sample merge worked
    assert row["__source_row"] == 2


def test_read_xls_still_works_and_strips_hash(tmp_path):
    # the shipped WMRD .xls fixture goes through the same normalization
    fixture = (Path(__file__).parent.parent / "fixtures"
               / "wmrd_equis_fixture.xls")
    import autogis
    prof = LabEDDProfile.load(
        Path(autogis.__file__).parent / "config" / "lab_profiles"
        / "wmrd.yaml")
    rows = read_equis_xls(fixture, prof, QACollector())
    assert len(rows) == 9
    # header '#sys_sample_code' now lands casefolded+stripped
    assert "sys_sample_code" in rows[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_xlsx_engine.py -q`
Expected: FAIL / ERROR with `ImportError: cannot import name '_norm_header'`

- [ ] **Step 3: Implement**

In `equis_reader.py`, replace `read_equis_xls` and `_sheet_to_dicts` (the
closure inside it) with:

```python
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
                           profile.batch_sheet])
    return transform_equis_sheets(sheets.get(profile.sample_sheet, []),
                                  sheets.get(profile.result_sheet, []),
                                  sheets.get(profile.batch_sheet, []),
                                  profile, qa)


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
```

Also update the module docstring's "xlrd is lazy-imported" line to
"xlrd/openpyxl are lazy-imported in the sheet loaders only" and drop the
"Mining's renamed cousins are a later slice" sentence (this IS that slice).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_equis_xlsx_engine.py tests/envmon/test_equis_reader.py tests/envmon/test_equis_e2e.py -q`
Expected: all PASS (existing WMRD tests pin the no-op property)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/equis_reader.py tests/envmon/test_equis_xlsx_engine.py
git commit -m "feat(envmon): equis xlsx engine + load-time header normalization (2b R1/R2)"
```

### Task 2: R3 `source_aliases:` profile key + application

**Files:**
- Modify: `autogis/core/envmon/edd_profile.py` (dataclass + `load`)
- Modify: `autogis/core/envmon/equis_reader.py` (`transform_equis_sheets`)
- Test: `tests/envmon/test_equis_dialect_transforms.py` (new)

**Interfaces:**
- Consumes: `transform_equis_sheets(sample_rows, result_rows, batch_rows,
  profile, qa)`; `LabEDDProfile`.
- Produces: `LabEDDProfile.source_aliases: dict[str, str]` (default `{}`,
  loaded from YAML key `source_aliases`); `_apply_source_aliases(rows,
  aliases) -> None` applied to every sheet's rows at the top of
  `transform_equis_sheets`. Tasks 3/6/8 rely on aliased rows carrying BOTH
  the source and destination keys.

- [ ] **Step 1: Write the failing tests**

```python
# tests/envmon/test_equis_dialect_transforms.py
"""Slice-2b dialect transforms: R3 aliases, R5 inline batch, R6 extended
batch join, R4 test-sheet join, R9 run token. Pure dict rows."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.equis_reader import transform_equis_sheets

MINING_ALIASES = {
    "analytical_method_id": "lab_anl_method_name",
    "sample_fraction": "fraction",
    "result_value_unit": "result_unit",
    "lower_reporting_limit": "reporting_detection_limit",
    "lab_batch_id": "test_batch_id",
    "batch_type": "test_batch_type",
    "lab_name": "lab_name_code",
    "sample_type": "sample_type_code",
}


def _profile(**over):
    kw = dict(
        profile_id="t", lab_name="T", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sample_id"},
        matrix_map={}, nondetect_qualifiers=["U"],
        sample_sheet="LabCollection", result_sheet="LabResult",
        batch_sheet="",
        value_maps={"qc_sample_type": {
            "S-ROUTINE": "", "QC-FD": "FIELD_DUP", "QC-LMS": "MS"}},
    )
    kw.update(over)
    return LabEDDProfile(**kw)


def _mining_sample(**over):
    row = {"sample_id": "M-001", "sample_type": "S-ROUTINE",
           "matrix": "GW", "sample_source": "Field",
           "parent_sample_id": "", "sample_date": "03/11/2025 09:54",
           "station_id": "STA-1"}
    row.update(over)
    return row


def _mining_result(**over):
    row = {"sample_id": "M-001", "analytical_method_id": "E200.8",
           "analysis_date": "03/17/2025 14:02", "sample_fraction": "T",
           "test_type": "INITIAL", "basis": "NA", "dilution_factor": "1",
           "lab_name": "ELI", "characteristic_id": "7439-92-1",
           "characteristic_name": "Lead", "result_value": "12.4",
           "result_value_unit": "mg/L", "detect_flag": "Y",
           "reportable_result": "Yes", "lab_qualifiers": "",
           "interpreted_qualifiers": "", "method_detection_limit": "0.1",
           "lower_reporting_limit": "0.5", "quantitation_limit": "1.0",
           "detection_limit_unit": "mg/L", "lab_batch_id": "",
           "batch_type": "", "result_type_code": "TRG"}
    row.update(over)
    return row


def _run(samples, results, batches=(), profile=None):
    qa = QACollector()
    out = transform_equis_sheets(list(samples), list(results), list(batches),
                                 profile or _profile(), qa)
    return out, qa


def test_aliases_bridge_mining_columns_to_synthesis():
    prof = _profile(source_aliases=dict(MINING_ALIASES))
    out, qa = _run([_mining_sample()], [_mining_result()], profile=prof)
    assert len(out) == 1
    row = out[0]
    assert row["__equis_result"] == "12.4"
    assert row["__equis_units"] == "mg/L"               # result_value_unit
    assert row["__equis_reporting_limit"] == "0.5"      # lower_reporting_limit
    # method reached the analytical dilution-key fold via the alias
    assert "E200.8" in row["__equis_method_dilution_key"]
    # source column kept (profile columns: maps may reference it)
    assert row["analytical_method_id"] == "E200.8"


def test_alias_sample_type_bridge_routes_mining_lab_qc():
    # P1 (PR #243): without sample_type -> sample_type_code the reader's
    # stream discriminator never sees Mining's QC codes.
    prof = _profile(source_aliases=dict(MINING_ALIASES))
    out, _ = _run(
        [_mining_sample(sample_id="LMS-1", sample_type="QC-LMS",
                        sample_source="Lab")],
        [_mining_result(sample_id="LMS-1")], profile=prof)
    assert out[0]["__equis_stream"] == "qc"
    assert out[0]["__equis_qc_type"] == "MS"


def test_alias_sample_type_bridge_routes_field_duplicate():
    prof = _profile(source_aliases=dict(MINING_ALIASES))
    out, _ = _run(
        [_mining_sample(sample_id="FD-1", sample_type="QC-FD")],
        [_mining_result(sample_id="FD-1")], profile=prof)
    assert out[0].get("__equis_stream") != "qc"          # field stream
    assert out[0]["__equis_qc_type"] == "FIELD_DUP"


def test_no_aliases_is_a_noop():
    out, _ = _run([_mining_sample(sample_type="S-ROUTINE")],
                  [_mining_result()])
    # without the bridge the ND/method synthesis inputs are absent
    assert "lab_anl_method_name" not in out[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'source_aliases'`

- [ ] **Step 3: Implement**

`edd_profile.py` — add to the dataclass after `batch_sheet`:

```python
    source_aliases: dict[str, str] = field(default_factory=dict)  # equis_xls only (R3)
```

and in `load()` after the `batch_sheet=` line:

```python
            source_aliases=data.get("source_aliases", {}),
```

`equis_reader.py` — add above `transform_equis_sheets`:

```python
def _apply_source_aliases(rows: list[dict], aliases: dict[str, str]) -> None:
    """R3: bridge a dialect's renamed source columns onto the EQuIS names the
    ``_COL_*`` synthesis rules read. The source key is kept — profile
    ``columns:`` maps may still reference it. Applied after R2 (keys are
    already casefolded), before any synthesis."""
    for row in rows:
        for src, dst in aliases.items():
            if src in row and dst not in row:
                row[dst] = row[src]
```

and at the top of `transform_equis_sheets` (before `sample_index = {}`):

```python
    if profile.source_aliases:
        for rows in (sample_rows, result_rows, batch_rows):
            _apply_source_aliases(rows, profile.source_aliases)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py tests/envmon/test_edd_profile.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_profile.py autogis/core/envmon/equis_reader.py tests/envmon/test_equis_dialect_transforms.py
git commit -m "feat(envmon): source_aliases profile bridge for dialect columns (2b R3)"
```

### Task 3: R5 inline-batch fallback + case-insensitive batch types

**Files:**
- Modify: `autogis/core/envmon/equis_reader.py` (`transform_equis_sheets`
  batch-index build, `_attach_batches`; new `_attach_inline_batch`)
- Test: `tests/envmon/test_equis_dialect_transforms.py` (append)

**Interfaces:**
- Consumes: `_get`, `_COL_BATCH_TYPE`, `_COL_BATCH_ID`, `batch_index`.
- Produces: batch-index inner dict keyed by CASEFOLDED type
  (`"prep"`/`"analysis"`); `_attach_inline_batch(row, qa, row_num)` used when
  `batch_rows` is empty; QA code `equis_unknown_batch_type`.

- [ ] **Step 1: Write the failing tests** (append to
  `tests/envmon/test_equis_dialect_transforms.py`)

```python
def _wmrd_profile(**over):
    kw = dict(
        profile_id="w", lab_name="W", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sys_sample_code"},
        matrix_map={}, nondetect_qualifiers=["U"],
        sample_sheet="Sample_v1", result_sheet="TestResultQC_v1",
        batch_sheet="Batch_v1",
        value_maps={"qc_sample_type": {"N": ""}},
    )
    kw.update(over)
    return LabEDDProfile(**kw)


def _equis_sample(**over):
    row = {"sys_sample_code": "S-1", "sample_matrix_code": "WQ",
           "sample_type_code": "N", "sample_source": "Field",
           "parent_sample_code": "", "sample_date": "03/11/2025",
           "sys_loc_code": "MW-1"}
    row.update(over)
    return row


def _equis_result(**over):
    row = {"sys_sample_code": "S-1", "lab_anl_method_name": "E200.8",
           "analysis_date": "03/17/2025", "fraction": "T",
           "column_number": "NA", "test_type": "INITIAL", "basis": "NA",
           "dilution_factor": "1", "cas_rn": "7439-92-1",
           "chemical_name": "Lead", "result_value": "12.4",
           "result_type_code": "TRG", "reportable_result": "Yes",
           "detect_flag": "Y", "result_unit": "mg/L",
           "detection_limit_unit": "mg/L"}
    row.update(over)
    return row


def test_batch_sheet_types_match_case_insensitively():
    # NYSDEC Batch_v5 carries uppercase PREP/ANALYSIS
    batch = {"sys_sample_code": "S-1", "lab_anl_method_name": "E200.8",
             "fraction": "T", "column_number": "NA", "test_type": "INITIAL",
             "test_batch_type": "PREP", "test_batch_id": "PB-9"}
    out, _ = _run([_equis_sample()], [_equis_result()], [batch],
                  profile=_wmrd_profile())
    assert out[0]["__equis_prep_batch"] == "PB-9"


def test_inline_batch_prep_populates_both_ids():
    # key-safety (P1): AnalysisBatchID is the frozen key part, PrepBatchID
    # is not — a prep-typed inline id must reach AnalysisBatchID too.
    out, qa = _run([_equis_sample()],
                   [_equis_result(test_batch_type="PREP",
                                  test_batch_id="PB-1")],
                   profile=_wmrd_profile(batch_sheet=""))
    assert out[0]["__equis_prep_batch"] == "PB-1"
    assert out[0]["__equis_analysis_batch"] == "PB-1"
    assert not [i for i in qa.issues
                if i.code == "equis_unknown_batch_type"]


def test_inline_batch_analysis_type():
    out, _ = _run([_equis_sample()],
                  [_equis_result(test_batch_type="Analysis",
                                 test_batch_id="AB-1")],
                  profile=_wmrd_profile(batch_sheet=""))
    assert out[0]["__equis_prep_batch"] == ""
    assert out[0]["__equis_analysis_batch"] == "AB-1"


def test_inline_batch_unknown_type_warns_and_stays_empty():
    out, qa = _run([_equis_sample()],
                   [_equis_result(test_batch_type="LEACH",
                                  test_batch_id="LB-1")],
                   profile=_wmrd_profile(batch_sheet=""))
    assert out[0]["__equis_prep_batch"] == ""
    assert out[0]["__equis_analysis_batch"] == ""
    assert [i for i in qa.issues if i.code == "equis_unknown_batch_type"]


def test_no_batch_columns_no_warn():
    out, qa = _run([_equis_sample()], [_equis_result()],
                   profile=_wmrd_profile(batch_sheet=""))
    assert out[0]["__equis_analysis_batch"] == ""
    assert not [i for i in qa.issues
                if i.code == "equis_unknown_batch_type"]
```

NOTE: check `QACollector`'s issue-list attribute name in
`autogis/core/common/qa.py` before running (existing tests use the same
access pattern — copy whatever `test_equis_reader.py` uses to assert on QA
codes, e.g. `qa.issues` / `qa.records`; adjust the four assertions if the
attribute differs).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py -q`
Expected: new tests FAIL (case-sensitive lookup returns ""; inline ids empty)

- [ ] **Step 3: Implement**

In `transform_equis_sheets`, the batch-index insert becomes (casefolded
type key; values were `"Prep"`/`"Analysis"` — slice-1 WMRD vocabulary, not a
contract):

```python
        batch_index.setdefault(key, {})[
            _get(b, _COL_BATCH_TYPE).casefold()] = _get(b, _COL_BATCH_ID)
```

Replace `_attach_batches` with:

```python
def _attach_batches(row: dict, batch_index: dict, batch_rows: list[dict],
                    sample_id: str, profile, qa: QACollector,
                    row_num: int) -> None:
    if not batch_rows:
        _attach_inline_batch(row, qa, row_num)
        return
    key = (sample_id, _get(row, _COL_METHOD), _get(row, _COL_FRACTION),
           _get(row, _COL_COLUMN_NUM), _get(row, _COL_TEST_TYPE).casefold())
    hit = batch_index.get(key, {})
    row["__equis_prep_batch"] = hit.get("prep", "")
    row["__equis_analysis_batch"] = hit.get("analysis", "")
    if not hit:
        qa.add(SEV_WARNING, "equis_missing_batch",
               f"Row {row_num}: no batch-sheet entry for "
               f"({sample_id}, {key[1]}, {key[2]}, {key[3]}, {key[4]}) — "
               f"batch ids empty", source_row=row_num)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py tests/envmon/test_equis_reader.py tests/envmon/test_equis_e2e.py -q`
Expected: PASS (WMRD `"Prep"`/`"Analysis"` values casefold onto the same keys)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/equis_reader.py tests/envmon/test_equis_dialect_transforms.py
git commit -m "feat(envmon): inline-batch fallback + case-insensitive batch types (2b R5)"
```

### Task 4: R6 batch join composite extends with analysis_date

**Files:**
- Modify: `autogis/core/envmon/equis_reader.py`
- Test: `tests/envmon/test_equis_dialect_transforms.py` (append)

**Interfaces:**
- Consumes: Task-3 `_attach_batches`.
- Produces: module constant `_COL_ANALYSIS_DATE = "analysis_date"`;
  `_attach_batches(..., join_date: bool)` extra parameter; batch-index keys
  gain a 6th element when `join_date` is True.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _batch(**over):
    row = {"sys_sample_code": "S-1", "lab_anl_method_name": "E200.8",
           "fraction": "T", "column_number": "NA", "test_type": "INITIAL",
           "test_batch_type": "Analysis", "test_batch_id": "AB-1"}
    row.update(over)
    return row


def test_batch_join_extends_with_analysis_date_when_both_carry_it():
    # NYSDEC Batch_v5: two batches for the same test differing only by date
    batches = [_batch(analysis_date="03/17/2025", test_batch_id="AB-1"),
               _batch(analysis_date="03/18/2025", test_batch_id="AB-2")]
    out, _ = _run([_equis_sample()],
                  [_equis_result(analysis_date="03/18/2025")],
                  batches, profile=_wmrd_profile())
    assert out[0]["__equis_analysis_batch"] == "AB-2"


def test_batch_join_stays_5col_when_batch_lacks_analysis_date():
    # WMRD Batch_v1 has no analysis_date: result date must NOT enter the key
    out, _ = _run([_equis_sample()],
                  [_equis_result(analysis_date="03/18/2025")],
                  [_batch()], profile=_wmrd_profile())
    assert out[0]["__equis_analysis_batch"] == "AB-1"


def test_batch_join_date_mismatch_warns_missing():
    batches = [_batch(analysis_date="03/17/2025")]
    out, qa = _run([_equis_sample()],
                   [_equis_result(analysis_date="03/18/2025")],
                   batches, profile=_wmrd_profile())
    assert out[0]["__equis_analysis_batch"] == ""
    assert [i for i in qa.issues if i.code == "equis_missing_batch"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py -q`
Expected: first and third new tests FAIL (5-col join matches both batches;
last-write-wins gives AB-2/AB-1 wrongly)

- [ ] **Step 3: Implement**

Add the constant next to the other `_COL_*` constants:

```python
_COL_ANALYSIS_DATE = "analysis_date"
```

In `transform_equis_sheets`, before the batch-index loop:

```python
    # R6: NYSDEC's Batch_v5 adds analysis_date to the 5-column composite;
    # WMRD's 5-column join is byte-identical when the column is absent.
    join_date = bool(batch_rows and _COL_ANALYSIS_DATE in batch_rows[0]
                     and result_rows and _COL_ANALYSIS_DATE in result_rows[0])
```

and the index key becomes:

```python
        key = (_get_sample_id(b, profile), _get(b, _COL_METHOD),
               _get(b, _COL_FRACTION), _get(b, _COL_COLUMN_NUM),
               _get(b, _COL_TEST_TYPE).casefold()) \
            + ((_get(b, _COL_ANALYSIS_DATE),) if join_date else ())
```

Thread `join_date` through the `_attach_batches` call
(`_attach_batches(row, batch_index, batch_rows, sample_id, profile, qa,
row_num, join_date)`) and extend its lookup key the same way:

```python
    key = (sample_id, _get(row, _COL_METHOD), _get(row, _COL_FRACTION),
           _get(row, _COL_COLUMN_NUM), _get(row, _COL_TEST_TYPE).casefold()) \
        + ((_get(row, _COL_ANALYSIS_DATE),) if join_date else ())
```

(signature: `def _attach_batches(row, batch_index, batch_rows, sample_id,
profile, qa, row_num, join_date=False)`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py tests/envmon/test_equis_reader.py tests/envmon/test_equis_e2e.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/equis_reader.py tests/envmon/test_equis_dialect_transforms.py
git commit -m "feat(envmon): batch join composite extends with analysis_date (2b R6)"
```

### Task 5: 2b ADR — accepts the R4 profile-shape amendment (GATES Task 6)

**Files:**
- Create: `docs/adr/XXXX-edd-step3-slice2b-dialects.md`

**Interfaces:**
- Produces: the committed ADR whose existence unlocks R4 (Task 6). The
  heading stays `XXXX`; it is renumbered against origin/main AND open PRs at
  ship time (collision history: 0030/0034/0061/0063/0071/0074/0076).

- [ ] **Step 1: Write the ADR** (follow `docs/adr/TEMPLATE.md` structure;
  full content below, adjust only formatting to the template):

```markdown
# XXXX. EDD Step-3 slice 2b — mining/epar4/NYSDEC dialect support

Date: 2026-07-17

## Status

Accepted

## Context

Slice 1 (ADR-0082) shipped the EQuIS v1 WMRD reader (`equis_reader.py`,
xlrd-only `.xls`, three-sheet Sample/TestResultQC/Batch shape). The slice-2
design spec (`docs/superpowers/specs/2026-07-12-edd-step3-slice2-design.md`,
PR #243) recorded template-verified facts for three further dialects — MTDEQ
Mining, EPA Region 4 (epar4), NYSDEC v5 — all `.xlsx`, all EQuIS-vocabulary
cousins with structural deltas: Mining renames ~10 columns and carries inline
batch ids; epar4 splits Test/Result into two sheets joined by a 7-column
composite and has no batch sheet; NYSDEC extends the batch join with
`analysis_date`. ADR-0084 froze the unique-key compositions and rejected
key widening and run-instance ordinals; QC rerun collisions ERROR-block by
design (#244).

## Decision

Implement the spec's R1–R9 as reader/profile extensions (no new reader, no
new dependency, zero CLI change):

- **R1** `read_equis_xls` dispatches by extension: `.xls` → xlrd (unchanged),
  `.xlsx` → openpyxl (existing dep, read-only, lazy import) normalizing cell
  text to the same contract (`_xlsx_cell_text`). Format id stays `equis_xls`.
- **R2** headers casefold + strip one leading `#` at load, both engines.
- **R3** new optional profile key `source_aliases: dict[str, str]` renames a
  dialect's outlier source columns onto the EQuIS canonical names before
  synthesis, so every `_COL_*` rule works untouched.
- **R4** new optional profile key `test_sheet:` — epar4's `EPAR4_TST_v1`
  rows are indexed by the shared 7-column composite and merged under the
  result row (result wins); a miss is QA-WARN `equis_missing_test` +
  fail-safe import. **This ADR explicitly accepts the amendment of
  ADR-0075's "flat and 2-sheet-shaped permanently" `LabEDDProfile` freeze**
  to admit `test_sheet:` (and the `source_aliases:` mapping key), following
  the precedent of slice 1's `batch_sheet` key (ADR-0082). All field
  mappings remain in profile YAML; the profile remains declarative.
- **R5** inline-batch fallback: with no batch sheet, a row's single
  `test_batch_type`/`test_batch_id` pair routes by type, case-insensitively
  (Mining/NYSDEC record uppercase PREP/ANALYSIS); a prep-typed id also
  fills `__equis_analysis_batch` because `AnalysisBatchID` — not
  PrepBatchID — is the frozen Env_QCResults key part. Unknown type → both
  empty + `equis_unknown_batch_type` WARN. Batch-sheet type lookups are
  case-insensitive too (slice-1's exact-case `Prep`/`Analysis` was WMRD
  vocabulary, not a contract).
- **R6** the batch join composite extends with `analysis_date` when both
  the batch and result sheets carry the column (NYSDEC `Batch_v5`); WMRD's
  5-column join is byte-identical when absent (pinned by existing tests).
- **R7** three DRAFT profiles (`mining.yaml`, `epar4.yaml`, `nysdec.yaml`),
  template-verified only; vocabularies seeded from the MTDEQ enum XML, the
  epar4 `rt_*` sheets, and the NYSDEC valid-values workbook. Unmapped
  values fail safe with QA-WARN (ADR-0080/D10 policy). Banners stay until
  verified against a real deliverable (wqx.yaml precedent).
- **R8** zero CLI change — dispatch entirely via `format: equis_xls`.
- **R9** when a profile sets `test_sheet:` (epar4), the reader folds a
  bounded digits-only token from the composite's
  `analysis_date`+`analysis_time` into the `MethodDilutionKey` value recipe
  (ADR-0075 §3 escape hatch, same mechanism as ADR-0084 §1's method fold) —
  per-row, source-alone deterministic — so two reanalyses differing only by
  date/time key distinctly on both tables (`MethodDilutionKey` is a frozen
  key part of both). Worst-case composed value (4 run parts + method +
  12-digit token) stays far below the TEXT(64) `detect_overlength_keys`
  guard. The token also feeds the #244 run-identity design.

## Consequences

- The frozen key compositions are untouched; no run-instance ordinals exist.
  Dialect QC rerun collisions (non-epar4) still ERROR-block by design (#244).
- `LabEDDProfile` is now declaratively up-to-4-sheet-shaped
  (`sample_sheet`/`result_sheet`/`batch_sheet`/`test_sheet`); ADR-0075's
  freeze is amended exactly that far and no further.
- The three profiles are DRAFT: first production import of each dialect must
  be verified against a real deliverable before banner removal.
- Committed fixtures are synthetic openpyxl-generated `.xlsx` (template
  headers + invented rows); no client data enters the repo.
```

- [ ] **Step 2: Commit**

```bash
git add docs/adr/XXXX-edd-step3-slice2b-dialects.md
git commit -m "docs(adr): slice-2b dialect decisions + ADR-0075 test_sheet amendment (gates R4)"
```

(`docs/adr/README.md` index row is added at ship time when the final number
is assigned.)

### Task 6: R4 `test_sheet:` join (epar4 TST/RES split)

**Files:**
- Modify: `autogis/core/envmon/edd_profile.py` (`test_sheet` field + load)
- Modify: `autogis/core/envmon/equis_reader.py` (loader names list,
  `transform_equis_sheets` signature + test index + merge)
- Test: `tests/envmon/test_equis_dialect_transforms.py` (append)

**Interfaces:**
- Consumes: Task-1 loaders, Task-2 aliasing, Task-5 ADR (gate — verify the
  ADR file exists on the branch before writing code).
- Produces: `LabEDDProfile.test_sheet: str = ""` (YAML key `test_sheet`);
  `transform_equis_sheets(sample_rows, result_rows, batch_rows, profile, qa,
  test_rows=None)`; constant `_COL_ANALYSIS_TIME = "analysis_time"`; QA code
  `equis_missing_test`. Task 7 keys the R9 token off `profile.test_sheet`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _epar4_profile(**over):
    kw = dict(
        profile_id="e", lab_name="E", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sys_sample_code"},
        matrix_map={}, nondetect_qualifiers=["U"],
        sample_sheet="EPAR4_FSample_v1", result_sheet="EPAR4_RES_v1",
        batch_sheet="", test_sheet="EPAR4_TST_v1",
        source_aliases={"total_or_dissolved": "fraction",
                        "lab_prep_method_name": "prep_method"},
        value_maps={"qc_sample_type": {"N": ""}},
    )
    kw.update(over)
    return LabEDDProfile(**kw)


def _tst(**over):
    row = {"sys_sample_code": "S-1", "lab_anl_method_name": "E200.8",
           "analysis_date": "03/17/2025", "analysis_time": "14:02",
           "total_or_dissolved": "T", "column_number": "NA",
           "test_type": "initial", "basis": "NA", "dilution_factor": "5",
           "lab_prep_method_name": "E200.2", "lab_name_code": "ELI",
           "lab_sample_id": "L-1"}
    row.update(over)
    return row


def _res(**over):
    row = _equis_result(analysis_time="14:02",
                        total_or_dissolved="T")
    del row["fraction"]          # epar4 says total_or_dissolved
    del row["dilution_factor"]   # dilution lives on the TST sheet
    del row["basis"]
    row["test_type"] = "initial"
    row.update(over)
    return row


def _run_epar4(samples, results, tests, profile=None):
    qa = QACollector()
    out = transform_equis_sheets(list(samples), list(results), [],
                                 profile or _epar4_profile(), qa,
                                 test_rows=list(tests))
    return out, qa


def test_test_sheet_merges_under_result_row():
    out, qa = _run_epar4([_equis_sample()], [_res()], [_tst()])
    assert len(out) == 1
    row = out[0]
    assert row["lab_sample_id"] == "L-1"          # TST-side field arrived
    # TST dilution + basis reached the dilution-key fold
    assert row["__equis_method_dilution_key"].startswith("5|")
    assert not [i for i in qa.issues if i.code == "equis_missing_test"]


def test_result_columns_win_on_collision():
    out, _ = _run_epar4([_equis_sample()],
                        [_res(lab_anl_method_name="E300.0")],
                        [_tst(lab_anl_method_name="E300.0",
                              comment="tst-comment")])
    assert out[0]["lab_anl_method_name"] == "E300.0"
    assert out[0]["comment"] == "tst-comment"


def test_missing_test_entry_warns_and_imports():
    out, qa = _run_epar4([_equis_sample()],
                         [_res(analysis_time="09:00")], [_tst()])
    assert len(out) == 1                          # fail-safe: row imports
    assert [i for i in qa.issues if i.code == "equis_missing_test"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py -q`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'test_sheet'`

- [ ] **Step 3: Implement**

`edd_profile.py` — after `source_aliases`:

```python
    test_sheet: str = ""                     # equis_xls only (R4, ADR XXXX)
```

and in `load()`:

```python
            test_sheet=data.get("test_sheet", ""),
```

`equis_reader.py`:

1. `read_equis_xls` names list gains the test sheet and the call gains
   `test_rows`:

```python
    sheets = loader(path, [profile.sample_sheet, profile.result_sheet,
                           profile.batch_sheet, profile.test_sheet])
    return transform_equis_sheets(sheets.get(profile.sample_sheet, []),
                                  sheets.get(profile.result_sheet, []),
                                  sheets.get(profile.batch_sheet, []),
                                  profile, qa,
                                  test_rows=sheets.get(profile.test_sheet, []))
```

2. Constant: `_COL_ANALYSIS_TIME = "analysis_time"`.

3. `transform_equis_sheets` signature becomes:

```python
def transform_equis_sheets(sample_rows: list[dict], result_rows: list[dict],
                           batch_rows: list[dict], profile,
                           qa: QACollector,
                           test_rows: Optional[list[dict]] = None) -> list[dict]:
```

`test_rows = test_rows or []`; include `test_rows` in the R3 aliasing loop
(`for rows in (sample_rows, result_rows, batch_rows, test_rows):`).

4. After the batch index build:

```python
    # R4 (ADR XXXX): epar4 splits Test and Result into two sheets sharing a
    # 7-column composite; index the test sheet and merge under each result
    # row. fraction is the post-alias name (total_or_dissolved bridged by R3).
    test_index: dict[tuple, dict] = {}
    for t in test_rows:
        test_index[_test_key(t, _get_sample_id(t, profile))] = t
```

with the helper:

```python
def _test_key(row: dict, sample_id: str) -> tuple:
    return (sample_id, _get(row, _COL_METHOD),
            _get(row, _COL_ANALYSIS_DATE), _get(row, _COL_ANALYSIS_TIME),
            _get(row, _COL_FRACTION), _get(row, _COL_COLUMN_NUM),
            _get(row, _COL_TEST_TYPE).casefold())
```

5. In the result loop, between `row = dict(sample)` and `row.update(src)`:

```python
        if test_rows:
            test = test_index.get(_test_key(src, sample_id))
            if test is None:
                qa.add(SEV_WARNING, "equis_missing_test",
                       f"Row {row_num}: no test-sheet entry for sample "
                       f"'{sample_id}' — test-side fields empty",
                       source_row=row_num)
            else:
                row.update(test)
        row.update(src)             # result columns win on collision
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py tests/envmon/test_edd_profile.py tests/envmon/test_equis_reader.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_profile.py autogis/core/envmon/equis_reader.py tests/envmon/test_equis_dialect_transforms.py
git commit -m "feat(envmon): test_sheet join for epar4 TST/RES split (2b R4, ADR-gated)"
```

### Task 7: R9 epar4 run-identity token in MethodDilutionKey

**Files:**
- Modify: `autogis/core/envmon/equis_reader.py` (`_compose_dilution_key` +
  its call site; `import re` at module top)
- Test: `tests/envmon/test_equis_dialect_transforms.py` (append)

**Interfaces:**
- Consumes: Task-6 `profile.test_sheet`, `_COL_ANALYSIS_DATE`,
  `_COL_ANALYSIS_TIME`.
- Produces: `_compose_dilution_key(row, run_token="")`; the token appears as
  the final `|`-joined part on BOTH streams when `profile.test_sheet` is set.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_run_token_distinguishes_reanalyses():
    # R9: two valid reanalyses differing only by analysis_time must compute
    # distinct MethodDilutionKey values (frozen key part on both tables).
    out, _ = _run_epar4(
        [_equis_sample()],
        [_res(analysis_time="10:00"), _res(analysis_time="14:30")],
        [_tst(analysis_time="10:00"), _tst(analysis_time="14:30")])
    keys = {r["__equis_method_dilution_key"] for r in out}
    assert len(keys) == 2
    # bounded digits-only token, e.g. ...|031720251000
    assert any(k.endswith("031720251000") for k in keys)


def test_run_token_absent_without_test_sheet():
    # WMRD/mining/nysdec profiles (no test_sheet) — key recipe unchanged
    out, _ = _run([_equis_sample()], [_equis_result()],
                  profile=_wmrd_profile(batch_sheet=""))
    assert "0317" not in out[0]["__equis_method_dilution_key"]


def test_run_token_empty_dates_add_no_part():
    out, _ = _run_epar4([_equis_sample()],
                        [_res(analysis_date="", analysis_time="")],
                        [_tst(analysis_date="", analysis_time="")])
    assert not out[0]["__equis_method_dilution_key"].endswith("|")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py -q`
Expected: first test FAILS (both rows share one key)

- [ ] **Step 3: Implement**

Add `import re` to the module's imports. `_compose_dilution_key` becomes:

```python
def _compose_dilution_key(row: dict, run_token: str = "") -> None:
    # Per-row fold (ADR-0080 determinism argument); WMRD's literal 'NA' nulls
    # normalized out so an undiluted INITIAL run keys compatibly with formats
    # that leave the columns blank.
    parts = [_na(_get(row, _COL_DILUTION)), _na(_get(row, _COL_TEST_TYPE)),
             _na(_get(row, _COL_COLUMN_NUM)), _na(_get(row, _COL_BASIS))]
    # ADR-0084 §1: [keep the existing method-fold comment verbatim]
    if row.get("__equis_stream") != "qc":
        parts.append(_na(_get(row, _COL_METHOD)))
    # R9 (ADR XXXX): epar4's TST composite treats analysis date/time as the
    # run identity, but neither survives into the frozen keys — the bounded
    # token makes reanalyses key distinctly on both tables. Worst case
    # (4 parts + method + 12 digits) stays far below the TEXT(64) guard.
    if run_token:
        parts.append(run_token)
    row["__equis_method_dilution_key"] = "|".join(p for p in parts if p)
```

Call site in the result loop:

```python
        run_token = ""
        if profile.test_sheet:
            run_token = re.sub(r"\D", "",
                               _get(row, _COL_ANALYSIS_DATE)
                               + _get(row, _COL_ANALYSIS_TIME))
        _compose_dilution_key(row, run_token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_equis_dialect_transforms.py tests/envmon/test_equis_e2e.py -q`
Expected: PASS (`test_rerun_flags_and_dilution_keys` pins the WMRD key
string unchanged — proves the token is test_sheet-gated)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/equis_reader.py tests/envmon/test_equis_dialect_transforms.py
git commit -m "feat(envmon): epar4 run-identity token in MethodDilutionKey recipe (2b R9)"
```

### Task 8: mining.yaml + fixture + e2e

**Files:**
- Create: `autogis/config/lab_profiles/mining.yaml`
- Create: `tests/fixtures/make_mining_fixture.py`
- Create: `tests/fixtures/mining_edd_fixture.xlsx` (generated, committed)
- Test: `tests/envmon/test_mining_e2e.py` (new)

**Interfaces:**
- Consumes: Tasks 1–5 (no test_sheet, no batch sheet — inline R5 path).
- Produces: shipped `mining.yaml` loadable by `LabEDDProfile.load`.

- [ ] **Step 1: Write the profile**

```yaml
# autogis/config/lab_profiles/mining.yaml
# MTDEQ Mining EDD (.xlsx, LabCollection + LabResult) — Step-3 slice 2b.
#
# *** DRAFT — verify against a real filled Mining EDD before first
# production import; do not remove this banner until then (wqx.yaml
# precedent). ***
# Structure verified against the blank template + description workbook +
# MTDEQ_Mining-enum.xml (2026-07-12 / 2026-07-17); no real filled EDD
# exists yet. Headers are casefolded and '#'-stripped at load (R2), so all
# names below are lowercase — TitleCase source headers (Detect_Flag,
# Result_Value, ...) land on the EQuIS constants for free. Unmapped values
# fail safe: unknown sample types import QC-flagged (hidden from canonical
# reads) + QA-WARN; unmapped matrix codes pass through raw + WARN.
# Reader: autogis/core/envmon/equis_reader.py (synthesized __equis_*).
profile_id: mining
lab_name: MTDEQ Mining EDD
format: equis_xls
date_format: "%m/%d/%Y"
encoding: utf-8

# Sheet names stay real-case; only headers are casefolded (R2/R7).
sample_sheet: LabCollection
result_sheet: LabResult
# No batch sheet: Lab_Batch_ID / Batch_Type are inline on LabResult (R5).

# R3: bridge Mining's renamed columns onto the EQuIS names the reader's
# _COL_* synthesis rules read (post-R2, so keys are casefolded).
source_aliases:
  analytical_method_id: lab_anl_method_name
  sample_fraction: fraction
  result_value_unit: result_unit
  lower_reporting_limit: reporting_detection_limit
  lab_batch_id: test_batch_id
  batch_type: test_batch_type
  lab_name: lab_name_code
  sample_type: sample_type_code

columns:
  # identity / joins
  sample_id: sample_id
  parent_sample_id: parent_sample_id
  lab_sample_id: lab_sample_id
  location_id: station_id
  event_date: sample_date
  matrix: matrix
  depth_top_ft: sample_start_depth
  depth_bot_ft: sample_end_depth
  # analyte / method
  analyte: characteristic_name
  cas_number: characteristic_id
  method: lab_anl_method_name
  method_name: lab_anl_method_name
  method_speciation: method_speciation
  result_fraction: fraction
  analysis_date: analysis_date
  prep_method: prep_method
  prep_date: prep_date
  lab_name: lab_name_code
  result_basis: basis
  # reader-synthesized (__equis_*) keys
  result: __equis_result
  units: __equis_units
  qualifier: __equis_qualifier
  qc_type: __equis_qc_type
  dilution_factor: __equis_method_dilution_key
  is_reportable: __equis_is_reportable
  reporting_limit: __equis_reporting_limit
  detection_limit: __equis_detection_limit
  quantitation_limit: __equis_quantitation_limit
  prep_batch_id: __equis_prep_batch
  analysis_batch_id: __equis_analysis_batch
  # QC-only source columns (normalize_qc_rows)
  qc_original_conc: qc_original_conc
  qc_spike_added: qc_spike_added
  qc_spike_measured: qc_spike_measured
  qc_spike_recovery: qc_spike_recovery
  qc_spike_lcl: qc_spike_lcl
  qc_spike_ucl: qc_spike_ucl
  qc_rpd: qc_rpd
  qc_rpd_cl: qc_rpd_cl
  qc_dup_original_conc: qc_dup_original_conc
  qc_dup_spike_added: qc_dup_spike_added
  qc_dup_spike_measured: qc_dup_spike_measured
  qc_dup_spike_recovery: qc_dup_spike_recovery

# rt_matrix codes (GW, SW, ...) largely match canonical usage already;
# _TODO: seed after the first real filled EDD (unmapped codes warn, not
# fail — same policy as wqx.yaml).
matrix_map: {}

nondetect_qualifiers: ["U", "UJ"]

value_maps:
  qc_sample_type:
    # activity_type_code (MTDEQ_Mining-enum.xml) -> canonical QCType.
    # Field samples map to "" (analytical stream, no QC flag). Codes with
    # no canonical bucket (QC-FS, QC-DL, QC-IS, QC-MPS, QC-REFS, QC-FCC,
    # QC-FSERB, QC-HABITAT, QC-MSR/OBS, QC-OTHER) are _TODO — they import
    # with the raw code + QA-WARN (fail-safe).
    "S-ROUTINE": ""
    "S-FS": ""
    "S-CWOP": ""
    "S-IVP": ""
    "S-OTHER": ""
    "F-MSR/OBS": ""
    "F-HA": ""
    "F-DL": ""
    "QC-FD": FIELD_DUP
    "QC-FB": FIELD_BLANK
    "QC-EB": EQUIPMENT_BLANK
    "QC-TB": TRIP_BLANK
    "QC-LMS": MS
    "QC-LMSD": MSD
```

- [ ] **Step 2: Write the fixture generator**

```python
# tests/fixtures/make_mining_fixture.py
"""One-shot generator for mining_edd_fixture.xlsx (MTDEQ Mining EDD shape,
synthetic data — template headers + invented rows, no client data).
openpyxl is a project dependency. Run from the repo root:
    python tests/fixtures/make_mining_fixture.py
Regenerate only when the fixture must change; commit the .xlsx binary."""
import openpyxl

SAMPLE_HDR = ["#Sample_ID", "Sample_Type", "Medium", "Matrix",
              "Sample_Source", "Parent_Sample_ID", "Sample_Date",
              "Station_ID", "Sample_Start_Depth", "Sample_End_Depth",
              "Sample_Depth_Units"]
SAMPLES = [
    ["M-001", "S-ROUTINE", "Water", "GW", "Field", "",
     "03/11/2025 09:54", "STA-1", "", "", ""],
    ["M-002", "S-ROUTINE", "Water", "GW", "Field", "",
     "03/11/2025 10:30", "STA-2", "", "", ""],
    ["FD-1", "QC-FD", "Water", "GW", "Field", "M-001",
     "03/11/2025 09:54", "STA-1", "", "", ""],
    ["LMS-1", "QC-LMS", "Water", "WQ", "Lab", "M-001",
     "03/11/2025 09:54", "", "", "", ""],
]

RESULT_HDR = ["#Sample_ID", "Analytical_Method_ID", "Analysis_Date",
              "Sample_Fraction", "Test_Type", "Lab_Matrix", "Basis",
              "Dilution_Factor", "Prep_Method", "Prep_Date", "Lab_Name",
              "Lab_Sample_ID", "Characteristic_ID", "Characteristic_Name",
              "Result_Value", "Result_Value_Unit", "Detect_Flag",
              "Reportable_Result", "Lab_Qualifiers",
              "Interpreted_Qualifiers", "Method_Detection_Limit",
              "Lower_Reporting_Limit", "Quantitation_Limit",
              "Detection_Limit_Unit", "Lab_Batch_ID", "Batch_Type",
              "Result_Type_Code",
              "qc_original_conc", "qc_spike_added", "qc_spike_measured",
              "qc_spike_recovery", "qc_dup_original_conc",
              "qc_dup_spike_added", "qc_dup_spike_measured",
              "qc_dup_spike_recovery", "qc_rpd", "qc_spike_lcl",
              "qc_spike_ucl", "qc_rpd_cl"]


def _res(code, chem, cas, value, detect="Y", frac="T", dil="1",
         unit="mg/L", lunit="mg/L", mdl="0.1", rl="0.5", ql="1.0",
         qual="", batch=("PREP", "PB-1"), rtype="TRG", reportable="Yes",
         spike=("", "", "", ""), lcl="", ucl=""):
    return [code, "E200.8", "03/17/2025 14:02", frac, "INITIAL", "WQ",
            "NA", dil, "E200.2", "03/12/2025 08:00", "ELI",
            f"LAB-{code}", cas, chem, value, unit, detect, reportable,
            qual, "", mdl, rl, ql, lunit, batch[1], batch[0], rtype,
            "", spike[1], spike[2], spike[3], "", "", "", "", "",
            lcl, ucl, ""]


RESULTS = [
    # field sample M-001: detected lead (PREP-typed inline batch -> both ids)
    _res("M-001", "Lead", "7439-92-1", "12.4"),
    # M-002: ND arsenic with ug/L limits (conversion /1000), ANALYSIS batch
    _res("M-002", "Arsenic", "7440-38-2", "", detect="N",
         mdl="100", rl="500", ql="1000", lunit="ug/L",
         batch=("ANALYSIS", "AB-1")),
    # field duplicate rides the analytical stream QC-flagged
    _res("FD-1", "Lead", "7439-92-1", "12.1"),
    # lab matrix spike -> QC stream via the sample_type bridge
    _res("LMS-1", "Lead", "7439-92-1", "13.9",
         spike=("", "1.5", "1.45", "97"), lcl="80", ucl="120",
         batch=("ANALYSIS", "AB-1")),
]


def main() -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, hdr, rows in (("LabCollection", SAMPLE_HDR, SAMPLES),
                            ("LabResult", RESULT_HDR, RESULTS)):
        ws = wb.create_sheet(name)
        ws.append(hdr)
        for row in rows:
            ws.append(row)
    wb.save("tests/fixtures/mining_edd_fixture.xlsx")
    print("wrote tests/fixtures/mining_edd_fixture.xlsx")


if __name__ == "__main__":
    main()
```

Run it: `python tests/fixtures/make_mining_fixture.py`

- [ ] **Step 3: Write the failing e2e test**

```python
# tests/envmon/test_mining_e2e.py
"""End-to-end: mining .xlsx fixture -> read_edd_file -> split -> both
normalizers -> key distinctness. Loads the SHIPPED mining.yaml."""
import dataclasses
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_importer import (
    normalize_edd_rows, normalize_qc_rows, read_edd_file,
)
from autogis.core.envmon.edd_profile import (
    LabEDDProfile, validate_edd_profile,
)
from autogis.core.envmon.gdb_schema import compute_unique_key

FIXTURE = (Path(__file__).parent.parent / "fixtures"
           / "mining_edd_fixture.xlsx")
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "mining.yaml")


def _import():
    profile = LabEDDProfile.load(PROFILE)
    qa = QACollector()
    rows = read_edd_file(FIXTURE, profile, qa)
    qc_rows = [r for r in rows if r.get("__equis_stream") == "qc"]
    data_rows = [r for r in rows if r.get("__equis_stream") != "qc"]
    samples, results = normalize_edd_rows(
        data_rows, profile, "SITE1", "B1", {}, {}, qa)
    qc = normalize_qc_rows(qc_rows, profile, "SITE1", "B1", {}, qa)
    return samples, results, qc, qa


def test_profile_validates():
    qa = QACollector()
    validate_edd_profile(LabEDDProfile.load(PROFILE), qa)
    assert not [i for i in qa.issues if i.severity == "ERROR"]


def test_stream_split_counts():
    _, results, qc, _ = _import()
    assert len(results) == 3      # M-001 Pb, M-002 As ND, FD-1 Pb
    assert len(qc) == 1           # LMS via the sample_type bridge


def test_keys_distinct_both_tables():
    _, results, qc, _ = _import()
    rkeys = {compute_unique_key(dataclasses.asdict(r),
                                "Env_AnalyticalResults") for r in results}
    qkeys = {compute_unique_key(dataclasses.asdict(r), "Env_QCResults")
             for r in qc}
    assert len(rkeys) == 3
    assert len(qkeys) == 1


def test_field_dup_qc_flagged_analytical():
    _, results, _, _ = _import()
    fd = next(r for r in results if r.SampleID == "FD-1")
    assert fd.QCType == "FIELD_DUP"


def test_ms_spike_fields_and_inline_analysis_batch():
    _, _, qc, _ = _import()
    ms = qc[0]
    assert ms.QCType == "MS"
    assert ms.PercentRecovery == 97.0
    assert ms.AnalysisBatchID == "AB-1"
    assert ms.ParentSampleID == "M-001"


def test_prep_typed_inline_batch_fills_both_ids():
    _, results, _, _ = _import()
    pb = next(r for r in results if r.SampleID == "M-001")
    assert pb.PrepBatchID == "PB-1"
    assert pb.AnalysisBatchID == "PB-1"     # R5 key-safety fill


def test_nd_limits_converted():
    _, results, _, _ = _import()
    nd = next(r for r in results if r.SampleID == "M-002")
    assert nd.IsNonDetect == 1
    assert nd.DetectionLimit == 0.1         # 100 ug/L -> 0.1 mg/L
    assert nd.ReportingLimit == 0.5         # lower_reporting_limit routed
```

NOTE: `normalize_edd_rows` result-dataclass attribute names
(`PrepBatchID`/`AnalysisBatchID`/`QCType`/...) — copy the exact names used
in `test_equis_e2e.py`/`test_wmrd_profile.py`; if an attribute asserted here
doesn't exist on the analytical dataclass, check
`autogis/core/envmon/edd_importer.py` for the real field name and adjust.
The `qa.issues`/`i.severity` access pattern likewise mirrors existing tests.

- [ ] **Step 4: Run, fix profile until green**

Run: `python -m pytest tests/envmon/test_mining_e2e.py -q`
Expected: PASS. If a mapping is wrong the failure names the column — fix
`mining.yaml`, not the reader.

- [ ] **Step 5: Commit**

```bash
git add autogis/config/lab_profiles/mining.yaml tests/fixtures/make_mining_fixture.py tests/fixtures/mining_edd_fixture.xlsx tests/envmon/test_mining_e2e.py
git commit -m "feat(envmon): DRAFT MTDEQ Mining EDD profile + fixture + e2e (2b R7)"
```

### Task 9: epar4.yaml + fixture + e2e

**Files:**
- Create: `autogis/config/lab_profiles/epar4.yaml`
- Create: `tests/fixtures/make_epar4_fixture.py`
- Create: `tests/fixtures/epar4_edd_fixture.xlsx` (generated, committed)
- Test: `tests/envmon/test_epar4_e2e.py` (new)

**Interfaces:**
- Consumes: Tasks 1–7 (test_sheet + R9 token + inline batches).
- Produces: shipped `epar4.yaml`.

- [ ] **Step 1: Write the profile**

```yaml
# autogis/config/lab_profiles/epar4.yaml
# EPA Region 4 EQuIS EDD (.xlsx, FSample + TST + RES) — Step-3 slice 2b.
#
# *** DRAFT — verify against a real filled EPAR4 EDD before first
# production import; do not remove this banner until then (wqx.yaml
# precedent). ***
# Structure verified against epar4_blank_edd.xlsx + its rt_* vocabulary
# sheets (2026-07-12 / 2026-07-17); no real filled EDD exists yet.
# Test/Result are split sheets joined on the shared 7-column composite
# (test_sheet, R4/ADR XXXX); test_batch ids are inline on RES (R5); a
# digits-only analysis date/time token is folded into MethodDilutionKey
# (R9) so reanalyses key distinctly. VI_* sheets are slice 4.
profile_id: epar4
lab_name: EPA Region 4 EQuIS
format: equis_xls
date_format: "%m/%d/%Y"
encoding: utf-8

sample_sheet: EPAR4_FSample_v1
result_sheet: EPAR4_RES_v1
test_sheet: EPAR4_TST_v1
# No batch sheet: test_batch_type / test_batch_id are inline on RES (R5).

# R3: epar4 says total_or_dissolved where WMRD says fraction, and
# lab_prep_method_name where WMRD says prep_method.
source_aliases:
  total_or_dissolved: fraction
  lab_prep_method_name: prep_method

columns:
  # identity / joins
  sample_id: sys_sample_code
  parent_sample_id: parent_sample_code
  lab_sample_id: lab_sample_id
  location_id: sys_loc_code
  event_date: sample_date
  matrix: sample_matrix_code
  depth_top_ft: start_depth
  depth_bot_ft: end_depth
  # analyte / method
  analyte: chemical_name
  cas_number: cas_rn
  method: lab_anl_method_name
  method_name: lab_anl_method_name
  result_fraction: fraction
  analysis_date: analysis_date
  prep_method: prep_method
  prep_date: prep_date
  lab_name: lab_name_code
  result_basis: basis
  # reader-synthesized (__equis_*) keys
  result: __equis_result
  units: __equis_units
  qualifier: __equis_qualifier
  qc_type: __equis_qc_type
  dilution_factor: __equis_method_dilution_key
  is_reportable: __equis_is_reportable
  reporting_limit: __equis_reporting_limit
  detection_limit: __equis_detection_limit
  quantitation_limit: __equis_quantitation_limit
  prep_batch_id: __equis_prep_batch
  analysis_batch_id: __equis_analysis_batch
  # QC-only source columns (normalize_qc_rows)
  qc_original_conc: qc_original_conc
  qc_spike_added: qc_spike_added
  qc_spike_measured: qc_spike_measured
  qc_spike_recovery: qc_spike_recovery
  qc_spike_lcl: qc_spike_lcl
  qc_spike_ucl: qc_spike_ucl
  qc_rpd: qc_rpd
  qc_rpd_cl: qc_rpd_cl
  qc_dup_original_conc: qc_dup_original_conc
  qc_dup_spike_added: qc_dup_spike_added
  qc_dup_spike_measured: qc_dup_spike_measured
  qc_dup_spike_recovery: qc_dup_spike_recovery

# rt_matrix (epar4): minimal, unambiguous mappings only (wqx.yaml policy);
# everything else passes through + WARN. _TODO: extend after a real EDD.
matrix_map:
  SB: SOIL
  SF: SOIL
  Soil: SOIL
  SD: SED

nondetect_qualifiers: ["U", "UJ"]

value_maps:
  qc_sample_type:
    # rt_sample_type -> canonical QCType; unmapped codes fail safe (WARN).
    "N": ""
    "FD": FIELD_DUP
    "LCS": LCS
    "LCSD": LCSD
    "MS": MS
    "MSD": MSD
    "MBL": LAB_BLANK
    "EB": EQUIPMENT_BLANK
    "FL": FIELD_BLANK
    "TB": TRIP_BLANK
    "TW": TRIP_BLANK
    "TA": TRIP_BLANK
    "TS": TRIP_BLANK
```

- [ ] **Step 2: Write the fixture generator**

```python
# tests/fixtures/make_epar4_fixture.py
"""One-shot generator for epar4_edd_fixture.xlsx (EPA Region 4 EQuIS shape,
synthetic data — template headers + invented rows, no client data).
Run from the repo root:  python tests/fixtures/make_epar4_fixture.py"""
import openpyxl

SAMPLE_HDR = ["#sys_sample_code", "sample_name", "sample_matrix_code",
              "sample_type_code", "sample_source", "parent_sample_code",
              "sample_date", "sample_time", "sys_loc_code", "start_depth",
              "end_depth", "depth_unit"]
SAMPLES = [
    ["E-001", "MW-1", "GW", "N", "Field", "",
     "03/11/2025", "09:54", "MW-1", "", "", ""],
    ["LCS-1", "LCS", "WQ", "LCS", "Lab", "",
     "03/12/2025", "08:00", "", "", "", ""],
]

# shared 7-column composite leads both TST and RES
TST_HDR = ["#sys_sample_code", "lab_anl_method_name", "analysis_date",
           "analysis_time", "total_or_dissolved", "column_number",
           "test_type", "lab_matrix_code", "basis", "dilution_factor",
           "lab_prep_method_name", "prep_date", "lab_name_code",
           "lab_sample_id"]


def _tst(code, time, dil="1", ttype="initial"):
    return [code, "E200.8", "03/17/2025", time, "T", "NA", ttype,
            "WQ", "NA", dil, "E200.2", "03/12/2025", "ELI", f"LAB-{code}"]


TESTS = [
    _tst("E-001", "10:00"),
    _tst("E-001", "14:30", ttype="Reanalysis"),
    _tst("LCS-1", "10:00"),
]

RES_HDR = ["#sys_sample_code", "lab_anl_method_name", "analysis_date",
           "analysis_time", "total_or_dissolved", "column_number",
           "test_type", "cas_rn", "chemical_name", "result_value",
           "result_type_code", "reportable_result", "detect_flag",
           "lab_qualifiers", "validator_qualifiers",
           "interpreted_qualifiers", "method_detection_limit",
           "reporting_detection_limit", "quantitation_limit",
           "result_unit", "detection_limit_unit",
           "qc_original_conc", "qc_spike_added", "qc_spike_measured",
           "qc_spike_recovery", "qc_dup_original_conc",
           "qc_dup_spike_added", "qc_dup_spike_measured",
           "qc_dup_spike_recovery", "qc_rpd", "qc_spike_lcl",
           "qc_spike_ucl", "qc_rpd_cl", "test_batch_type",
           "test_batch_id"]


def _res(code, time, chem, cas, value, ttype="initial", detect="Y",
         reportable="Yes", spike=("", "", "", ""), lcl="", ucl="",
         batch=("Analysis", "AB-1")):
    return [code, "E200.8", "03/17/2025", time, "T", "NA", ttype,
            cas, chem, value, "TRG", reportable, detect, "", "", "",
            "0.1", "0.5", "1.0", "mg/L", "mg/L",
            "", spike[1], spike[2], spike[3], "", "", "", "", "",
            lcl, ucl, "", batch[0], batch[1]]


RESULTS = [
    # initial + reanalysis of the SAME analyte, differing only by time —
    # the R9 token must key them distinctly (only the initial reportable)
    _res("E-001", "10:00", "Lead", "7439-92-1", "12.4"),
    _res("E-001", "14:30", "Lead", "7439-92-1", "12.6",
         ttype="Reanalysis", reportable="No"),
    # a row with NO matching TST entry -> equis_missing_test WARN, imports
    _res("E-001", "09:00", "Arsenic", "7440-38-2", "2.0"),
    # LCS -> QC stream, Prep-typed inline batch fills both ids (R5)
    _res("LCS-1", "10:00", "Lead", "7439-92-1", "0.070",
         spike=("", "0.073", "0.070", "96"), lcl="80", ucl="120",
         batch=("Prep", "PB-1")),
]


def main() -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, hdr, rows in (("EPAR4_FSample_v1", SAMPLE_HDR, SAMPLES),
                            ("EPAR4_TST_v1", TST_HDR, TESTS),
                            ("EPAR4_RES_v1", RES_HDR, RESULTS)):
        ws = wb.create_sheet(name)
        ws.append(hdr)
        for row in rows:
            ws.append(row)
    wb.save("tests/fixtures/epar4_edd_fixture.xlsx")
    print("wrote tests/fixtures/epar4_edd_fixture.xlsx")


if __name__ == "__main__":
    main()
```

Run it: `python tests/fixtures/make_epar4_fixture.py`

- [ ] **Step 3: Write the failing e2e test**

```python
# tests/envmon/test_epar4_e2e.py
"""End-to-end: epar4 .xlsx fixture -> read_edd_file -> split -> both
normalizers -> key distinctness incl. the R9 reanalysis pair."""
import dataclasses
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_importer import (
    normalize_edd_rows, normalize_qc_rows, read_edd_file,
)
from autogis.core.envmon.edd_profile import (
    LabEDDProfile, validate_edd_profile,
)
from autogis.core.envmon.gdb_schema import compute_unique_key

FIXTURE = (Path(__file__).parent.parent / "fixtures"
           / "epar4_edd_fixture.xlsx")
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "epar4.yaml")


def _import():
    profile = LabEDDProfile.load(PROFILE)
    qa = QACollector()
    rows = read_edd_file(FIXTURE, profile, qa)
    qc_rows = [r for r in rows if r.get("__equis_stream") == "qc"]
    data_rows = [r for r in rows if r.get("__equis_stream") != "qc"]
    samples, results = normalize_edd_rows(
        data_rows, profile, "SITE1", "B1", {}, {}, qa)
    qc = normalize_qc_rows(qc_rows, profile, "SITE1", "B1", {}, qa)
    return samples, results, qc, qa


def test_profile_validates():
    qa = QACollector()
    validate_edd_profile(LabEDDProfile.load(PROFILE), qa)
    assert not [i for i in qa.issues if i.severity == "ERROR"]


def test_stream_split_counts():
    _, results, qc, _ = _import()
    assert len(results) == 3      # Pb initial + Pb reanalysis + As
    assert len(qc) == 1           # LCS


def test_reanalysis_pair_keys_distinct():
    # R9: same sample/analyte/fraction, differing only by analysis_time
    _, results, _, _ = _import()
    lead = [r for r in results if r.AnalyteName == "Lead"]
    assert len(lead) == 2
    keys = {compute_unique_key(dataclasses.asdict(r),
                               "Env_AnalyticalResults") for r in lead}
    assert len(keys) == 2
    tokens = {r.MethodDilutionKey.rsplit("|", 1)[-1] for r in lead}
    assert tokens == {"031720251000", "031720251430"}


def test_test_sheet_fields_merged():
    # dilution/basis/prep live on TST; the join brought them across
    _, results, _, _ = _import()
    pb = next(r for r in results if r.AnalyteName == "Lead"
              and r.IsReportable == 1)
    assert pb.PrepMethod == "E200.2"        # via lab_prep_method_name alias


def test_missing_test_entry_warns_but_imports():
    _, results, _, qa = _import()
    assert any(r.AnalyteName == "Arsenic" for r in results)
    assert [i for i in qa.issues if i.code == "equis_missing_test"]


def test_lcs_qc_with_prep_typed_inline_batch():
    _, _, qc, _ = _import()
    lcs = qc[0]
    assert lcs.QCType == "LCS"
    assert lcs.PercentRecovery == 96.0
    assert lcs.AnalysisBatchID == "PB-1"    # R5 key-safety fill
    assert lcs.PrepBatchID == "PB-1"
```

NOTE: same attribute-name caveat as Task 8 (`PrepMethod`, `PrepBatchID`,
etc. — mirror the names existing e2e/QC tests use; adjust if they differ).

- [ ] **Step 4: Run, fix profile until green**

Run: `python -m pytest tests/envmon/test_epar4_e2e.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/config/lab_profiles/epar4.yaml tests/fixtures/make_epar4_fixture.py tests/fixtures/epar4_edd_fixture.xlsx tests/envmon/test_epar4_e2e.py
git commit -m "feat(envmon): DRAFT EPA Region 4 EDD profile + fixture + e2e (2b R7)"
```

### Task 10: nysdec.yaml + fixture + e2e

**Files:**
- Create: `autogis/config/lab_profiles/nysdec.yaml`
- Create: `tests/fixtures/make_nysdec_fixture.py`
- Create: `tests/fixtures/nysdec_edd_fixture.xlsx` (generated, committed)
- Test: `tests/envmon/test_nysdec_e2e.py` (new)

**Interfaces:**
- Consumes: Tasks 1–5 (batch sheet with analysis_date — R6; uppercase batch
  types — R5 sheet path; no aliases, no test sheet).
- Produces: shipped `nysdec.yaml`.

- [ ] **Step 1: Write the profile**

```yaml
# autogis/config/lab_profiles/nysdec.yaml
# NYSDEC EQuIS v5 EDD (.xlsx, Sample_v5 + TestResultQC_v5 + Batch_v5) —
# Step-3 slice 2b.
#
# *** DRAFT — verify against a real filled NYSDEC EDD before first
# production import; do not remove this banner until then (wqx.yaml
# precedent). ***
# Structure verified against the v5 blank template + description + valid-
# values workbooks (2026-07-12 / 2026-07-17); no real filled EDD exists
# yet. Same lowercase EQuIS column vocabulary as WMRD; Batch_v5 adds
# analysis_date to the batch join composite (R6) and records uppercase
# PREP/ANALYSIS batch types (matched case-insensitively, R5). Non-
# analytical sheets (WaterLevel_v5, SoilGas_v5, FieldResults_v5, VI_*) are
# out of scope for this slice.
profile_id: nysdec
lab_name: NYSDEC EQuIS v5
format: equis_xls
date_format: "%m/%d/%Y"
encoding: utf-8

sample_sheet: Sample_v5
result_sheet: TestResultQC_v5
batch_sheet: Batch_v5

columns:
  # identity / joins
  sample_id: sys_sample_code
  parent_sample_id: parent_sample_code
  lab_sample_id: lab_sample_id
  location_id: sys_loc_code
  event_date: sample_date
  matrix: sample_matrix_code
  depth_top_ft: start_depth
  depth_bot_ft: end_depth
  # analyte / method
  analyte: chemical_name
  cas_number: cas_rn
  method: lab_anl_method_name
  method_name: lab_anl_method_name
  result_fraction: fraction
  analysis_date: analysis_date
  prep_method: prep_method
  prep_date: prep_date
  lab_name: lab_name_code
  result_basis: basis
  # reader-synthesized (__equis_*) keys
  result: __equis_result
  units: __equis_units
  qualifier: __equis_qualifier
  qc_type: __equis_qc_type
  dilution_factor: __equis_method_dilution_key
  is_reportable: __equis_is_reportable
  reporting_limit: __equis_reporting_limit
  detection_limit: __equis_detection_limit
  quantitation_limit: __equis_quantitation_limit
  prep_batch_id: __equis_prep_batch
  analysis_batch_id: __equis_analysis_batch
  # QC-only source columns (normalize_qc_rows)
  qc_original_conc: qc_original_conc
  qc_spike_added: qc_spike_added
  qc_spike_measured: qc_spike_measured
  qc_spike_recovery: qc_spike_recovery
  qc_spike_lcl: qc_spike_lcl
  qc_spike_ucl: qc_spike_ucl
  qc_rpd: qc_rpd
  qc_rpd_cl: qc_rpd_cl
  qc_dup_original_conc: qc_dup_original_conc
  qc_dup_spike_added: qc_dup_spike_added
  qc_dup_spike_measured: qc_dup_spike_measured
  qc_dup_spike_recovery: qc_dup_spike_recovery

# rt_matrix (NYSDEC): minimal, unambiguous mappings only (wqx.yaml
# policy); everything else passes through + WARN. _TODO: extend after a
# real EDD.
matrix_map:
  WG: GW
  SO: SOIL
  SS: SOIL
  SIMP: SOIL
  SE: SED
  SED: SED

nondetect_qualifiers: ["U", "UJ"]

value_maps:
  qc_sample_type:
    # rt_sample_type (valid-values workbook) -> canonical QCType; unmapped
    # codes (BS, BD, IB, PE, KD, RM, SD, SB, ...) are _TODO — they import
    # with the raw code + QA-WARN (fail-safe).
    "N": ""
    "FD": FIELD_DUP
    "FB": FIELD_BLANK
    "EB": EQUIPMENT_BLANK
    "TB": TRIP_BLANK
    "LB": LAB_BLANK
    "LCS": LCS
    "LCSD": LCSD
    "LD": LAB_DUP
    "DUP": LAB_DUP
    "MS": MS
    "MSD": MSD
```

- [ ] **Step 2: Write the fixture generator**

```python
# tests/fixtures/make_nysdec_fixture.py
"""One-shot generator for nysdec_edd_fixture.xlsx (NYSDEC EQuIS v5 shape,
synthetic data — template headers + invented rows, no client data).
Run from the repo root:  python tests/fixtures/make_nysdec_fixture.py"""
import openpyxl

SAMPLE_HDR = ["#data_provider", "sys_sample_code", "sample_name",
              "sample_matrix_code", "sample_type_code", "sample_source",
              "parent_sample_code", "sample_delivery_group", "sample_date",
              "sys_loc_code", "start_depth", "end_depth", "depth_unit"]
SAMPLES = [
    ["ACME", "N-001", "MW-1", "WG", "N", "Field", "", "SDG1",
     "03/11/2025 09:54", "MW-1", "", "", ""],
    ["ACME", "N-002", "MW-2", "WG", "N", "Field", "", "SDG1",
     "03/11/2025 10:30", "MW-2", "", "", ""],
    ["ACME", "LB-1", "Lab Blank", "WQ", "LB", "Lab", "", "SDG1",
     "03/12/2025 08:00", "", "", "", ""],
]

RESULT_HDR = ["#sys_sample_code", "lab_anl_method_name", "analysis_date",
              "fraction", "column_number", "test_type", "lab_matrix_code",
              "basis", "dilution_factor", "prep_method", "prep_date",
              "lab_name_code", "lab_sample_id", "cas_rn", "chemical_name",
              "result_value", "result_unit", "result_type_code",
              "reportable_result", "detect_flag", "lab_qualifiers",
              "validator_qualifiers", "interpreted_qualifiers",
              "method_detection_limit", "reporting_detection_limit",
              "quantitation_limit", "detection_limit_unit",
              "qc_original_conc", "qc_spike_added", "qc_spike_measured",
              "qc_spike_recovery", "qc_dup_original_conc",
              "qc_dup_spike_added", "qc_dup_spike_measured",
              "qc_dup_spike_recovery", "qc_rpd", "qc_spike_lcl",
              "qc_spike_ucl", "qc_rpd_cl"]


def _res(code, chem, cas, value, adate="03/17/2025", detect="Y",
         frac="T", qual=""):
    return [code, "E200.8", adate, frac, "NA", "INITIAL", "WQ", "NA",
            "1", "E200.2", "03/12/2025", "ELI", f"LAB-{code}", cas, chem,
            value, "mg/L", "TRG", "Yes", detect, qual, "", "",
            "0.1", "0.5", "1.0", "mg/L",
            "", "", "", "", "", "", "", "", "", "", "", ""]


RESULTS = [
    # two field samples analyzed on DIFFERENT dates -> R6 join picks the
    # date-matching batch row
    _res("N-001", "Lead", "7439-92-1", "12.4", adate="03/17/2025"),
    _res("N-002", "Lead", "7439-92-1", "8.1", adate="03/18/2025"),
    # lab blank -> QC stream; ND
    _res("LB-1", "Lead", "7439-92-1", "", adate="03/17/2025", detect="N"),
]

BATCH_HDR = ["#sys_sample_code", "lab_anl_method_name", "analysis_date",
             "fraction", "column_number", "test_type", "test_batch_type",
             "test_batch_id"]
BATCHES = [
    # uppercase types (rt_test_batch_type) — case-insensitive match (R5)
    ["N-001", "E200.8", "03/17/2025", "T", "NA", "INITIAL",
     "PREP", "PB-1"],
    ["N-001", "E200.8", "03/17/2025", "T", "NA", "INITIAL",
     "ANALYSIS", "AB-1"],
    ["N-002", "E200.8", "03/18/2025", "T", "NA", "INITIAL",
     "ANALYSIS", "AB-2"],
    ["LB-1", "E200.8", "03/17/2025", "T", "NA", "INITIAL",
     "ANALYSIS", "AB-1"],
]


def main() -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, hdr, rows in (("Sample_v5", SAMPLE_HDR, SAMPLES),
                            ("TestResultQC_v5", RESULT_HDR, RESULTS),
                            ("Batch_v5", BATCH_HDR, BATCHES)):
        ws = wb.create_sheet(name)
        ws.append(hdr)
        for row in rows:
            ws.append(row)
    wb.save("tests/fixtures/nysdec_edd_fixture.xlsx")
    print("wrote tests/fixtures/nysdec_edd_fixture.xlsx")


if __name__ == "__main__":
    main()
```

Run it: `python tests/fixtures/make_nysdec_fixture.py`

- [ ] **Step 3: Write the failing e2e test**

```python
# tests/envmon/test_nysdec_e2e.py
"""End-to-end: NYSDEC v5 .xlsx fixture -> read_edd_file -> split -> both
normalizers -> R6 date-extended batch join + case-insensitive types."""
import dataclasses
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_importer import (
    normalize_edd_rows, normalize_qc_rows, read_edd_file,
)
from autogis.core.envmon.edd_profile import (
    LabEDDProfile, validate_edd_profile,
)
from autogis.core.envmon.gdb_schema import compute_unique_key

FIXTURE = (Path(__file__).parent.parent / "fixtures"
           / "nysdec_edd_fixture.xlsx")
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "nysdec.yaml")


def _import():
    profile = LabEDDProfile.load(PROFILE)
    qa = QACollector()
    rows = read_edd_file(FIXTURE, profile, qa)
    qc_rows = [r for r in rows if r.get("__equis_stream") == "qc"]
    data_rows = [r for r in rows if r.get("__equis_stream") != "qc"]
    samples, results = normalize_edd_rows(
        data_rows, profile, "SITE1", "B1", {}, {}, qa)
    qc = normalize_qc_rows(qc_rows, profile, "SITE1", "B1", {}, qa)
    return samples, results, qc, qa


def test_profile_validates():
    qa = QACollector()
    validate_edd_profile(LabEDDProfile.load(PROFILE), qa)
    assert not [i for i in qa.issues if i.severity == "ERROR"]


def test_stream_split_and_keys():
    _, results, qc, _ = _import()
    assert len(results) == 2
    assert len(qc) == 1
    rkeys = {compute_unique_key(dataclasses.asdict(r),
                                "Env_AnalyticalResults") for r in results}
    assert len(rkeys) == 2


def test_r6_date_extended_join_and_uppercase_types():
    _, results, _, qa = _import()
    n1 = next(r for r in results if r.SampleID == "N-001")
    n2 = next(r for r in results if r.SampleID == "N-002")
    assert n1.PrepBatchID == "PB-1"          # uppercase PREP matched
    assert n1.AnalysisBatchID == "AB-1"
    assert n2.AnalysisBatchID == "AB-2"      # date-discriminated (R6)
    assert not [i for i in qa.issues if i.code == "equis_missing_batch"]


def test_lab_blank_routed_qc_with_matrix_passthrough():
    _, _, qc, _ = _import()
    lb = qc[0]
    assert lb.QCType == "LAB_BLANK"
    assert lb.IsNonDetect == 1
    assert lb.AnalysisBatchID == "AB-1"


def test_matrix_mapped():
    samples, _, _, _ = _import()
    assert all(s.Matrix == "GW" for s in samples
               if s.SampleID.startswith("N-"))
```

NOTE: same attribute-name caveat as Tasks 8/9.

- [ ] **Step 4: Run, fix profile until green**

Run: `python -m pytest tests/envmon/test_nysdec_e2e.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/config/lab_profiles/nysdec.yaml tests/fixtures/make_nysdec_fixture.py tests/fixtures/nysdec_edd_fixture.xlsx tests/envmon/test_nysdec_e2e.py
git commit -m "feat(envmon): DRAFT NYSDEC v5 EDD profile + fixture + e2e (2b R7)"
```

### Task 11: full-suite verification + invariant check

**Files:** none new (fixes only if the suite finds a regression)

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: 0 failures; total = baseline 2188 + the new tests (record the
final number for the PR body). Investigate ANY failure — the slice-1
files (`test_equis_reader.py`, `test_equis_e2e.py`, `test_wmrd_profile.py`,
`test_qc_normalizer.py`, `test_key_collision_guard.py`) are the pinned
no-op contracts for R2/R5/R6/R9.

- [ ] **Step 2: arcpy-free import check**

Run: `python -c "import autogis.core.envmon.equis_reader, autogis.core.envmon.edd_profile; print('ok')"`
Expected: `ok` (no arcpy/arcgis in the import chain).

- [ ] **Step 3: R8 zero-CLI-change check**

Run: `git diff main --stat -- autogis/adapters/`
Expected: empty (no adapter/CLI edits anywhere in the branch).

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test(envmon): slice-2b full-suite fixes"   # only if needed
```

---

## Self-Review (done at plan time)

- **Spec coverage:** R1→T1, R2→T1, R3→T2, R4→T5+T6 (gate order enforced),
  R5→T3, R6→T4, R7→T8/9/10, R8→T11 step 3 (verification only — zero
  change), R9→T7. 2b testing-plan bullets all land in T1–T10.
- **Known judgment calls** (flag to reviewer): (a) the R9 token applies to
  BOTH streams — `MethodDilutionKey` is a frozen key part of both tables
  and per-row determinism holds either way; (b) R2 applies to the `.xls`
  engine too (the spec's "no-op for the real WMRD export" phrasing assumes
  exactly this); (c) vocabulary seeds were extracted fresh from the cleared
  examples folder 2026-07-17 because the spec records structure, not vocab
  values; minimal-unambiguous mapping policy copied from wqx.yaml.
- **Type consistency:** `transform_equis_sheets(..., test_rows=None)` is
  introduced in T6 and consumed in T7/T9; `_attach_batches(..., join_date)`
  introduced in T4; `LabEDDProfile.source_aliases`/`test_sheet` introduced
  T2/T6 and consumed by every profile task.
