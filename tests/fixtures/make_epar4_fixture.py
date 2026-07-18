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
    _tst("E-001", "14:30"),
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
         reportable="No"),
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
