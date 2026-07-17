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
