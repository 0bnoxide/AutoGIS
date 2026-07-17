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
    assert not any(r.category == "equis_unknown_batch_type"
                   for r in qa.records)


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
    assert any(r.category == "equis_unknown_batch_type"
               for r in qa.records)


def test_no_batch_columns_no_warn():
    out, qa = _run([_equis_sample()], [_equis_result()],
                   profile=_wmrd_profile(batch_sheet=""))
    assert out[0]["__equis_analysis_batch"] == ""
    assert not any(r.category == "equis_unknown_batch_type"
                   for r in qa.records)


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
    assert [r for r in qa.records if r.category == "equis_missing_batch"]


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
    assert not [r for r in qa.records if r.category == "equis_missing_test"]


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
    assert [r for r in qa.records if r.category == "equis_missing_test"]


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


def test_empty_test_sheet_still_warns_missing_test():
    # a present-but-empty EPAR4_TST_v1 sheet must not silently skip the
    # equis_missing_test WARN (the `if test_rows:` gate used to hide this).
    out, qa = _run_epar4([_equis_sample()], [_res()], [])
    assert len(out) == 1                          # row still imports
    missing = [r for r in qa.records if r.category == "equis_missing_test"]
    assert len(missing) == 1


def test_run_token_empty_dates_add_no_part():
    out, _ = _run_epar4([_equis_sample()],
                        [_res(analysis_date="", analysis_time="")],
                        [_tst(analysis_date="", analysis_time="")])
    assert not out[0]["__equis_method_dilution_key"].endswith("|")
