# EDD Step 3 Slice 1 — EQuIS reader + WMRD profile + QC schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import real EQuIS WMRD lab EDDs (.xls, 3 relational sheets) into the envmon GDB — field results into `Env_AnalyticalResults` (now with CASNumber/QuantitationLimit/IsReportable) and lab-QC results into a new `Env_QCResults` table — with zero CLI change.

**Architecture:** One parameterized family reader (`equis_reader.py`, format `equis_xls`) joins the sample/result/batch sheets and emits flat row dicts with synthesized `__equis_*` columns (the ADR-0080 pattern); lab-QC rows are tagged `__equis_stream="qc"` and forked in `run_edd_import` to a new `normalize_qc_rows` → the existing table-generic `append_records_idempotent` writer. Spec: `docs/superpowers/specs/2026-07-10-edd-step3-equis-wmrd-design.md` (decisions D1–D12 cited per task).

**Tech Stack:** Python stdlib + xlrd 2.x (NEW required dep, lazy-imported in the reader only). No arcpy in anything this plan writes — GDB writes ride existing `pragma: no cover` seams.

## Global Constraints

- `main` is READ-ONLY — all work on branch `spec/edd-step3-equis-wmrd` (already checked out) or a successor feature branch; this applies to subagents too, state it in their prompts.
- ponytail (full) active: laziest solution that works, reuse before writing, no new abstractions beyond this plan.
- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` installed (repo invariant). xlrd imports live inside function bodies in `equis_reader.py` only.
- Tests are arcpy-free, run with `python -m pytest -q` from the worktree root. Baseline: **2030 passed, 3 skipped** — every task ends green with its new tests added.
- The PostToolUse hook may print "pytest reported failures" even on green runs — trust only the `N passed` summary line.
- SCHEMA_VERSION goes `"2.2"` → `"2.3"` exactly once (Task 1).
- Real-file verification data: `C:\Users\ichbi\OneDrive\Desktop\Analytical Report Format Examples\B25030623-MT-WMRD (EQUIS).XLS` (client data — NEVER copy into the repo).
- Column-name constants target the EQuIS v1 family (wmrd/epar4/nysdec). Mining's renamed cousins are slice 2's problem — do not add configurability for them now (YAGNI).

---

### Task 1: Schema — Env_QCResults table, 3 new AnalyticalResults columns, QCResultRecord, SCHEMA_VERSION 2.3

**Files:**
- Modify: `autogis/core/envmon/gdb_schema.py` (TABLE_FIELDS ~line 72, UNIQUE_KEYS ~line 342, AnalyticalResultRecord ~line 439, new dataclass after RPDRecord ~line 452)
- Modify: `autogis/core/envmon/upgrade_schema.py:13`
- Test: `tests/envmon/test_qc_schema.py` (new)

**Interfaces:**
- Produces: `QCResultRecord` dataclass (field names == Env_QCResults schema names, importable as `from autogis.core.envmon.gdb_schema import QCResultRecord`); `UNIQUE_KEYS["Env_QCResults"]`; `AnalyticalResultRecord` gains `CASNumber: str = ""`, `QuantitationLimit: Optional[float] = None`, `IsReportable: Optional[int] = None`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

```python
# tests/envmon/test_qc_schema.py
"""Env_QCResults schema + Step-3 AnalyticalResults additions (slice-1 spec)."""
import dataclasses

from autogis.core.envmon.gdb_schema import (
    TABLE_FIELDS, UNIQUE_KEYS, AnalyticalResultRecord, QCResultRecord,
    compute_unique_key,
)
from autogis.core.envmon.upgrade_schema import SCHEMA_VERSION


def test_schema_version_bumped():
    assert SCHEMA_VERSION == "2.3"


def test_env_qcresults_table_declared():
    names = [f[0] for f in TABLE_FIELDS["Env_QCResults"]]
    # paper-mapping finalized 33-column list, spot-checked head/tail + QC pillars
    assert names[0] == "ImportBatchID"
    assert names[-1] == "SourceRow"
    for col in ("QCType", "SampleID", "ParentSampleID", "AnalyteCanonicalName",
                "CASNumber", "MethodDilutionKey", "SpikeAmount",
                "PercentRecovery", "RPD", "RPDControlLimit"):
        assert col in names
    assert len(names) == 33


def test_env_qcresults_unique_key():
    assert UNIQUE_KEYS["Env_QCResults"] == [
        "SiteID", "Matrix", "AnalysisBatchID", "SampleID", "QCType",
        "AnalyteCanonicalName", "ResultFraction", "MethodID",
        "MethodDilutionKey"]


def test_qcresultrecord_matches_table_fields():
    record_fields = {f.name for f in dataclasses.fields(QCResultRecord)}
    schema_fields = {f[0] for f in TABLE_FIELDS["Env_QCResults"]}
    assert record_fields == schema_fields


def test_analytical_record_step3_fields_default_safe():
    fields = {f.name: f for f in dataclasses.fields(AnalyticalResultRecord)}
    assert fields["CASNumber"].default == ""
    assert fields["QuantitationLimit"].default is None
    assert fields["IsReportable"].default is None
    cols = {f[0] for f in TABLE_FIELDS["Env_AnalyticalResults"]}
    assert {"CASNumber", "QuantitationLimit", "IsReportable"} <= cols


def test_compute_unique_key_env_qcresults():
    rec = {"SiteID": "s1", "Matrix": "SOIL", "AnalysisBatchID": "438621",
           "SampleID": "B25-002AMT", "QCType": "MS",
           "AnalyteCanonicalName": "Lead", "ResultFraction": "Total",
           "MethodID": "E200.8", "MethodDilutionKey": "1"}
    key = compute_unique_key(rec, "Env_QCResults")
    assert key == ("S1", "SOIL", "438621", "B25-002AMT", "MS", "LEAD",
                   "TOTAL", "E200.8", "1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_qc_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'QCResultRecord'`

- [ ] **Step 3: Implement the schema additions**

In `autogis/core/envmon/gdb_schema.py`, `TABLE_FIELDS["Env_AnalyticalResults"]` — append after `("ResultBasis", T, 16), ("MethodSpeciation", T, 32)` (keep `+ _SRC` at the end):

```python
        ("ResultBasis", T, 16), ("MethodSpeciation", T, 32),
        # --- Step-3 EQuIS additions (slice-1 spec 2026-07-10) ---
        ("CASNumber", T, 32), ("QuantitationLimit", D, None),
        ("IsReportable", SH, None)] + _SRC,
```

Add a new TABLE_FIELDS entry directly after the `"Env_AnalyticalResults"` entry:

```python
    # Lab-QC results (blanks, LCS/LCSD, MS/MSD, surrogates, CCV/ICV...) —
    # Step-3 slice 1; field list finalized by the 2026-07-09 paper mapping.
    "Env_QCResults": [
        ("ImportBatchID", T, 64), ("SiteID", T, 32), ("Matrix", T, 16),
        ("PrepBatchID", T, 64), ("AnalysisBatchID", T, 64),
        ("QCType", T, 32), ("SampleID", T, 64), ("ParentSampleID", T, 64),
        ("LabSampleID", T, 64), ("AnalyteName", T, 128),
        ("AnalyteCanonicalName", T, 128), ("CASNumber", T, 32),
        ("MethodID", T, 64), ("ResultFraction", T, 32),
        ("MethodDilutionKey", T, 64), ("AnalysisDate", DT, None),
        ("ResultRawText", T, 64), ("ResultNumeric", D, None),
        ("Units", T, 16), ("ReportingLimit", D, None),
        ("DetectionLimit", D, None), ("Qualifier", T, 16),
        ("IsNonDetect", SH, None), ("SpikeAmount", D, None),
        ("OriginalConcentration", D, None), ("PercentRecovery", D, None),
        ("RecoveryLowerLimit", D, None), ("RecoveryUpperLimit", D, None),
        ("RPD", D, None), ("RPDControlLimit", D, None)] + _SRC[:3],
```

(`_SRC[:3]` supplies SourceWorkbook/SourceSheet/SourceRow — same idiom as Env_Samples; verify `_SRC[:3]` is exactly those three at line 18 before using.)

Add to `UNIQUE_KEYS` (after the Env_AnalyticalResults entry):

```python
    "Env_QCResults": ["SiteID", "Matrix", "AnalysisBatchID", "SampleID",
                      "QCType", "AnalyteCanonicalName", "ResultFraction",
                      "MethodID", "MethodDilutionKey"],
```

Append to `AnalyticalResultRecord` after `MethodSpeciation: str = ""`:

```python
    # --- Step-3 EQuIS additions (slice-1 spec 2026-07-10) ---
    CASNumber: str = ""
    QuantitationLimit: Optional[float] = None
    IsReportable: Optional[int] = None
```

Add after the `RPDRecord` dataclass:

```python
@dataclass
class QCResultRecord:
    """Lab-QC result row (Env_QCResults). Field names == schema names.

    Key discriminators default "" (never None — idempotency, ADR-0075);
    numeric/date data fields default None."""
    ImportBatchID: str; SiteID: str; Matrix: str
    SampleID: str; QCType: str
    AnalyteName: str; AnalyteCanonicalName: str
    SourceWorkbook: str; SourceSheet: str; SourceRow: int
    PrepBatchID: str = ""
    AnalysisBatchID: str = ""
    ParentSampleID: str = ""
    LabSampleID: str = ""
    CASNumber: str = ""
    MethodID: str = ""
    ResultFraction: str = ""
    MethodDilutionKey: str = ""
    AnalysisDate: Optional[date] = None
    ResultRawText: str = ""
    ResultNumeric: Optional[float] = None
    Units: str = ""
    ReportingLimit: Optional[float] = None
    DetectionLimit: Optional[float] = None
    Qualifier: str = ""
    IsNonDetect: int = 0
    SpikeAmount: Optional[float] = None
    OriginalConcentration: Optional[float] = None
    PercentRecovery: Optional[float] = None
    RecoveryLowerLimit: Optional[float] = None
    RecoveryUpperLimit: Optional[float] = None
    RPD: Optional[float] = None
    RPDControlLimit: Optional[float] = None
```

In `autogis/core/envmon/upgrade_schema.py:13`: `SCHEMA_VERSION = "2.3"`.

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `python -m pytest tests/envmon/test_qc_schema.py -q` → all PASS.
Run: `python -m pytest -q` → expect **2030 + 6 new passed** (a pre-existing test may pin SCHEMA_VERSION or table lists — if one fails on the bump, update its expectation in the same commit; that is the test doing its job).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/gdb_schema.py autogis/core/envmon/upgrade_schema.py tests/envmon/test_qc_schema.py
git commit -m "feat(envmon): Env_QCResults table + Step-3 AnalyticalResults columns (schema 2.3)"
```

---

### Task 2: Profile — register `equis_xls` format + `batch_sheet` field

**Files:**
- Modify: `autogis/core/envmon/edd_profile.py:15` (`_VALID_FORMATS`), `:22` (format comment), `:28-29` region (new field), `:57-58` region (load kwargs)
- Test: `tests/envmon/test_edd_profile.py` (existing — append tests; if the file does not exist, create it with just these tests)

**Interfaces:**
- Produces: `LabEDDProfile.batch_sheet: str = ""`; `"equis_xls"` accepted by `validate_edd_profile`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests** (append to the existing test module)

```python
def test_equis_xls_is_valid_format():
    from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile
    from autogis.core.common.qa import QACollector
    profile = LabEDDProfile(
        profile_id="p", lab_name="l", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={c: "x" for c in ("sample_id", "location_id", "event_date",
                                  "matrix", "analyte", "result", "units",
                                  "qualifier", "reporting_limit")},
        matrix_map={}, nondetect_qualifiers=[],
    )
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert not qa.has_blocking()


def test_batch_sheet_defaults_empty_and_loads(tmp_path):
    from autogis.core.envmon.edd_profile import LabEDDProfile
    p = tmp_path / "prof.yaml"
    p.write_text(
        "profile_id: p\nformat: equis_xls\n"
        "sample_sheet: Sample_v1\nresult_sheet: TestResultQC_v1\n"
        "batch_sheet: Batch_v1\ncolumns: {}\n",
        encoding="utf-8")
    prof = LabEDDProfile.load(p)
    assert prof.batch_sheet == "Batch_v1"
    assert LabEDDProfile(
        profile_id="p", lab_name="l", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8", columns={},
        matrix_map={}, nondetect_qualifiers=[],
    ).batch_sheet == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_edd_profile.py -q`
Expected: FAIL — `edis_profile_bad_format` blocking QA for the first, `TypeError`/`AttributeError` (no `batch_sheet`) for the second.

- [ ] **Step 3: Implement**

```python
_VALID_FORMATS = {"flat_csv", "two_tab_xlsx", "wqx_csv", "equis_xls"}
```

Field comment on line 22 becomes `# "flat_csv" | "two_tab_xlsx" | "wqx_csv" | "equis_xls"`. After `result_sheet: str = "Results"` add:

```python
    batch_sheet: str = ""                    # equis_xls only; "" = no batch sheet
```

In `load()`, after the `result_sheet=` kwarg add:

```python
            batch_sheet=data.get("batch_sheet", ""),
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/envmon/test_edd_profile.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_profile.py tests/envmon/test_edd_profile.py
git commit -m "feat(envmon): register equis_xls EDD format + batch_sheet profile field"
```

---

### Task 3: `equis_reader.py` — pure transform over sheet dicts

**Files:**
- Create: `autogis/core/envmon/equis_reader.py`
- Test: `tests/envmon/test_equis_reader.py` (new)

**Interfaces:**
- Produces: `transform_equis_sheets(sample_rows: list[dict], result_rows: list[dict], batch_rows: list[dict], profile, qa: QACollector) -> list[dict]` — flat merged rows, QC rows tagged `row["__equis_stream"] = "qc"`, synthesized `__equis_*` keys per spec. Rows may carry `"__sheet_row"` (int) stamped by the loader (Task 4); when absent, enumeration from 2 is used.
- Consumes: `QACollector`, `SEV_WARNING` from `..common.qa`; `UnitError, convert` from `..common.units`; profile `map_value` / `value_maps` / `resolve_column` (Task 2 shapes).

- [ ] **Step 1: Write the failing tests**

```python
# tests/envmon/test_equis_reader.py
"""EQuIS v1 family transform tests (Step-3 slice 1). Pure dict rows — the
.xls loader is exercised by the end-to-end fixture test (test_equis_e2e.py)."""
import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.equis_reader import transform_equis_sheets


def _profile(**over):
    kw = dict(
        profile_id="wmrd_test", lab_name="Test Lab", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": ["#sys_sample_code", "sys_sample_code"]},
        matrix_map={"SOLID": "SOIL"},
        nondetect_qualifiers=["U"],
        sample_sheet="Sample_v1", result_sheet="TestResultQC_v1",
        batch_sheet="Batch_v1",
        value_maps={"qc_sample_type": {
            "N": "", "QC-LCS": "LCS", "QC-LCSD": "LCSD", "QC-LMS": "MS",
            "QC-LMSD": "MSD", "QC-LB": "LAB_BLANK", "QC-LD": "LAB_DUP",
            "QC-LCCV": "CCV", "QC-LICV": "ICV", "QC-PDS": "PDS",
            "QC-LIFC": "IFC", "SRM": "SRM"}},
    )
    kw.update(over)
    return LabEDDProfile(**kw)


def _sample(**over):
    row = {"sys_sample_code": "S-001", "sample_name": "MW-1",
           "sample_matrix_code": "SOLID", "sample_type_code": "N",
           "sample_source": "Field", "parent_sample_code": "",
           "sample_date": "03/11/2025 09:54", "sys_loc_code": "MW-1",
           "start_depth": "", "end_depth": "", "depth_unit": "ft"}
    row.update(over)
    return row


def _result(**over):
    row = {"#sys_sample_code": "S-001", "lab_anl_method_name": "E200.8",
           "analysis_date": "03/17/2025 14:02", "fraction": "Total",
           "column_number": "NA", "test_type": "INITIAL",
           "lab_matrix_code": "SOLID", "basis": "Dry",
           "dilution_factor": "1", "prep_method": "E200.2",
           "prep_date": "03/12/2025 08:00", "lab_name_code": "ELI-B",
           "lab_sample_id": "B25030623-001", "cas_rn": "7439-92-1",
           "chemical_name": "Lead", "result_value": "12.4",
           "result_type_code": "TRG", "reportable_result": "Yes",
           "detect_flag": "Y", "lab_qualifiers": "",
           "validator_qualifiers": "", "interpreted_qualifiers": "",
           "method_detection_limit": "0.1", "reporting_detection_limit": "0.5",
           "quantitation_limit": "1.0", "result_unit": "mg/kg",
           "detection_limit_unit": "mg/kg",
           "qc_original_conc": "", "qc_spike_added": "",
           "qc_spike_measured": "", "qc_spike_recovery": "",
           "qc_dup_original_conc": "", "qc_dup_spike_added": "",
           "qc_dup_spike_measured": "", "qc_dup_spike_recovery": "",
           "qc_rpd": "", "qc_spike_lcl": "", "qc_spike_ucl": "",
           "qc_rpd_cl": ""}
    row.update(over)
    return row


def _batch(**over):
    row = {"#sys_sample_code": "S-001", "lab_anl_method_name": "E200.8",
           "fraction": "Total", "column_number": "NA",
           "test_type": "INITIAL", "test_batch_type": "Prep",
           "test_batch_id": "PB-1", "Expr1002": "junk"}
    row.update(over)
    return row


def _run(samples, results, batches, profile=None):
    qa = QACollector()
    out = transform_equis_sheets(samples, results, batches,
                                 profile or _profile(), qa)
    return out, qa


def test_field_sample_row_untagged_and_merged():
    rows, qa = _run([_sample()], [_result()], [_batch()])
    assert len(rows) == 1
    r = rows[0]
    assert r.get("__equis_stream") != "qc"
    assert r["sample_date"] == "03/11/2025 09:54"     # sample-side merged
    assert r["result_value"] == "12.4"                # result side wins
    assert r["__equis_prep_batch"] == "PB-1"
    assert r["__equis_analysis_batch"] == ""


def test_lab_source_sample_tagged_qc():
    rows, _ = _run(
        [_sample(sys_sample_code="LCS-1", sample_source="LAB",
                 sample_type_code="QC-LCS", sample_matrix_code="SQ-CONTROL")],
        [_result(**{"#sys_sample_code": "LCS-1"})], [])
    assert rows[0]["__equis_stream"] == "qc"
    assert rows[0]["__equis_qc_type"] == "LCS"


def test_surrogate_on_field_sample_routed_qc():
    rows, _ = _run([_sample()], [_result(result_type_code="SUR")], [])
    assert rows[0]["__equis_stream"] == "qc"
    assert rows[0]["__equis_qc_type"] == "SURROGATE"


def test_unmapped_lab_qc_type_warns_and_keeps_raw():
    rows, qa = _run(
        [_sample(sample_source="LAB", sample_type_code="QC-WEIRD")],
        [_result()], [])
    assert rows[0]["__equis_qc_type"] == "QC-WEIRD"
    assert any(r.category == "equis_unmapped_qc_type" for r in qa.records)


def test_nd_synthesis_from_detect_flag():
    rows, _ = _run([_sample()],
                   [_result(detect_flag="N", result_value="")], [])
    assert rows[0]["__equis_result"] == "ND"


def test_detect_flag_conflict_warns_nd_wins():
    rows, qa = _run([_sample()],
                    [_result(detect_flag="N", result_value="0.3")], [])
    assert rows[0]["__equis_result"] == "ND"
    assert any(r.category == "equis_detect_flag_conflict" for r in qa.records)


def test_qualifier_precedence_interpreted_first():
    rows, _ = _run([_sample()], [_result(lab_qualifiers="U",
                                         validator_qualifiers="J",
                                         interpreted_qualifiers="UJ")], [])
    assert rows[0]["__equis_qualifier"] == "UJ"
    rows, _ = _run([_sample()], [_result(lab_qualifiers="U",
                                         validator_qualifiers="J")], [])
    assert rows[0]["__equis_qualifier"] == "J"
    rows, _ = _run([_sample()], [_result(lab_qualifiers="U")], [])
    assert rows[0]["__equis_qualifier"] == "U"


def test_dilution_key_fold_na_normalized():
    rows, _ = _run([_sample()], [_result(dilution_factor="5",
                                         test_type="DILUTION",
                                         column_number="NA", basis="Dry")], [])
    assert rows[0]["__equis_method_dilution_key"] == "5|DILUTION|Dry"


def test_limit_conversion_and_short_circuit():
    # same units: values pass through untouched, no warning
    rows, qa = _run([_sample()], [_result()], [])
    assert rows[0]["__equis_reporting_limit"] == "0.5"
    assert rows[0]["__equis_detection_limit"] == "0.1"
    assert rows[0]["__equis_quantitation_limit"] == "1.0"
    assert not qa.records
    # unit mismatch: converted (ug/kg -> mg/kg)
    rows, _ = _run([_sample()],
                   [_result(method_detection_limit="100",
                            detection_limit_unit="ug/kg")], [])
    assert float(rows[0]["__equis_detection_limit"]) == pytest.approx(0.1)


def test_unconvertible_limit_unit_warns_keeps_raw():
    rows, qa = _run([_sample()],
                    [_result(method_detection_limit="0.1",
                             detection_limit_unit="furlongs")], [])
    assert rows[0]["__equis_detection_limit"] == "0.1"
    assert any(r.category == "equis_limit_unit_mismatch" for r in qa.records)


def test_units_fallback_to_limit_unit():
    rows, _ = _run([_sample()],
                   [_result(result_unit="", detection_limit_unit="mg/kg")], [])
    assert rows[0]["__equis_units"] == "mg/kg"


def test_is_reportable_synthesis():
    rows, _ = _run([_sample()], [_result(reportable_result="Yes")], [])
    assert rows[0]["__equis_is_reportable"] == "1"
    rows, _ = _run([_sample()], [_result(reportable_result="No")], [])
    assert rows[0]["__equis_is_reportable"] == "0"
    rows, _ = _run([_sample()], [_result(reportable_result="")], [])
    assert rows[0]["__equis_is_reportable"] == ""


def test_missing_sample_join_skips_row_and_warns():
    rows, qa = _run([_sample()],
                    [_result(**{"#sys_sample_code": "GHOST"})], [])
    assert rows == []
    assert any(r.category == "equis_missing_sample" for r in qa.records)


def test_missing_batch_join_warns_but_imports():
    rows, qa = _run([_sample()], [_result()],
                    [_batch(test_type="REANALYSIS")])   # key mismatch
    assert len(rows) == 1
    assert rows[0]["__equis_prep_batch"] == ""
    assert any(r.category == "equis_missing_batch" for r in qa.records)


def test_no_batch_sheet_no_warn():
    rows, qa = _run([_sample()], [_result()], [],
                    profile=_profile(batch_sheet=""))
    assert rows[0]["__equis_prep_batch"] == ""
    assert not any(r.category == "equis_missing_batch" for r in qa.records)


def test_source_row_stamped():
    r1 = _result()
    r2 = _result(chemical_name="Arsenic")
    r1["__sheet_row"] = 7
    r2["__sheet_row"] = 9
    rows, _ = _run([_sample()], [r1, r2], [])
    assert [r["__source_row"] for r in rows] == [7, 9]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_equis_reader.py -q`
Expected: FAIL — `ModuleNotFoundError: autogis.core.envmon.equis_reader`

- [ ] **Step 3: Implement the transform module**

```python
# autogis/core/envmon/equis_reader.py
"""EQuIS v1 family EDD reader (Step 3 slice 1 of the ingestion program).

Joins the three-sheet EQuIS shape (sample + result/QC + batch) into flat row
dicts with synthesized ``__equis_*`` columns — transform logic here,
column->canonical mapping in the profile YAML (ADR-0080 pattern). Lab-QC rows
(LAB-source samples, surrogate rows) are tagged ``__equis_stream="qc"`` and
forked by run_edd_import into Env_QCResults.

Column constants target the EQuIS v1 dialect family (wmrd/epar4/nysdec) —
verified against the real B25030623 WMRD export 2026-07-10. Mining's renamed
cousins are a later slice.

Spec: docs/superpowers/specs/2026-07-10-edd-step3-equis-wmrd-design.md.
arcpy-free; xlrd is lazy-imported in read_equis_xls only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_WARNING
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


def _get(row: dict, col: str) -> str:
    val = row.get(col)
    return "" if val is None else str(val).strip()


def _na(val: str) -> str:
    """WMRD uses literal 'NA' as its null in run discriminators."""
    return "" if val.upper() == "NA" else val


def read_equis_xls(path: Path, profile,
                   qa: Optional[QACollector] = None) -> list[dict]:
    """Read a legacy .xls EQuIS EDD and return transformed flat row dicts."""
    qa = qa if qa is not None else QACollector()
    import xlrd  # required dep, lazy so nothing else pays the import

    wb = xlrd.open_workbook(str(path))

    def _sheet_to_dicts(name: str) -> list[dict]:
        sheet = wb.sheet_by_name(name)
        if sheet.nrows == 0:
            return []
        headers = [_cell_text(c, wb.datemode) for c in sheet.row(0)]
        out = []
        for r in range(1, sheet.nrows):
            row = {h: _cell_text(c, wb.datemode)
                   for h, c in zip(headers, sheet.row(r)) if h}
            row["__sheet_row"] = r + 1   # 1-based, header = row 1
            out.append(row)
        return out

    sample_rows = _sheet_to_dicts(profile.sample_sheet)
    result_rows = _sheet_to_dicts(profile.result_sheet)
    batch_rows = (_sheet_to_dicts(profile.batch_sheet)
                  if profile.batch_sheet else [])
    return transform_equis_sheets(sample_rows, result_rows, batch_rows,
                                  profile, qa)


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


def transform_equis_sheets(sample_rows: list[dict], result_rows: list[dict],
                           batch_rows: list[dict], profile,
                           qa: QACollector) -> list[dict]:
    """Join + synthesize; returns flat rows, QC rows tagged __equis_stream."""
    sample_index = {}
    for s in sample_rows:
        key = profile.resolve_column(s, "sample_id")
        if key:
            sample_index[key] = s

    # (sample, method, fraction, column, test_type) -> {"Prep": id, ...}
    batch_index: dict[tuple, dict] = {}
    for b in batch_rows:
        key = (_get_sample_id(b, profile), _get(b, _COL_METHOD),
               _get(b, _COL_FRACTION), _get(b, _COL_COLUMN_NUM),
               _get(b, _COL_TEST_TYPE))
        batch_index.setdefault(key, {})[_get(b, _COL_BATCH_TYPE)] = \
            _get(b, _COL_BATCH_ID)

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
        row.update(src)             # result columns win on collision
        row["__source_row"] = row_num
        _tag_stream(row, profile, qa, row_num)
        _synthesize_result(row, qa, row_num)
        _synthesize_qualifier(row)
        _compose_dilution_key(row)
        _route_limits(row, qa, row_num)
        _synthesize_reportable(row)
        _attach_batches(row, batch_index, batch_rows, sample_id, profile,
                        qa, row_num)
        out.append(row)
    return out


def _get_sample_id(row: dict, profile) -> str:
    return (profile.resolve_column(row, "sample_id") or "").strip()


def _tag_stream(row: dict, profile, qa: QACollector, row_num: int) -> None:
    is_lab = _get(row, _COL_SAMPLE_SOURCE).casefold() == "lab"
    is_sur = _get(row, _COL_RESULT_TYPE).upper() == "SUR"
    if not (is_lab or is_sur):
        row["__equis_qc_type"] = ""
        return
    row["__equis_stream"] = "qc"
    if is_sur:
        row["__equis_qc_type"] = "SURROGATE"
        return
    raw = _get(row, _COL_SAMPLE_TYPE)
    mapped = profile.value_maps.get("qc_sample_type", {}).get(raw)
    if mapped is None:
        qa.add(SEV_WARNING, "equis_unmapped_qc_type",
               f"Row {row_num}: lab-QC sample type '{raw}' not in the "
               f"profile qc_sample_type map — imported with the raw code; "
               f"verify and extend the map",
               source_row=row_num)
        mapped = raw
    row["__equis_qc_type"] = mapped


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


def _compose_dilution_key(row: dict) -> None:
    # Unconditional per-row fold (ADR-0080 determinism argument); WMRD's
    # literal 'NA' nulls normalized out so an undiluted INITIAL run keys
    # compatibly with formats that leave the columns blank.
    parts = (_na(_get(row, _COL_DILUTION)), _na(_get(row, _COL_TEST_TYPE)),
             _na(_get(row, _COL_COLUMN_NUM)), _na(_get(row, _COL_BASIS)))
    row["__equis_method_dilution_key"] = "|".join(p for p in parts if p)
```

(D8 sanity check: `dilution=5, test_type=DILUTION, column=NA, basis=Dry` folds to `"5|DILUTION|Dry"`; an undiluted INITIAL run folds to `"1|INITIAL|Dry"` — both per-row deterministic, matching the tests. Continue the module:)

```python
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
    if limit_unit and result_unit \
            and limit_unit.casefold() != result_unit.casefold():
        try:
            value = convert(value, limit_unit, result_unit)
        except UnitError as exc:
            qa.add(SEV_WARNING, "equis_limit_unit_mismatch",
                   f"Row {row_num}: {exc}; raw limit value kept",
                   source_row=row_num)
    return f"{value:g}"


def _synthesize_reportable(row: dict) -> None:
    raw = _get(row, _COL_REPORTABLE).casefold()
    row["__equis_is_reportable"] = ("1" if raw in ("yes", "y")
                                    else "0" if raw in ("no", "n") else "")


def _attach_batches(row: dict, batch_index: dict, batch_rows: list[dict],
                    sample_id: str, profile, qa: QACollector,
                    row_num: int) -> None:
    key = (sample_id, _get(row, _COL_METHOD), _get(row, _COL_FRACTION),
           _get(row, _COL_COLUMN_NUM), _get(row, _COL_TEST_TYPE))
    hit = batch_index.get(key, {})
    row["__equis_prep_batch"] = hit.get("Prep", "")
    row["__equis_analysis_batch"] = hit.get("Analysis", "")
    if batch_rows and not hit:
        qa.add(SEV_WARNING, "equis_missing_batch",
               f"Row {row_num}: no batch-sheet entry for "
               f"({sample_id}, {key[1]}, {key[2]}, {key[3]}, {key[4]}) — "
               f"batch ids empty", source_row=row_num)
```

Note for the implementer: the test `test_limit_conversion_and_short_circuit` asserts `"0.5"`/`"0.1"`/`"1.0"` pass-throughs — `f"{value:g}"` renders `0.5 → "0.5"`, `0.1 → "0.1"`, `1.0 → "1"`. That last one breaks the test's `"1.0"` expectation. Use this exact formatting rule instead: return `raw` unchanged when no conversion happened, and `f"{value:g}"` only after an actual `convert()` call. Restructure `_convert_limit` accordingly:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/envmon/test_equis_reader.py -q` → all PASS. Then `python -m pytest -q` → suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/equis_reader.py tests/envmon/test_equis_reader.py
git commit -m "feat(envmon): EQuIS v1 family transform — join, QC tagging, __equis_* synthesis"
```

---

### Task 4: xlrd loading + `read_edd_file` dispatch + dependency

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py:23-40` (dispatch), docstring line 29-30
- Modify: `pyproject.toml:6` (dependencies)
- Test: `tests/envmon/test_equis_reader.py` (append)

**Interfaces:**
- Produces: `read_edd_file` dispatches `equis_xls` → `read_equis_xls(path, profile, qa)` (defined in Task 3's module).
- Consumes: `read_equis_xls` from Task 3.

- [ ] **Step 1: Write the failing test** (append to `tests/envmon/test_equis_reader.py`)

```python
def test_read_edd_file_dispatches_equis_xls(monkeypatch, tmp_path):
    from autogis.core.envmon import edd_importer
    from autogis.core.envmon import equis_reader
    seen = {}

    def fake(path, profile, qa=None):
        seen["args"] = (path, profile, qa)
        return [{"ok": "1"}]

    monkeypatch.setattr(equis_reader, "read_equis_xls", fake)
    prof = _profile()
    from autogis.core.common.qa import QACollector
    qa = QACollector()
    rows = edd_importer.read_edd_file(tmp_path / "f.xls", prof, qa)
    assert rows == [{"ok": "1"}]
    assert seen["args"][2] is qa


def test_cell_text_normalization():
    import xlrd
    from autogis.core.envmon.equis_reader import _cell_text

    class Cell:
        def __init__(self, ctype, value):
            self.ctype, self.value = ctype, value

    assert _cell_text(Cell(xlrd.XL_CELL_NUMBER, 438175.0), 0) == "438175"
    assert _cell_text(Cell(xlrd.XL_CELL_NUMBER, 0.5), 0) == "0.5"
    assert _cell_text(Cell(xlrd.XL_CELL_TEXT, "  Lead "), 0) == "Lead"
    assert _cell_text(Cell(xlrd.XL_CELL_EMPTY, ""), 0) == ""
    # 2025-03-11 09:54 as an Excel serial (1900 datemode)
    serial = 45727.0 + (9 * 60 + 54) / (24 * 60)
    assert _cell_text(Cell(xlrd.XL_CELL_DATE, serial), 0) == "03/11/2025 09:54"
```

- [ ] **Step 2: Run to verify the dispatch test fails**

Run: `python -m pytest tests/envmon/test_equis_reader.py -q`
Expected: `test_read_edd_file_dispatches_equis_xls` FAILS with `ValueError: Unknown EDD format 'equis_xls'`. (`test_cell_text_normalization` already passes — `_cell_text` shipped in Task 3; it lives here because xlrd-typed cells are this task's concern. If the serial-date expectation fails instead, fix the test's serial constant against `xlrd.xldate.xldate_from_datetime_tuple((2025, 3, 11, 9, 54, 0), 0)` rather than the implementation.)

- [ ] **Step 3: Implement dispatch + dependency**

In `read_edd_file` (edd_importer.py), after the `wqx_csv` branch:

```python
    if profile.format == "equis_xls":
        from .equis_reader import read_equis_xls
        return read_equis_xls(path, profile, qa)
```

Update the function docstring's qa sentence to `(wqx_csv, equis_xls)`.

In `pyproject.toml` line 6:

```toml
dependencies = ["PyYAML", "click>=8.0", "openpyxl", "numpy>=1.24", "xlrd>=2.0"]   # click>=8.0: introspect.py's _field() calls param.to_info_dict(); xlrd: legacy .xls EQuIS EDDs (lazy import in equis_reader)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/envmon/test_equis_reader.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_importer.py pyproject.toml tests/envmon/test_equis_reader.py
git commit -m "feat(envmon): equis_xls dispatch in read_edd_file + xlrd dependency"
```

---

### Task 5: `normalize_edd_rows` — cas_number / quantitation_limit / is_reportable columns

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py:219-227` region (after the detection_limit block) and the `AnalyticalResultRecord(...)` construction (~line 317)
- Test: `tests/envmon/test_edd_importer.py` (existing — append; create if absent)

**Interfaces:**
- Consumes: Task 1's `AnalyticalResultRecord` fields.
- Produces: profile columns `cas_number`, `quantitation_limit`, `is_reportable` resolved onto every analytical record (all formats; absent mapping → defaults).

- [ ] **Step 1: Write the failing test**

```python
def test_normalize_resolves_step3_columns():
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.edd_importer import normalize_edd_rows
    from autogis.core.envmon.edd_profile import LabEDDProfile
    profile = LabEDDProfile(
        profile_id="p", lab_name="l", format="flat_csv",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sid", "location_id": "loc",
                 "event_date": "dt", "matrix": "mx", "analyte": "an",
                 "result": "res", "units": "un", "qualifier": "q",
                 "reporting_limit": "rl", "cas_number": "cas",
                 "quantitation_limit": "ql", "is_reportable": "rep"},
        matrix_map={}, nondetect_qualifiers=[])
    rows = [{"sid": "S1", "loc": "MW-1", "dt": "01/02/2026", "mx": "GW",
             "an": "Lead", "res": "1.2", "un": "ug/l", "q": "", "rl": "0.5",
             "cas": "7439-92-1", "ql": "2.5", "rep": "1"}]
    qa = QACollector()
    _, results = normalize_edd_rows(rows, profile, "site", "batch",
                                    {}, {}, qa)
    assert results[0].CASNumber == "7439-92-1"
    assert results[0].QuantitationLimit == 2.5
    assert results[0].IsReportable == 1


def test_normalize_step3_columns_default_when_unmapped():
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.edd_importer import normalize_edd_rows
    from autogis.core.envmon.edd_profile import LabEDDProfile
    profile = LabEDDProfile(
        profile_id="p", lab_name="l", format="flat_csv",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sid", "location_id": "loc",
                 "event_date": "dt", "matrix": "mx", "analyte": "an",
                 "result": "res", "units": "un", "qualifier": "q",
                 "reporting_limit": "rl"},
        matrix_map={}, nondetect_qualifiers=[])
    rows = [{"sid": "S1", "loc": "MW-1", "dt": "01/02/2026", "mx": "GW",
             "an": "Lead", "res": "1.2", "un": "ug/l", "q": "", "rl": ""}]
    qa = QACollector()
    _, results = normalize_edd_rows(rows, profile, "site", "batch",
                                    {}, {}, qa)
    assert results[0].CASNumber == ""
    assert results[0].QuantitationLimit is None
    assert results[0].IsReportable is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/envmon/test_edd_importer.py -q`
Expected: FAIL — `AttributeError`/`AssertionError` on the new fields (records default until wired).

- [ ] **Step 3: Implement** — in `normalize_edd_rows`, directly after the detection-limit block (line ~227):

```python
        # Step-3 EQuIS additions — format-agnostic like detection_limit
        # (every EQuIS dialect carries cas_rn / quantitation_limit /
        # reportable_result natively; other formats simply don't map them).
        cas_number = profile.resolve_column(row, "cas_number") or ""
        quantitation_limit = None
        ql_raw = profile.resolve_column(row, "quantitation_limit")
        if ql_raw:
            try:
                quantitation_limit = float(ql_raw.replace(",", ""))
            except (ValueError, AttributeError):
                pass
        rep_raw = (profile.resolve_column(row, "is_reportable") or "").strip()
        is_reportable = int(rep_raw) if rep_raw in ("0", "1") else None
```

And in the `AnalyticalResultRecord(...)` constructor after `MethodSpeciation=speciation,`:

```python
            CASNumber=cas_number,
            QuantitationLimit=quantitation_limit,
            IsReportable=is_reportable,
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/envmon/test_edd_importer.py -q` → PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_importer.py tests/envmon/test_edd_importer.py
git commit -m "feat(envmon): resolve cas_number/quantitation_limit/is_reportable in normalize_edd_rows"
```

---

### Task 6: `normalize_qc_rows` — tagged rows → QCResultRecord

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py` (new function after `normalize_edd_rows`, ~line 321)
- Test: `tests/envmon/test_qc_normalizer.py` (new)

**Interfaces:**
- Consumes: Task 1's `QCResultRecord`; existing `parse_result_value`, `normalize_analyte_name`, `parse_excel_date` (already imported at the top of edd_importer.py).
- Produces: `normalize_qc_rows(rows: list[dict], profile: LabEDDProfile, site_id: str, batch_id: str, analyte_dictionary: dict, qa: QACollector) -> list[QCResultRecord]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/envmon/test_qc_normalizer.py
"""normalize_qc_rows: tagged EQuIS QC rows -> QCResultRecord (slice-1 spec D4/D5)."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_importer import normalize_qc_rows
from autogis.core.envmon.edd_profile import LabEDDProfile


def _profile():
    return LabEDDProfile(
        profile_id="wmrd_test", lab_name="Test Lab", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={
            "sample_id": ["#sys_sample_code", "sys_sample_code"],
            "parent_sample_id": "parent_sample_code",
            "lab_sample_id": "lab_sample_id",
            "matrix": "sample_matrix_code",
            "analyte": "chemical_name", "cas_number": "cas_rn",
            "method": "lab_anl_method_name", "result_fraction": "fraction",
            "qc_type": "__equis_qc_type",
            "dilution_factor": "__equis_method_dilution_key",
            "analysis_date": "analysis_date",
            "result": "__equis_result", "units": "__equis_units",
            "qualifier": "__equis_qualifier",
            "reporting_limit": "__equis_reporting_limit",
            "detection_limit": "__equis_detection_limit",
            "prep_batch_id": "__equis_prep_batch",
            "analysis_batch_id": "__equis_analysis_batch",
            "qc_original_conc": "qc_original_conc",
            "qc_spike_added": "qc_spike_added",
            "qc_spike_measured": "qc_spike_measured",
            "qc_spike_recovery": "qc_spike_recovery",
            "qc_spike_lcl": "qc_spike_lcl",
            "qc_spike_ucl": "qc_spike_ucl",
            "qc_rpd": "qc_rpd", "qc_rpd_cl": "qc_rpd_cl",
            "qc_dup_original_conc": "qc_dup_original_conc",
            "qc_dup_spike_added": "qc_dup_spike_added",
            "qc_dup_spike_measured": "qc_dup_spike_measured",
            "qc_dup_spike_recovery": "qc_dup_spike_recovery",
        },
        matrix_map={"SOLID": "SOIL"}, nondetect_qualifiers=["U"])


def _qc_row(**over):
    row = {"#sys_sample_code": "LCS-438621", "parent_sample_code": "",
           "lab_sample_id": "B25030623-LCS", "sample_matrix_code": "SQ-CONTROL",
           "chemical_name": "Lead", "cas_rn": "7439-92-1",
           "lab_anl_method_name": "E200.8", "fraction": "Total",
           "analysis_date": "03/17/2025 14:02",
           "__equis_stream": "qc", "__equis_qc_type": "LCS",
           "__equis_result": "0.071", "__equis_units": "mg/kg",
           "__equis_qualifier": "", "__equis_reporting_limit": "0.5",
           "__equis_detection_limit": "0.1",
           "__equis_method_dilution_key": "1|Dry",
           "__equis_prep_batch": "PB-1", "__equis_analysis_batch": "AB-1",
           "__source_row": 7,
           "qc_original_conc": "", "qc_spike_added": "0.0731",
           "qc_spike_measured": "0.0701", "qc_spike_recovery": "96",
           "qc_spike_lcl": "80", "qc_spike_ucl": "120",
           "qc_rpd": "", "qc_rpd_cl": "",
           "qc_dup_original_conc": "", "qc_dup_spike_added": "",
           "qc_dup_spike_measured": "", "qc_dup_spike_recovery": ""}
    row.update(over)
    return row


def _run(rows):
    qa = QACollector()
    recs = normalize_qc_rows(rows, _profile(), "SITE1", "BATCH1",
                             {"Lead": {"abbreviation": "Pb"}}, qa)
    return recs, qa


def test_one_record_per_row_fully_mapped():
    recs, _ = _run([_qc_row()])
    assert len(recs) == 1                      # D5: no pivot, ever
    r = recs[0]
    assert r.ImportBatchID == "BATCH1"
    assert r.SiteID == "SITE1"
    assert r.Matrix == "SQ-CONTROL"   # control matrices pass through unmapped
    assert r.SampleID == "LCS-438621"
    assert r.QCType == "LCS"
    assert r.AnalyteName == "Lead"
    assert r.AnalyteCanonicalName == "Lead"
    assert r.CASNumber == "7439-92-1"
    assert r.MethodID == "E200.8"
    assert r.ResultFraction == "Total"
    assert r.MethodDilutionKey == "1|Dry"
    assert r.PrepBatchID == "PB-1"
    assert r.AnalysisBatchID == "AB-1"
    assert r.LabSampleID == "B25030623-LCS"
    assert r.ResultNumeric == 0.071
    assert r.Units == "mg/kg"
    assert r.ReportingLimit == 0.5
    assert r.DetectionLimit == 0.1
    assert r.SpikeAmount == 0.0731
    assert r.PercentRecovery == 96.0
    assert r.RecoveryLowerLimit == 80.0
    assert r.RecoveryUpperLimit == 120.0
    assert r.AnalysisDate is not None
    assert r.SourceRow == 7


def test_nd_qc_row_blank_result_with_limits():
    recs, _ = _run([_qc_row(**{"__equis_result": "ND",
                               "__equis_qc_type": "LAB_BLANK"})])
    r = recs[0]
    assert r.IsNonDetect == 1
    assert r.ResultNumeric is None
    assert r.ReportingLimit == 0.5


def test_spike_measured_fills_empty_result():
    recs, _ = _run([_qc_row(**{"__equis_result": ""})])
    assert recs[0].ResultNumeric == 0.0701     # documented convention


def test_dup_columns_fall_back_per_field():
    # MSD-style row: primary spike fields empty, qc_dup_* populated
    recs, _ = _run([_qc_row(**{
        "__equis_qc_type": "MSD",
        "qc_spike_added": "", "qc_spike_recovery": "",
        "qc_original_conc": "",
        "qc_dup_spike_added": "0.0365", "qc_dup_spike_recovery": "104",
        "qc_dup_original_conc": "0.0148",
        "qc_rpd": "2.1", "qc_rpd_cl": "20"})])
    r = recs[0]
    assert len(recs) == 1                      # still no second record
    assert r.SpikeAmount == 0.0365
    assert r.PercentRecovery == 104.0
    assert r.OriginalConcentration == 0.0148
    assert r.RPD == 2.1
    assert r.RPDControlLimit == 20.0


def test_missing_sample_id_skips_with_error():
    from autogis.core.common.qa import SEV_ERROR
    recs, qa = _run([_qc_row(**{"#sys_sample_code": ""})])
    assert recs == []
    assert any(r.severity == SEV_ERROR for r in qa.records)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/envmon/test_qc_normalizer.py -q`
Expected: FAIL — `ImportError: cannot import name 'normalize_qc_rows'`

- [ ] **Step 3: Implement** — add to `edd_importer.py` after `normalize_edd_rows` (import `QCResultRecord` in the existing `from .gdb_schema import ...` line):

```python
def _qc_float(profile: LabEDDProfile, row: dict, field: str) -> Optional[float]:
    raw = profile.resolve_column(row, field)
    if not raw:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def normalize_qc_rows(
    rows: list[dict],
    profile: LabEDDProfile,
    site_id: str,
    batch_id: str,
    analyte_dictionary: dict,
    qa: QACollector,
) -> list["QCResultRecord"]:
    """Convert reader-tagged lab-QC rows to QCResultRecord lists (spec D4/D5).

    One record per source row — MSD/LCSD are their own rows in EQuIS v1 and
    qc_dup_* merely echoes the row's own values (verified against the real
    WMRD export), so spike fields read the primary qc_* columns with a
    per-field qc_dup_* fallback. No second record is ever synthesized.
    """
    source_name = profile.profile_id
    records: list[QCResultRecord] = []
    for row_num, row in enumerate(rows, start=2):
        try:
            row_num = int(row.get("__source_row") or row_num)
        except (TypeError, ValueError):
            pass

        sample_id = profile.resolve_column(row, "sample_id")
        analyte_raw = profile.resolve_column(row, "analyte") or ""
        if not sample_id or not analyte_raw:
            qa.add(SEV_ERROR, "edd_qc_missing_required_field",
                   f"Row {row_num}: QC row missing "
                   f"{'sample_id' if not sample_id else 'analyte'} — skipped",
                   site_id=site_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            continue

        canonical = normalize_analyte_name(analyte_raw, analyte_dictionary)
        if canonical is None:
            qa.add(SEV_WARNING, "edd_unknown_analyte",
                   f"Row {row_num}: QC analyte '{analyte_raw}' not in the "
                   f"analyte dictionary; using raw name",
                   site_id=site_id, sample_id=sample_id,
                   import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            canonical = analyte_raw

        parsed = parse_result_value(profile.resolve_column(row, "result"))

        result_numeric = parsed.result_numeric
        spike_measured = _qc_float(profile, row, "qc_spike_measured") \
            if _qc_float(profile, row, "qc_spike_measured") is not None \
            else _qc_float(profile, row, "qc_dup_spike_measured")
        if result_numeric is None and not parsed.is_nondetect \
                and spike_measured is not None:
            # spike rows report the measured spike in qc_spike_measured, not
            # result_value (documented convention, paper mapping)
            result_numeric = spike_measured

        def _fallback(primary: str, dup: str) -> Optional[float]:
            v = _qc_float(profile, row, primary)
            return v if v is not None else _qc_float(profile, row, dup)

        records.append(QCResultRecord(
            ImportBatchID=batch_id,
            SiteID=site_id,
            Matrix=profile.map_value(
                "matrix", profile.resolve_column(row, "matrix") or ""),
            SampleID=sample_id,
            QCType=profile.resolve_column(row, "qc_type") or "",
            AnalyteName=analyte_raw,
            AnalyteCanonicalName=canonical,
            SourceWorkbook=source_name,
            SourceSheet=profile.result_sheet,
            SourceRow=row_num,
            PrepBatchID=profile.resolve_column(row, "prep_batch_id") or "",
            AnalysisBatchID=profile.resolve_column(
                row, "analysis_batch_id") or "",
            ParentSampleID=profile.resolve_column(
                row, "parent_sample_id") or "",
            LabSampleID=profile.resolve_column(row, "lab_sample_id") or "",
            CASNumber=profile.resolve_column(row, "cas_number") or "",
            MethodID=profile.resolve_column(row, "method") or "",
            ResultFraction=profile.map_value(
                "result_fraction",
                profile.resolve_column(row, "result_fraction") or ""),
            MethodDilutionKey=(profile.resolve_column(
                row, "dilution_factor") or "").strip(),
            AnalysisDate=parse_excel_date(
                profile.resolve_column(row, "analysis_date") or ""),
            ResultRawText=parsed.raw_text,
            ResultNumeric=result_numeric,
            Units=profile.resolve_column(row, "units") or "",
            ReportingLimit=_qc_float(profile, row, "reporting_limit"),
            DetectionLimit=_qc_float(profile, row, "detection_limit"),
            Qualifier=parsed.qualifier or
                (profile.resolve_column(row, "qualifier") or ""),
            IsNonDetect=int(parsed.is_nondetect),
            SpikeAmount=_fallback("qc_spike_added", "qc_dup_spike_added"),
            OriginalConcentration=_fallback("qc_original_conc",
                                            "qc_dup_original_conc"),
            PercentRecovery=_fallback("qc_spike_recovery",
                                      "qc_dup_spike_recovery"),
            RecoveryLowerLimit=_qc_float(profile, row, "qc_spike_lcl"),
            RecoveryUpperLimit=_qc_float(profile, row, "qc_spike_ucl"),
            RPD=_qc_float(profile, row, "qc_rpd"),
            RPDControlLimit=_qc_float(profile, row, "qc_rpd_cl"),
        ))
    return records
```

Implementation notes (read before coding):
- `parse_result_value(None)` — check its handling of None; if it requires a str, pass `profile.resolve_column(row, "result") or ""`.
- Qualifier: `parsed.qualifier` comes from the result text; the separate qualifier column wins when parse produced none — mirrors the analytical path's two-source qualifier handling in ONE expression because QC rows never carry embedded qualifiers in EQuIS (result_value is numeric); simplify to `profile.resolve_column(row, "qualifier") or ""` if `parsed.qualifier` proves always-empty in the fixture test.
- The double call in `spike_measured` is sloppy — hoist: `sm = _qc_float(profile, row, "qc_spike_measured"); spike_measured = sm if sm is not None else _qc_float(profile, row, "qc_dup_spike_measured")`.

- [ ] **Step 4: Run tests** — `python -m pytest tests/envmon/test_qc_normalizer.py -q` → PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_importer.py tests/envmon/test_qc_normalizer.py
git commit -m "feat(envmon): normalize_qc_rows — tagged EQuIS QC rows to QCResultRecord"
```

---

### Task 7: `run_edd_import` — QC stream split + Env_QCResults append

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py:389-411` (run_edd_import body)
- Test: `tests/envmon/test_qc_normalizer.py` (append)

**Interfaces:**
- Consumes: Task 6's `normalize_qc_rows`; existing `append_records_idempotent` stub (table-generic).
- Produces: QC records written to `Env_QCResults`; finalize counts gain `"qc_results"`.

- [ ] **Step 1: Write the failing test** (append; mirror the monkeypatch style of `test_run_edd_import_caller_collector_gets_wqx_reader_qa` in `tests/envmon/test_wqx_reader.py` — read that test first and reuse its stub pattern)

```python
def test_run_edd_import_splits_qc_stream(monkeypatch, tmp_path):
    from autogis.core.envmon import edd_importer

    seen = {"appends": []}
    monkeypatch.setattr(edd_importer, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: None)
    monkeypatch.setattr(edd_importer, "create_edd_import_batch",
                        lambda *a, **k: "BATCH1")
    monkeypatch.setattr(
        edd_importer, "append_records_idempotent",
        lambda gdb, table, records, qa, batch: seen["appends"].append(
            (table, len(records))))
    monkeypatch.setattr(edd_importer, "finalize_batch",
                        lambda gdb, batch, qa, counts, status:
                        seen.update(counts=counts))
    monkeypatch.setattr(edd_importer, "write_qa_to_gdb",
                        lambda *a, **k: None)

    field_row = {"sid": "S1", "loc": "MW-1", "dt": "01/02/2026", "mx": "GW",
                 "an": "Lead", "res": "1.2", "un": "ug/l", "q": "", "rl": ""}
    qc_row = dict(_qc_row())
    monkeypatch.setattr(edd_importer, "read_edd_file",
                        lambda path, profile, qa=None: [field_row, qc_row])

    from autogis.core.envmon.edd_profile import LabEDDProfile
    profile = LabEDDProfile(
        profile_id="p", lab_name="l", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": ["sid", "#sys_sample_code"],
                 "location_id": "loc", "event_date": "dt", "matrix": "mx",
                 "analyte": ["an", "chemical_name"], "result": "res",
                 "units": "un", "qualifier": "q", "reporting_limit": "rl"},
        matrix_map={}, nondetect_qualifiers=[])

    edd_importer.run_edd_import(
        tmp_path / "f.xls", profile, tmp_path / "g.gdb", "SITE1", {}, {})

    tables = dict(seen["appends"])
    assert tables["Env_AnalyticalResults"] == 1   # QC row not in analytical
    assert tables["Env_QCResults"] == 1
    assert seen["counts"]["qc_results"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/envmon/test_qc_normalizer.py -q`
Expected: FAIL — no `Env_QCResults` append; analytical count == 2 (QC row leaked into the analytical path).

- [ ] **Step 3: Implement** — in `run_edd_import`, replace the read/normalize/append block:

```python
    qa = qa if qa is not None else QACollector()
    rows = read_edd_file(edd_path, profile, qa)

    # Step-3 QC fork: readers with a QC concept (equis_xls) tag lab-QC rows;
    # untagged formats pass through unchanged.
    qc_rows = [r for r in rows if r.get("__equis_stream") == "qc"]
    data_rows = [r for r in rows if r.get("__equis_stream") != "qc"]

    samples, results = normalize_edd_rows(
        rows=data_rows,
        profile=profile,
        site_id=site_id,
        batch_id=batch_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        qa=qa,
        event_date_override=event_date_override,
    )

    qc_records = []
    if qc_rows:
        qc_records = normalize_qc_rows(
            qc_rows, profile, site_id, batch_id, analyte_dictionary, qa)

    append_records_idempotent(gdb_path, "Env_Samples", samples, qa, batch_id)
    append_records_idempotent(gdb_path, "Env_AnalyticalResults", results, qa, batch_id)
    if qc_records:
        append_records_idempotent(gdb_path, "Env_QCResults", qc_records, qa, batch_id)

    finalize_batch(
        gdb_path,
        batch_id,
        qa,
        {"analytical_results": len(results), "qc_results": len(qc_records)},
        "ERROR" if qa.has_blocking() else "PASS",
    )
```

(`finalize_batch` reads `counts` generically — unknown keys land in the Notes JSON; verified against `import_to_gdb.py:85-102`.)

- [ ] **Step 4: Run tests** — new test PASS; full suite green (the existing wqx run_edd_import test must still pass untouched — it exercises the untagged path).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/edd_importer.py tests/envmon/test_qc_normalizer.py
git commit -m "feat(envmon): fork tagged QC rows to Env_QCResults in run_edd_import"
```

---

### Task 8: `wmrd.yaml` profile

**Files:**
- Create: `autogis/config/lab_profiles/wmrd.yaml`
- Test: `tests/envmon/test_wmrd_profile.py` (new)

**Interfaces:**
- Consumes: everything above; profile column names must match Task 3/6 synthesized keys exactly.
- Produces: the shipped WMRD profile that Task 9's e2e test and real imports load by path.

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_wmrd_profile.py
"""Shipped WMRD (EQuIS v1) profile loads, validates, and maps the synthesized
__equis_* keys the reader actually writes."""
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile

PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "wmrd.yaml")


def test_profile_loads_and_validates():
    prof = LabEDDProfile.load(PROFILE)
    qa = QACollector()
    validate_edd_profile(prof, qa)
    assert not qa.has_blocking()
    assert prof.format == "equis_xls"
    assert prof.sample_sheet == "Sample_v1"
    assert prof.result_sheet == "TestResultQC_v1"
    assert prof.batch_sheet == "Batch_v1"


def test_synthesized_columns_wired():
    prof = LabEDDProfile.load(PROFILE)
    assert prof.columns["result"] == "__equis_result"
    assert prof.columns["units"] == "__equis_units"
    assert prof.columns["qualifier"] == "__equis_qualifier"
    assert prof.columns["qc_type"] == "__equis_qc_type"
    assert prof.columns["dilution_factor"] == "__equis_method_dilution_key"
    assert prof.columns["is_reportable"] == "__equis_is_reportable"
    assert prof.columns["reporting_limit"] == "__equis_reporting_limit"
    assert prof.columns["detection_limit"] == "__equis_detection_limit"
    assert prof.columns["quantitation_limit"] == "__equis_quantitation_limit"


def test_qc_sample_type_vocabulary():
    prof = LabEDDProfile.load(PROFILE)
    m = prof.value_maps["qc_sample_type"]
    assert m["N"] == ""
    assert m["QC-LCS"] == "LCS"
    assert m["QC-LMSD"] == "MSD"
    assert m["QC-LB"] == "LAB_BLANK"
    assert m["SRM"] == "SRM"
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/envmon/test_wmrd_profile.py -q` → FAIL (file not found).

- [ ] **Step 3: Write the profile**

```yaml
# autogis/config/lab_profiles/wmrd.yaml
# MT-WMRD EQuIS v1 EDD (legacy .xls, 3 sheets) — Step-3 slice 1.
# Vocabularies verified against ONE real Energy Labs export (B25030623,
# 2026-07-10) — single-lab provenance; extend maps as new labs appear.
# Reader: autogis/core/envmon/equis_reader.py (synthesized __equis_* columns).
profile_id: wmrd
lab_name: MT-WMRD EQuIS
format: equis_xls
date_format: "%m/%d/%Y"
encoding: utf-8

sample_sheet: Sample_v1
result_sheet: TestResultQC_v1
batch_sheet: Batch_v1

columns:
  # identity / joins (result sheet prefixes the key column with '#')
  sample_id: ["#sys_sample_code", "sys_sample_code"]
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

matrix_map:
  SOLID: SOIL
  WQ: GW
  # SQ-CONTROL / WQ-CONTROL intentionally unmapped: lab-control matrices
  # pass through as-is on QC rows.

nondetect_qualifiers: ["U", "UJ"]

value_maps:
  qc_sample_type:
    # Sample_v1.sample_type_code -> canonical QCType (Env_QCResults).
    # Field samples map to "" (analytical stream, no QC flag).
    "N": ""
    "FD": FIELD_DUP
    "QC-LCS": LCS
    "QC-LCSD": LCSD
    "QC-LMS": MS
    "QC-LMSD": MSD
    "QC-LB": LAB_BLANK
    "QC-LD": LAB_DUP
    "QC-LCCV": CCV
    "QC-LICV": ICV
    "QC-PDS": PDS
    "QC-LIFC": IFC
    "SRM": SRM
    "CRA": CRA
```

**IMPORTANT — field-duplicate handling:** `"N": ""` and `"FD": FIELD_DUP` live under `qc_sample_type`, but field-sample rows go through `normalize_edd_rows`, whose `qc_type` resolution reads the `qc_type` column mapping → `__equis_qc_type` — and a naive `_tag_stream` that only consults the map for LAB/SUR rows would set `""` for a **field duplicate** (`sample_type_code=FD`, `sample_source=Field`), silently losing its FIELD_DUP flag. This is the authoritative `_tag_stream` — implement it this way from the start (it supersedes the shorter sketch shown in Task 3):

```python
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
```

Add to Task 3's tests (same file, same commit as Task 3 if executing in order; otherwise append here):

```python
def test_field_duplicate_stays_analytical_with_qctype():
    prof = _profile(value_maps={"qc_sample_type": {"N": "", "FD": "FIELD_DUP"}})
    rows, _ = _run([_sample(sample_type_code="FD")], [_result()], [],
                   profile=prof)
    assert rows[0].get("__equis_stream") != "qc"
    assert rows[0]["__equis_qc_type"] == "FIELD_DUP"


def test_unmapped_field_type_warns_and_flags():
    rows, qa = _run([_sample(sample_type_code="XX")], [_result()], [])
    assert rows[0].get("__equis_stream") != "qc"
    assert rows[0]["__equis_qc_type"] == "XX"
    assert any(r.category == "equis_unmapped_qc_type" for r in qa.records)
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/envmon/test_wmrd_profile.py tests/envmon/test_equis_reader.py -q` → PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/config/lab_profiles/wmrd.yaml tests/envmon/test_wmrd_profile.py tests/envmon/test_equis_reader.py autogis/core/envmon/equis_reader.py
git commit -m "feat(envmon): shipped WMRD EQuIS profile + field-dup stream fix"
```

---

### Task 9: Synthetic .xls fixture + end-to-end test

**Files:**
- Create: `tests/fixtures/make_wmrd_fixture.py` (generator — committed for regeneration, NOT run by the suite)
- Create: `tests/fixtures/wmrd_equis_fixture.xls` (committed binary, ~15 KB)
- Test: `tests/envmon/test_equis_e2e.py` (new)

**Interfaces:**
- Consumes: the full stack (read_edd_file → transform → both normalizers → compute_unique_key) and the shipped `wmrd.yaml`.
- Produces: the regression fixture later slices reuse.

- [ ] **Step 1: Write the generator script**

```python
# tests/fixtures/make_wmrd_fixture.py
"""One-shot generator for wmrd_equis_fixture.xls (EQuIS v1 shape, synthetic
data). Requires xlwt (NOT a project dependency):  pip install xlwt
Run from the repo root:  python tests/fixtures/make_wmrd_fixture.py
Regenerate only when the fixture must change; commit the .xls binary."""
import xlwt

SAMPLE_HDR = ["#data_provider", "sys_sample_code", "sample_name",
              "sample_matrix_code", "sample_type_code", "sample_source",
              "parent_sample_code", "sample_date", "sys_loc_code",
              "start_depth", "end_depth", "depth_unit"]
SAMPLES = [
    ["ELI", "S-001", "MW-1", "SOLID", "N", "Field", "",
     "03/11/2025 09:54", "MW-1", "0", "2", "ft"],
    ["ELI", "S-002", "MW-2", "SOLID", "N", "Field", "",
     "03/11/2025 10:30", "MW-2", "0", "2", "ft"],
    ["ELI", "LCS-1", "LCS", "SQ-CONTROL", "QC-LCS", "LAB", "",
     "03/12/2025 08:00", "", "", "", ""],
    ["ELI", "MB-1", "Method Blank", "SQ-CONTROL", "QC-LB", "LAB", "",
     "03/12/2025 08:00", "", "", "", ""],
    ["ELI", "MSD-1", "MSD", "SOLID", "QC-LMSD", "LAB", "S-001",
     "03/11/2025 09:54", "", "", "", ""],
]

RESULT_HDR = ["#sys_sample_code", "lab_anl_method_name", "analysis_date",
              "fraction", "column_number", "test_type", "lab_matrix_code",
              "analysis_location", "basis", "container_id",
              "dilution_factor", "prep_method", "prep_date",
              "lab_name_code", "lab_sample_id", "cas_rn", "chemical_name",
              "result_value", "result_type_code", "reportable_result",
              "detect_flag", "lab_qualifiers", "validator_qualifiers",
              "interpreted_qualifiers", "method_detection_limit",
              "reporting_detection_limit", "quantitation_limit",
              "result_unit", "detection_limit_unit",
              "qc_original_conc", "qc_spike_added", "qc_spike_measured",
              "qc_spike_recovery", "qc_dup_original_conc",
              "qc_dup_spike_added", "qc_dup_spike_measured",
              "qc_dup_spike_recovery", "qc_rpd", "qc_spike_lcl",
              "qc_spike_ucl", "qc_rpd_cl"]


def _res(code, method, chem, cas, value, detect="Y", frac="Total",
         test_type="INITIAL", rtype="TRG", basis="Dry", dil="1",
         unit="mg/kg", lunit="mg/kg", mdl="0.1", rl="0.5", ql="1.0",
         qual="", spike=("", "", "", ""), dup=("", "", "", ""),
         rpd="", lcl="", ucl="", rpdcl="", reportable="Yes"):
    return [code, method, "03/17/2025 14:02", frac, "NA", test_type,
            "SOLID", "LB", basis, "", dil, "E200.2", "03/12/2025 08:00",
            "ELI-B", f"LAB-{code}", cas, chem, value, rtype, reportable,
            detect, qual, "", "", mdl, rl, ql, unit, lunit,
            spike[0], spike[1], spike[2], spike[3],
            dup[0], dup[1], dup[2], dup[3], rpd, lcl, ucl, rpdcl]


RESULTS = [
    # field sample S-001: detected lead (Total) + dissolved rerun + ND arsenic
    _res("S-001", "E200.8", "Lead", "7439-92-1", "12.4"),
    _res("S-001", "E200.8", "Lead", "7439-92-1", "11.9", frac="Dissolved"),
    # dilution rerun of the same (sample, analyte, fraction) — IsReportable
    # disambiguation target: only the INITIAL run is reportable
    _res("S-001", "E200.8", "Arsenic", "7440-38-2", "2.2",
         test_type="DILUTION", dil="5", reportable="No"),
    _res("S-001", "E200.8", "Arsenic", "7440-38-2", "2.0"),
    # ND row with limits, ug/kg limit units (conversion target: /1000)
    _res("S-002", "E200.8", "Cadmium", "7440-43-9", "", detect="N",
         mdl="100", rl="500", ql="1000", lunit="ug/kg"),
    # surrogate on a FIELD sample -> QC stream
    _res("S-001", "8081", "Decachlorobiphenyl", "2051-24-3", "96",
         rtype="SUR", unit="% recovery", lunit="% recovery",
         mdl="", rl="", ql=""),
    # LCS with spike columns
    _res("LCS-1", "E200.8", "Lead", "7439-92-1", "0.0701",
         spike=("", "0.0731", "0.0701", "96"), lcl="80", ucl="120"),
    # method blank: ND with limits
    _res("MB-1", "E200.8", "Lead", "7439-92-1", "", detect="N"),
    # MSD: dup columns echo own values (real-file convention), rpd present
    _res("MSD-1", "E200.8", "Lead", "7439-92-1", "0.0512",
         spike=("0.0148", "0.0365", "0.0512", "104"),
         dup=("0.0148", "0.0365", "0.0512", "104"),
         rpd="2.1", lcl="75", ucl="125", rpdcl="20"),
]

BATCH_HDR = ["#sys_sample_code", "lab_anl_method_name", "Expr1002",
             "fraction", "column_number", "test_type", "test_batch_type",
             "test_batch_id"]
BATCHES = [
    ["S-001", "E200.8", "junk", "Total", "NA", "INITIAL", "Prep", "PB-1"],
    ["S-001", "E200.8", "junk", "Total", "NA", "INITIAL", "Analysis", "AB-1"],
    ["LCS-1", "E200.8", "junk", "Total", "NA", "INITIAL", "Analysis", "AB-1"],
]


def main() -> None:
    wb = xlwt.Workbook()
    for name, hdr, rows in (("Sample_v1", SAMPLE_HDR, SAMPLES),
                            ("TestResultQC_v1", RESULT_HDR, RESULTS),
                            ("Batch_v1", BATCH_HDR, BATCHES)):
        ws = wb.add_sheet(name)
        for c, h in enumerate(hdr):
            ws.write(0, c, h)
        for r, row in enumerate(rows, start=1):
            for c, v in enumerate(row):
                ws.write(r, c, v)
    wb.save("tests/fixtures/wmrd_equis_fixture.xls")
    print("wrote tests/fixtures/wmrd_equis_fixture.xls")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the fixture** (xlwt install is a dev-machine one-off; use the scratchpad venv/pip if needed — do NOT add xlwt to pyproject)

Run: `pip install xlwt` then `python tests/fixtures/make_wmrd_fixture.py`
Expected: `wrote tests/fixtures/wmrd_equis_fixture.xls`

- [ ] **Step 3: Write the end-to-end test**

```python
# tests/envmon/test_equis_e2e.py
"""End-to-end: .xls fixture -> read_edd_file -> split -> both normalizers ->
key distinctness on both tables. Loads the SHIPPED wmrd.yaml."""
import dataclasses
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_importer import (
    normalize_edd_rows, normalize_qc_rows, read_edd_file,
)
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.gdb_schema import compute_unique_key

FIXTURE = Path(__file__).parent.parent / "fixtures" / "wmrd_equis_fixture.xls"
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "wmrd.yaml")


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


def test_stream_split_counts():
    _, results, qc, _ = _import()
    # 9 result rows: 5 analytical (2 Pb + 2 As reruns + 1 ND Cd),
    # 4 QC (surrogate, LCS, blank, MSD)
    assert len(results) == 5
    assert len(qc) == 4


def test_analytical_keys_distinct():
    _, results, _, _ = _import()
    keys = {compute_unique_key(dataclasses.asdict(r),
                               "Env_AnalyticalResults") for r in results}
    assert len(keys) == 5     # fraction + dilution-rerun discriminate


def test_qc_keys_distinct():
    _, _, qc, _ = _import()
    keys = {compute_unique_key(dataclasses.asdict(r), "Env_QCResults")
            for r in qc}
    assert len(keys) == 4


def test_rerun_flags_and_dilution_keys():
    _, results, _, _ = _import()
    arsenic = sorted((r for r in results if r.AnalyteName == "Arsenic"),
                     key=lambda r: r.MethodDilutionKey)
    assert len(arsenic) == 2
    initial = next(r for r in arsenic if "DILUTION" not in r.MethodDilutionKey)
    diluted = next(r for r in arsenic if "DILUTION" in r.MethodDilutionKey)
    assert initial.IsReportable == 1
    assert diluted.IsReportable == 0
    assert diluted.MethodDilutionKey == "5|DILUTION|Dry"


def test_nd_row_limits_converted_to_result_units():
    _, results, _, _ = _import()
    cd = next(r for r in results if r.AnalyteName == "Cadmium")
    assert cd.IsNonDetect == 1
    assert cd.Units == "mg/kg"
    assert cd.DetectionLimit == 0.1        # 100 ug/kg -> 0.1 mg/kg
    assert cd.ReportingLimit == 0.5
    assert cd.QuantitationLimit == 1.0
    assert cd.CASNumber == "7440-43-9"


def test_surrogate_routed_to_qc_with_field_sample_id():
    _, _, qc, _ = _import()
    sur = next(r for r in qc if r.QCType == "SURROGATE")
    assert sur.SampleID == "S-001"
    assert sur.PercentRecovery is None or sur.ResultNumeric == 96.0


def test_lcs_spike_fields_and_batches():
    _, _, qc, _ = _import()
    lcs = next(r for r in qc if r.QCType == "LCS")
    assert lcs.SpikeAmount == 0.0731
    assert lcs.PercentRecovery == 96.0
    assert lcs.AnalysisBatchID == "AB-1"


def test_msd_single_record_with_rpd():
    _, _, qc, _ = _import()
    msd = [r for r in qc if r.QCType == "MSD"]
    assert len(msd) == 1                   # D5: no synthesized second record
    assert msd[0].RPD == 2.1
    assert msd[0].RPDControlLimit == 20.0
    assert msd[0].ParentSampleID == "S-001"


def test_blank_is_nd_with_units():
    _, _, qc, _ = _import()
    mb = next(r for r in qc if r.QCType == "LAB_BLANK")
    assert mb.IsNonDetect == 1
    assert mb.ResultNumeric is None
```

Fixture-note for the implementer: `test_surrogate_routed_to_qc_with_field_sample_id` asserts loosely on purpose — the surrogate row reports 96 in `result_value` (% recovery units), so `ResultNumeric == 96.0`; `PercentRecovery` is None because surrogate rows carry no `qc_spike_recovery` in the fixture. If the real-file check (Step 6) shows Energy Labs populating `qc_spike_recovery` on SUR rows, extend the fixture and tighten this test in the same commit.

- [ ] **Step 4: Run the e2e tests**

Run: `python -m pytest tests/envmon/test_equis_e2e.py -q` → all PASS (iterate on transform/normalizer bugs the e2e surfaces; fix in the module, not by loosening asserts).

- [ ] **Step 5: Full suite**

Run: `python -m pytest -q` → green.

- [ ] **Step 6: Manual real-file verification (record output in the PR — file stays out of the repo)**

Write a scratchpad script that loads the shipped wmrd.yaml, runs `read_edd_file` + both normalizers against `C:\Users\ichbi\OneDrive\Desktop\Analytical Report Format Examples\B25030623-MT-WMRD (EQUIS).XLS`, and prints: analytical/QC record counts — expected **243 analytical / 332 QC**. Derivation (from the 2026-07-10 sheet peek): the file's only Field-source rows are (sample_type=N, result_type=TRG) = 243; every SUR row sits on a LAB-source sample in this particular file, and CRA/SRM are LAB-source — so QC = 575 − 243 = 332. Also print: distinct-key counts on both tables, the QA category histogram, and 3 spot rows. Verify: no `equis_missing_sample`/`equis_missing_batch` floods, every QC-* type maps, ND rows carry converted limits, IsReportable == 1 on all 575 (`reportable_result` all Yes). Paste the summary into the PR description.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/make_wmrd_fixture.py tests/fixtures/wmrd_equis_fixture.xls tests/envmon/test_equis_e2e.py
git commit -m "test(envmon): committed EQuIS .xls fixture + end-to-end WMRD import test"
```

---

### Task 10: `canonical_read` — IsReportable rerun disambiguation (D9)

**Files:**
- Modify: `autogis/core/envmon/canonical_read.py` (docstring lines 7-9, new step inside `canonical_result_rows` after the fraction filter ~line 77)
- Test: `tests/envmon/test_merge_gate_canonical.py` (existing — append) or `tests/envmon/test_canonical_read.py` if that's where `canonical_result_rows` unit tests live — check with `grep -l canonical_result_rows tests/envmon/` and append to the unit-test file.

**Interfaces:**
- Consumes: rows/records that may carry `IsReportable` (Task 1); all existing consumers pass dicts lacking the key — `.get()` keeps them on the legacy path.
- Produces: reportable-preferring resolution; new QA category `rerun_resolved`.

- [ ] **Step 1: Write the failing tests**

```python
def _rerun_row(mdk, reportable, value):
    return {"SiteID": "s", "Matrix": "SOIL", "LocationID": "MW-1",
            "SampleID": "S1", "SampleDate": "2026-01-02",
            "AnalyteCanonicalName": "Arsenic", "DepthIntervalText": "",
            "ResultFraction": "Total", "QCType": "",
            "MethodDilutionKey": mdk, "IsReportable": reportable,
            "ResultNumeric": value}


def test_isreportable_resolves_rerun_groups():
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.canonical_read import canonical_result_rows
    qa = QACollector()
    rows = [_rerun_row("", 1, 2.0), _rerun_row("5|DILUTION", 0, 2.2)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1
    assert out[0]["ResultNumeric"] == 2.0
    assert any(r.category == "rerun_resolved" for r in qa.records)


def test_null_isreportable_reruns_unchanged():
    # pre-Step-3 imports: flag NULL everywhere -> both rows pass (pinned
    # legacy behavior; do NOT guess among reruns without the flag)
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.canonical_read import canonical_result_rows
    qa = QACollector()
    rows = [_rerun_row("", None, 2.0), _rerun_row("5|DILUTION", None, 2.2)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 2


def test_single_run_groups_untouched_by_reportable_zero():
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.canonical_read import canonical_result_rows
    qa = QACollector()
    rows = [_rerun_row("", 0, 2.0)]        # one run, flagged not-reportable
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1                   # never drop a group's only run
```

- [ ] **Step 2: Run to verify failure** — first test FAILS (`len(out) == 2`).

- [ ] **Step 3: Implement** — in `canonical_result_rows`, after the fraction-filter `out = [...]` line:

```python
    # IsReportable rerun disambiguation (Step 3): where one group spans
    # multiple MethodDilutionKeys AND the lab marked run(s) reportable, keep
    # only the reportable ones. Groups with no flag anywhere (all pre-Step-3
    # imports) keep every run — legacy behavior, pinned by tests.
    def _reportable(r) -> bool:
        return r.get("IsReportable") in (1, "1", True)

    rerun_groups: Dict[Tuple, List[dict]] = defaultdict(list)
    for r in out:
        rerun_groups[(_group_key(r),
                      r.get("ResultFraction") or "")].append(r)
    dropped = set()
    for (gkey, _frac), members in rerun_groups.items():
        mdks = {m.get("MethodDilutionKey") or "" for m in members}
        if len(mdks) > 1 and any(_reportable(m) for m in members):
            for m in members:
                if not _reportable(m):
                    dropped.add(id(m))
            qa.add(SEV_INFO, "rerun_resolved",
                   f"{gkey[2]} {gkey[5]}: {len(members)} rerun row(s) "
                   f"resolved to the lab-flagged reportable run(s).",
                   location_id=gkey[2], analyte_name=gkey[5])
    if dropped:
        out = [r for r in out if id(r) not in dropped]
    return out
```

Update the module docstring: replace "MethodDilutionKey rerun disambiguation (IsReportable) is deferred to Step 3." with "MethodDilutionKey reruns resolve via the lab's IsReportable flag where present (Step 3); flagless groups keep every run."

- [ ] **Step 4: Run tests** — new tests PASS; full suite green (the 10 merge-gate regression tests and the wqx e2e must be untouched — their rows carry no IsReportable).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/canonical_read.py tests/envmon/<chosen test file>
git commit -m "feat(envmon): canonical_read prefers IsReportable-flagged runs among reruns"
```

---

### Task 11: ADR + docs + final gate

**Files:**
- Create: `docs/adr/00XX-edd-step3-equis-wmrd.md` (number vs origin/main tree AND every open PR's files at write time — ADR collisions have hit 5 times; do not trust the local max)
- Modify: `docs/adr/README.md` (index row after the highest existing)
- Create: `docs/adr/logs/2026-07-10-agent-decisions-equis-step3.md` (suffixed filename — a same-day log exists)
- Modify: `README.md` only if it states a test count (check `grep -n "20[0-9][0-9] passed\|test" README.md` for a drifted count; update if present)

- [ ] **Step 1: Write the ADR** — decisions D1–D12 condensed from the spec, with: the D5 no-pivot reversal and its real-file evidence, the xlrd dependency decision, the field-dup stream rule, `Env_QCResults` key composition, and the slice map (what's deferred where). Cross-reference ADR-0075/0079/0080 and the spec + plan paths.
- [ ] **Step 2: Write the agent-decisions log** — the autonomous calls: D5 reversal on real-file evidence, `batch_sheet` reuse over an `equis:` section, no new writer (generic append seam), `f"{value:g}"`-vs-raw limit formatting.
- [ ] **Step 3: Full suite + invariant check**

Run: `python -m pytest -q` → green (expect ≈ 2030 + ~45 new).
Then dispatch the `envmon-spec-checker` agent on the branch diff (state: main is read-only; ponytail active).

- [ ] **Step 4: Commit docs**

```bash
git add docs/adr/ docs/superpowers/plans/2026-07-10-edd-step3-equis-wmrd.md README.md
git commit -m "docs(adr): ADR-00XX — EDD Step 3 slice 1, EQuIS WMRD import + Env_QCResults"
```

- [ ] **Step 5: Push, PR, cold review**

Push the branch, open the PR (body: spec/plan links, real-file verification summary from Task 9 Step 6, suite count). Dispatch the `pr-reviewer` agent cold on the PR diff; fix findings; do NOT merge without explicit user authorization (standing rule).

---

## Self-Review (done at write time)

1. **Spec coverage:** D1 (Task 4 dep), D2 (Tasks 3/4), D3 (Tasks 3/7), D4 (Tasks 1/6), D5 (Tasks 6/9 — no-pivot pinned twice), D6/D7/D8 (Task 3), D9 (Task 10), D10 (Tasks 3/8), D11 (Task 3), D12 (no CLI task — zero change verified by e2e using `read_edd_file` directly; CLI dispatch is untouched code). Schema section → Task 1. Testing section → Tasks 3/6/9/10. Deferred list → ADR (Task 11).
2. **Placeholder scan:** ADR number is deliberately `00XX` (must be resolved against origin/main + open PRs at execution time — a hardcoded number here would cause the exact collision the repo keeps hitting). No other TBDs.
3. **Type consistency:** `transform_equis_sheets(sample_rows, result_rows, batch_rows, profile, qa)` consistent across Tasks 3/4/9; `normalize_qc_rows(rows, profile, site_id, batch_id, analyte_dictionary, qa)` consistent across Tasks 6/7/9; `QCResultRecord` field set pinned equal to `TABLE_FIELDS["Env_QCResults"]` by Task 1's parity test; `__equis_*` key names cross-checked between Task 3 code, Task 6/8 column maps, and Task 9 fixture.
