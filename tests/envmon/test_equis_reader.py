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
    # Method folds into the analytical MethodDilutionKey recipe (ADR-0084 §1);
    # NA column drops out, method (E200.8) rides last.
    rows, _ = _run([_sample()], [_result(dilution_factor="5",
                                         test_type="DILUTION",
                                         column_number="NA", basis="Dry")], [])
    assert rows[0]["__equis_method_dilution_key"] == "5|DILUTION|Dry|E200.8"


def test_method_folds_into_analytical_key_not_qc():
    # ADR-0084 §1: two rows identical but for method must key distinctly on
    # the analytical stream (MethodID is not an Env_AnalyticalResults key
    # part). On the QC stream the method is omitted — MethodID is already a
    # frozen Env_QCResults key part there.
    a1 = _result(lab_anl_method_name="8015")
    a2 = _result(lab_anl_method_name="8015M")
    rows, _ = _run([_sample()], [a1, a2], [])
    assert (rows[0]["__equis_method_dilution_key"]
            != rows[1]["__equis_method_dilution_key"])
    qc, _ = _run([_sample(sample_source="LAB", sample_type_code="QC-LCS",
                          sample_matrix_code="SQ-CONTROL")],
                 [_result(lab_anl_method_name="8015")], [])
    assert "8015" not in qc[0]["__equis_method_dilution_key"]


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
