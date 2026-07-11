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


def test_run_edd_import_splits_qc_stream(monkeypatch, tmp_path):
    from autogis.core.envmon import edd_importer

    seen = {"appends": []}
    monkeypatch.setattr(edd_importer, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: None)
    monkeypatch.setattr(edd_importer, "create_edd_import_batch",
                        lambda *a, **k: "BATCH1")
    monkeypatch.setattr(
        edd_importer, "append_records_idempotent",
        lambda gdb, table, records, qa, batch: (
            seen["appends"].append((table, len(records))),
            (len(records), 0))[1])
    monkeypatch.setattr(edd_importer, "finalize_batch",
                        lambda gdb, batch, qa, counts, status:
                        seen.update(counts=counts))
    monkeypatch.setattr(edd_importer, "write_qa_to_gdb",
                        lambda *a, **k: None)

    field_row = {"sid": "S1", "loc": "MW-1", "dt": "01/02/2026", "mx": "GW",
                 "an": "Lead", "res": "1.2", "un": "ug/l", "q": "", "rl": ""}
    qc_row = dict(_qc_row())
    qc_row["loc"] = "MW-9"   # satisfy location_id so the leak assertion bites
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
