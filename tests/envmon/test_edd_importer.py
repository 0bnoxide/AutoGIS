"""Tests for edd_importer.py — read_edd_file + normalize_edd_rows."""
from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon.edd_importer import read_edd_file, normalize_edd_rows
from autogis.core.envmon.edd_profile import LabEDDProfile

# ---------------------------------------------------------------------------
# Shared data
# ---------------------------------------------------------------------------

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "edd" / "testamerica_simple.csv"

ANALYTES = {
    "Benzene": {
        "aliases": ["benzene"],
        "abbreviation": "BNZ",
        "analytical_group": "VOC",
        "method_group": "EPA8260",
        "default_units_by_matrix": {"GW": "ug/L"},
    },
    "Toluene": {
        "aliases": ["toluene"],
        "abbreviation": "TOL",
        "analytical_group": "VOC",
        "method_group": "EPA8260",
    },
}

SCREENING = {
    "GW": {
        "Benzene": {"value": 1.0, "units": "ug/L", "source": "USEPA MCL"},
    }
}

_PROFILE_YAML = textwrap.dedent("""
    profile_id: test_lab
    lab_name: Test Lab
    format: flat_csv
    date_format: "%m/%d/%Y"
    encoding: utf-8
    columns:
      sample_id:       SysLocCode
      location_id:     SysLocCode
      event_date:      CollDate
      matrix:          Medium
      analyte:         Chemical
      result:          Result
      units:           Unit
      qualifier:       Qualifier
      reporting_limit: RL
      method:          AnalytMeth
      lab_sample_id:   LabID
    matrix_map:
      WS: GW
      SO: SOIL
    nondetect_qualifiers:
      - U
      - UJ
""").strip()


def _write_profile(tmp_path: Path) -> Path:
    p = tmp_path / "test_lab.yaml"
    p.write_text(_PROFILE_YAML, encoding="utf-8")
    return p


def _profile(tmp_path: Path) -> LabEDDProfile:
    return LabEDDProfile.load(_write_profile(tmp_path))


def _run(rows, tmp_path, *, event_date_override=None):
    """Helper: run normalize_edd_rows with standard fixtures."""
    profile = _profile(tmp_path)
    qa = QACollector()
    # Reset lookup cache so tests don't share state
    analyte_dict = dict(ANALYTES)
    samples, results = normalize_edd_rows(
        rows, profile,
        site_id="H281", batch_id="B001",
        analyte_dictionary=analyte_dict,
        screening_levels=SCREENING,
        qa=qa,
        event_date_override=event_date_override,
    )
    return samples, results, qa


def _rows_from_fixture(tmp_path: Path) -> list[dict]:
    profile = _profile(tmp_path)
    return read_edd_file(FIXTURE_CSV, profile)


# ---------------------------------------------------------------------------
# read_edd_file
# ---------------------------------------------------------------------------

def test_read_edd_file_returns_rows(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    assert len(rows) == 4
    assert "SysLocCode" in rows[0]


# ---------------------------------------------------------------------------
# normalize_edd_rows — qualifier and detection flags
# ---------------------------------------------------------------------------

def test_nondetect_qualifier_u(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    _, results, _ = _run(rows, tmp_path)
    # Row 0: Benzene MW-1 qualifier U
    r = next(x for x in results
             if x.LocationID == "MW-1" and x.AnalyteName == "Benzene")
    assert r.IsNonDetect == 1
    assert r.IsDetected == 0
    assert r.Qualifier == "U"


def test_detected_value(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    _, results, _ = _run(rows, tmp_path)
    # Row 1: Toluene MW-1, result 12.3
    r = next(x for x in results
             if x.LocationID == "MW-1" and x.AnalyteName == "Toluene")
    assert r.IsDetected == 1
    assert r.IsNonDetect == 0
    assert r.ResultNumeric == pytest.approx(12.3)


def test_blank_result_is_not_detected(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    _, results, _ = _run(rows, tmp_path)
    # Row 2: Benzene MW-2, blank result
    r = next(x for x in results
             if x.LocationID == "MW-2" and x.AnalyteName == "Benzene")
    assert r.IsDetected == 0
    assert r.ResultNumeric is None


# ---------------------------------------------------------------------------
# Sample deduplication
# ---------------------------------------------------------------------------

def test_sample_deduplication(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    samples, results, _ = _run(rows, tmp_path)
    # MW-1 appears in rows 0 and 1 (Benzene + Toluene) -> 1 SampleRecord
    mw1_samples = [s for s in samples if s.LocationID == "MW-1"]
    mw1_results = [r for r in results if r.LocationID == "MW-1"]
    assert len(mw1_samples) == 1
    assert len(mw1_results) == 2


# ---------------------------------------------------------------------------
# Matrix mapping
# ---------------------------------------------------------------------------

def test_matrix_mapping(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    samples, results, _ = _run(rows, tmp_path)
    # MW-3 has Medium="SO" -> Matrix=="SOIL"
    r = next(x for x in results if x.LocationID == "MW-3")
    assert r.Matrix == "SOIL"
    s = next(x for x in samples if x.LocationID == "MW-3")
    assert s.Matrix == "SOIL"


def test_unknown_matrix_emits_warning(tmp_path):
    profile = _profile(tmp_path)
    qa = QACollector()
    rows = [
        {"SysLocCode": "MW-9", "CollDate": "06/01/2026", "Medium": "XX",
         "LabID": "L-001", "Chemical": "Benzene", "Result": "1.0",
         "Qualifier": "", "RL": "0.5", "Unit": "ug/L", "AnalytMeth": "EPA 8260B"},
    ]
    normalize_edd_rows(rows, profile, site_id="H281", batch_id="B001",
                       analyte_dictionary=dict(ANALYTES),
                       screening_levels=SCREENING, qa=qa)
    warnings = [r for r in qa.records
                if r.severity == SEV_WARNING and "matrix" in r.message.lower()]
    assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# QA records
# ---------------------------------------------------------------------------

def test_unknown_analyte_emits_warning(tmp_path):
    profile = _profile(tmp_path)
    qa = QACollector()
    rows = [
        {"SysLocCode": "MW-9", "CollDate": "06/01/2026", "Medium": "WS",
         "LabID": "L-001", "Chemical": "Dibromochloromethane", "Result": "1.0",
         "Qualifier": "", "RL": "0.5", "Unit": "ug/L", "AnalytMeth": "EPA 8260B"},
    ]
    normalize_edd_rows(rows, profile, site_id="H281", batch_id="B001",
                       analyte_dictionary=dict(ANALYTES),
                       screening_levels=SCREENING, qa=qa)
    warnings = [r for r in qa.records
                if r.severity == SEV_WARNING and "analyte" in r.message.lower()]
    assert len(warnings) >= 1


def test_missing_required_column_emits_error(tmp_path):
    profile = _profile(tmp_path)
    qa = QACollector()
    # SysLocCode absent -> sample_id and location_id both None
    rows = [
        {"CollDate": "06/01/2026", "Medium": "WS",
         "LabID": "L-001", "Chemical": "Benzene", "Result": "1.0",
         "Qualifier": "", "RL": "0.5", "Unit": "ug/L", "AnalytMeth": "EPA 8260B"},
    ]
    samples, results = normalize_edd_rows(
        rows, profile, site_id="H281", batch_id="B001",
        analyte_dictionary=dict(ANALYTES),
        screening_levels=SCREENING, qa=qa,
    )[:2]
    assert len(samples) == 0
    errors = [r for r in qa.records if r.severity == SEV_ERROR]
    assert len(errors) >= 1


# ---------------------------------------------------------------------------
# Event date override
# ---------------------------------------------------------------------------

def test_event_date_override(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    override = date(2026, 3, 15)
    samples, results, _ = _run(rows, tmp_path, event_date_override=override)
    assert all(s.SampleDate == override for s in samples)
    assert all(r.SampleDate == override for r in results)


# ---------------------------------------------------------------------------
# Screening levels
# ---------------------------------------------------------------------------

def test_exceeds_screening_level_benzene_gw(tmp_path):
    rows = _rows_from_fixture(tmp_path)
    _, results, _ = _run(rows, tmp_path)

    # Toluene MW-1 has no screening level -> ExceedsScreeningLevel is None
    toluene = next(x for x in results
                   if x.LocationID == "MW-1" and x.AnalyteName == "Toluene")
    assert toluene.ExceedsScreeningLevel is None

    # Benzene MW-3 is SOIL matrix, no SL for SOIL -> None
    benz_soil = next(x for x in results
                     if x.LocationID == "MW-3" and x.AnalyteName == "Benzene")
    assert benz_soil.ExceedsScreeningLevel is None


# ---------------------------------------------------------------------------
# run_edd_import orchestrator
# ---------------------------------------------------------------------------

def test_run_edd_import_calls_lifecycle(tmp_path, monkeypatch):
    """Verify run_edd_import calls import_to_gdb lifecycle functions in order."""
    import autogis.core.envmon.edd_importer as mod

    calls = []

    def fake_create(gdb_path, edd_path, site_id, lab_name, profile_id, mode="append"):
        calls.append("create")
        return "BATCH-001"

    def fake_append(gdb_path, table_name, records, qa, batch_id):
        calls.append(f"append:{table_name}")
        return len(records), 0

    def fake_finalize(gdb_path, batch_id, qa, counts, status):
        calls.append("finalize")

    def fake_write_qa(gdb_path, qa, batch_id):
        calls.append("write_qa")

    def fake_schema(gdb_path, qa=None):
        calls.append("schema")

    monkeypatch.setattr(mod, "create_or_update_gdb_schema", fake_schema)
    monkeypatch.setattr(mod, "create_edd_import_batch", fake_create)
    monkeypatch.setattr(mod, "append_records_idempotent", fake_append)
    monkeypatch.setattr(mod, "finalize_batch", fake_finalize)
    monkeypatch.setattr(mod, "write_qa_to_gdb", fake_write_qa)

    profile = _profile(tmp_path)
    gdb = tmp_path / "test.gdb"

    batch_id = mod.run_edd_import(
        edd_path=FIXTURE_CSV,
        profile=profile,
        gdb_path=gdb,
        site_id="H281",
        analyte_dictionary=ANALYTES,
        screening_levels=SCREENING,
    )

    assert batch_id == "BATCH-001"
    assert calls[0] == "schema"
    assert calls[1] == "create"
    assert "append:Env_Samples" in calls
    assert "append:Env_AnalyticalResults" in calls
    assert "finalize" in calls
    assert "write_qa" in calls
    assert calls.index("finalize") > calls.index("append:Env_Samples")
    assert calls.index("finalize") > calls.index("append:Env_AnalyticalResults")


def test_run_edd_import_ensures_schema_first(tmp_path, monkeypatch):
    """run_edd_import must self-heal the GDB schema before anything else."""
    import autogis.core.envmon.edd_importer as mod

    calls = []

    monkeypatch.setattr(mod, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: calls.append("schema"))
    monkeypatch.setattr(mod, "create_edd_import_batch",
                        lambda *a, **k: (calls.append("batch"), "BATCH-001")[1])
    monkeypatch.setattr(mod, "append_records_idempotent",
                        lambda *a, **k: (calls.append("append"), (0, 0))[1])
    monkeypatch.setattr(mod, "finalize_batch", lambda *a, **k: calls.append("finalize"))
    monkeypatch.setattr(mod, "write_qa_to_gdb", lambda *a, **k: calls.append("write_qa"))

    profile = _profile(tmp_path)
    gdb = tmp_path / "test.gdb"

    batch_id = mod.run_edd_import(
        edd_path=FIXTURE_CSV,
        profile=profile,
        gdb_path=gdb,
        site_id="H281",
        analyte_dictionary=ANALYTES,
        screening_levels=SCREENING,
    )

    assert batch_id == "BATCH-001"
    assert calls[0] == "schema"
    assert "batch" in calls and "append" in calls


def test_run_edd_import_uses_caller_qa_collector(tmp_path, monkeypatch):
    """A caller-supplied QACollector must be the one used throughout (so the
    CLI can render/--report the same records that went to the GDB)."""
    import autogis.core.envmon.edd_importer as mod
    from autogis.core.common.qa import QACollector

    seen = {}
    monkeypatch.setattr(mod, "create_or_update_gdb_schema", lambda gdb, qa=None: None)
    monkeypatch.setattr(mod, "create_edd_import_batch", lambda *a, **k: "BATCH-001")
    monkeypatch.setattr(mod, "append_records_idempotent", lambda *a, **k: (0, 0))
    monkeypatch.setattr(mod, "finalize_batch", lambda *a, **k: None)
    monkeypatch.setattr(mod, "write_qa_to_gdb",
                        lambda gdb, qa, batch_id: seen.setdefault("qa", qa))

    mine = QACollector()
    mod.run_edd_import(
        edd_path=FIXTURE_CSV,
        profile=_profile(tmp_path),
        gdb_path=tmp_path / "test.gdb",
        site_id="H281",
        analyte_dictionary=ANALYTES,
        screening_levels=SCREENING,
        qa=mine,
    )
    assert seen["qa"] is mine


def _qa_persistence_writer(monkeypatch, *, late=None):
    """Execute real batch/QA persistence against only in-memory cursor effects."""
    import dataclasses
    from collections import defaultdict
    from types import SimpleNamespace
    from autogis.core.envmon import edd_importer as mod, import_to_gdb
    from autogis.core.envmon.gdb_schema import compute_unique_key
    tables, appends = defaultdict(list), []

    class Cursor:
        def __init__(self, table, fields):
            self.rows, self.fields = tables[Path(table).name], fields

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def insertRow(self, values):
            self.rows.append(dict(zip(self.fields, values)))

        def __iter__(self):
            for row in self.rows:
                self.current = row
                yield [row.get(field) for field in self.fields]

        def updateRow(self, values):
            self.current.update(zip(self.fields, values))

    def append(gdb, table, records, qa, batch):
        appends.append((batch, table, [compute_unique_key(dataclasses.asdict(r), table)
                                      for r in records]))
        if late and table == "Env_AnalyticalResults":
            qa.add(late, "current_append", "Synthetic writer diagnostic", import_batch_id=batch)
        return len(records), 0

    monkeypatch.setattr(mod, "create_or_update_gdb_schema", lambda *a: None)
    monkeypatch.setattr(mod, "append_records_idempotent", append)
    monkeypatch.setattr(import_to_gdb, "_arcpy", lambda: SimpleNamespace(
        da=SimpleNamespace(InsertCursor=Cursor, UpdateCursor=Cursor)))
    return tables, appends


@pytest.mark.parametrize("prior", ["equis_invalid_run_timestamp", "equis_test_key_collision",
                                   "ordinary_prior_error"])
@pytest.mark.parametrize("current", ["valid", "row_error", "late_error", "late_warning"])
def test_reused_qa_scopes_status_counts_and_persistence_to_current_import(
        tmp_path, monkeypatch, prior, current):
    import csv
    from autogis.core.envmon import edd_importer as mod
    tables, appends = _qa_persistence_writer(
        monkeypatch, late=SEV_ERROR if current == "late_error" else
        SEV_WARNING if current == "late_warning" else None)
    path = tmp_path / "input.csv"
    rows = [_BASE_ROW]
    if current == "row_error":
        rows.append(dict(_BASE_ROW, SysLocCode=""))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_BASE_ROW))
        writer.writeheader()
        writer.writerows(rows)
    qa = QACollector()
    old = qa.add(SEV_ERROR, prior, "Earlier import", import_batch_id="OLD")
    batch = mod.run_edd_import(path, _make_profile(_BASE_COLUMNS), tmp_path / "stub.gdb",
                              "SITE", ANALYTES, SCREENING, qa=qa)
    record = tables["Env_ImportBatch"][0]
    assert appends and record["AnalyticalRecordCount"] == 1
    assert record["QAStatus"] == ("ERROR" if current in {"row_error", "late_error"} else "PASS")
    current_records = qa.records[1:]
    assert record["ErrorCount"] == sum(r.severity == SEV_ERROR for r in current_records)
    assert record["WarningCount"] == sum(r.severity == SEV_WARNING for r in current_records)
    assert [r["Category"] for r in tables["Env_ImportQA"]] == [r.category for r in current_records]
    assert all(r["ImportBatchID"] == batch for r in tables["Env_ImportQA"])
    assert qa.records[0] is old and old.import_batch_id == "OLD"
    assert qa.has_blocking()  # The caller still owns the complete aggregate.


@pytest.mark.parametrize("bad_first", [True, False])
def test_sequential_equis_imports_keep_aggregate_qa_without_replaying_old_records(
        tmp_path, monkeypatch, bad_first):
    import openpyxl
    import autogis
    from autogis.core.envmon import edd_importer as mod
    tables, appends = _qa_persistence_writer(monkeypatch)
    profile = LabEDDProfile.load(Path(autogis.__file__).parent / "config/lab_profiles/epar4.yaml")
    qa = QACollector()
    snapshots = []
    for number, bad in enumerate([bad_first, not bad_first]):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        test = dict(sys_sample_code="S1", lab_anl_method_name="E200.8",
                    analysis_date="03/17/2025", analysis_time="09:14:17" if bad else "09:14",
                    total_or_dissolved="T", column_number="NA", test_type="INITIAL", dilution_factor="1")
        result = dict(test, chemical_name="Lead", result_value="1", result_unit="mg/L",
                      result_type_code="TRG", reportable_result="Yes", test_batch_id="AB1")
        sample = dict(sys_sample_code="S1", sys_loc_code="MW1", sample_matrix_code="GW",
                      sample_date="03/11/2025", sample_source="Field", sample_type_code="N")
        for title, row in [("EPAR4_FSample_v1", sample), ("EPAR4_TST_v1", test),
                           ("EPAR4_RES_v1", result)]:
            sheet = wb.create_sheet(title)
            sheet.append(list(row))
            sheet.append(list(row.values()))
        path = tmp_path / f"input-{number}.xlsx"
        wb.save(path)
        wb.close()
        before, written = list(qa.records), len(tables["Env_ImportQA"])
        batch = mod.run_edd_import(path, profile, tmp_path / "stub.gdb", "SITE", {}, {}, qa=qa)
        record = tables["Env_ImportBatch"][-1]
        new = qa.records[len(before):]
        assert all(a is b for a, b in zip(before, qa.records))
        assert [r["Category"] for r in tables["Env_ImportQA"][written:]] == [r.category for r in new]
        assert all(r["ImportBatchID"] == batch for r in tables["Env_ImportQA"][written:])
        assert record["ErrorCount"] == sum(r.severity == SEV_ERROR for r in new)
        assert record["QAStatus"] == ("ERROR" if bad else "PASS")
        calls = [a for a in appends if a[0] == batch]
        assert bool(calls) == (not bad)
        if not bad:
            analytical = next(a[2] for a in calls if a[1] == "Env_AnalyticalResults")
            assert analytical == [("SITE", "GW", "MW1", "S1", "2025-03-11", "LEAD", "",
                                   "EQUIS_XLS", "", "T", "", "1|INITIAL|E200.8|03/17/2025@09:14")]
        snapshots.append(new)
    assert qa.records == snapshots[0] + snapshots[1]
    assert qa.has_blocking()


# ---------------------------------------------------------------------------
# Step-1 canonical expansion (ADR-0075) — 12 new optional fields
# ---------------------------------------------------------------------------

_BASE_COLUMNS = {
    "sample_id": "SysLocCode", "location_id": "SysLocCode",
    "event_date": "CollDate", "matrix": "Medium", "analyte": "Chemical",
    "result": "Result", "units": "Unit", "qualifier": "Qualifier",
    "reporting_limit": "RL",
}

_BASE_ROW = {
    "SysLocCode": "MW-1", "CollDate": "06/26/2026", "Medium": "GW",
    "Chemical": "Benzene", "Result": "0.5", "Unit": "ug/L",
    "Qualifier": "", "RL": "",
}


def _make_profile(columns: dict, value_maps: dict | None = None) -> LabEDDProfile:
    return LabEDDProfile(
        profile_id="test_lab", lab_name="Test Lab", format="flat_csv",
        date_format="%m/%d/%Y", encoding="utf-8", columns=columns,
        matrix_map={}, nondetect_qualifiers=["U", "UJ"],
        value_maps=value_maps or {},
    )


def _normalize(rows, profile):
    qa = QACollector()
    return normalize_edd_rows(
        rows, profile, site_id="S1", batch_id="B1",
        analyte_dictionary=dict(ANALYTES), screening_levels=SCREENING, qa=qa,
    )


def test_normalize_edd_rows_populates_new_fields():
    profile = _make_profile(
        columns={
            **_BASE_COLUMNS,
            "result_fraction": "Fraction", "qc_type": "QC",
            "dilution_factor": "Dil", "method": "Method",
            "method_name": "MethodName", "analysis_date": "AnalDate",
            "limit_type": "LimType", "lab_name": "Lab",
            "prep_method": "PrepMeth", "prep_date": "PrepDate",
            "result_basis": "Basis", "method_speciation": "Speciation",
        },
        value_maps={"result_fraction": {"T": "Total"},
                    "qc_type": {"TB": "TRIP_BLANK"}},
    )
    row = {**_BASE_ROW, "Fraction": "T", "QC": "TB", "Dil": "5",
           "Method": "EPA 8260", "MethodName": "VOCs by GC/MS",
           "AnalDate": "06/27/2026", "LimType": "MDL", "Lab": "Pace",
           "PrepMeth": "5030B", "PrepDate": "06/26/2026", "Basis": "DRY",
           "Speciation": "as N"}
    _, results = _normalize([row], profile)
    r = results[0]
    assert r.ResultFraction == "Total"          # value-mapped
    assert r.QCType == "TRIP_BLANK"             # value-mapped
    assert r.MethodDilutionKey == "5"
    assert r.MethodID == "EPA 8260"
    assert r.MethodName == "VOCs by GC/MS"
    assert r.AnalysisDate is not None
    assert r.LimitType == "MDL"
    assert r.LabName == "Pace"
    assert r.PrepMethodID == "5030B"
    assert r.PrepDate is not None
    assert r.ResultBasis == "DRY"
    assert r.MethodSpeciation == "as N"


def test_normalize_edd_rows_unmapped_new_columns_default_empty():
    # A profile with NO new column mappings (today's TestAmerica shape)
    # must produce "" discriminators / None dates — bit-identical dedup.
    profile = _make_profile(columns=_BASE_COLUMNS)
    _, results = _normalize([dict(_BASE_ROW)], profile)
    r = results[0]
    assert (r.ResultFraction, r.QCType, r.MethodDilutionKey) == ("", "", "")
    assert r.AnalysisDate is None and r.PrepDate is None


# ---------------------------------------------------------------------------
# Step-3 EQuIS additions — cas_number, quantitation_limit, is_reportable
# ---------------------------------------------------------------------------

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
