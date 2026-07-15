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
    assert diluted.MethodDilutionKey == "5|DILUTION|Dry|E200.8"  # ADR-0084 §1


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
    # Real WMRD export (verified 2026-07-10) populates qc_spike_recovery on
    # SUR rows with a value distinct from result_value — PercentRecovery
    # must read qc_spike_recovery, not ResultNumeric (tightened per the
    # brief's fixture-note once the real file confirmed the convention).
    _, _, qc, _ = _import()
    sur = next(r for r in qc if r.QCType == "SURROGATE")
    assert sur.SampleID == "S-001"
    assert sur.ResultNumeric == 96.0
    assert sur.PercentRecovery == 97.0


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
