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
    # surrogate on a FIELD sample -> QC stream. qc_spike_recovery (97) is
    # deliberately distinct from result_value (96): the real WMRD export
    # (verified 2026-07-10) populates both, and they are NOT the same value
    # (different columns/scales) — PercentRecovery must read qc_spike_recovery,
    # not ResultNumeric.
    _res("S-001", "8081", "Decachlorobiphenyl", "2051-24-3", "96",
         rtype="SUR", unit="% recovery", lunit="% recovery",
         mdl="", rl="", ql="", spike=("", "", "", "97")),
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
