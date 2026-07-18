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
    # SAME sample (N-001), two analytes, analyzed on DIFFERENT dates -> the
    # batch join key (sample, method, fraction, col, test_type[, date]) does
    # NOT include analyte, so both rows compete for the SAME batch rows.
    # Without join_date (R6 reverted) the two ANALYSIS batch rows below
    # collapse onto one 5-col key and last-write-wins -- this is what makes
    # the ambiguity genuine (N-001 vs N-002 would already disambiguate on
    # sample_id alone, which doesn't exercise R6 at all).
    _res("N-001", "Lead", "7439-92-1", "12.4", adate="03/17/2025"),
    _res("N-001", "Copper", "7440-50-8", "3.2", adate="03/18/2025"),
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
    # two ANALYSIS batch rows for N-001, IDENTICAL except analysis_date --
    # the R6 case: without date in the join composite these collide.
    ["N-001", "E200.8", "03/17/2025", "T", "NA", "INITIAL",
     "ANALYSIS", "AB-1"],
    ["N-001", "E200.8", "03/18/2025", "T", "NA", "INITIAL",
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
