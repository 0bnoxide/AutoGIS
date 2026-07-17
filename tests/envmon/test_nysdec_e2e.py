# tests/envmon/test_nysdec_e2e.py
"""End-to-end: NYSDEC v5 .xlsx fixture -> read_edd_file -> split -> both
normalizers -> R6 date-extended batch join + case-insensitive types."""
import dataclasses
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector, SEV_ERROR
from autogis.core.envmon.edd_importer import (
    normalize_edd_rows, normalize_qc_rows, read_edd_file,
)
from autogis.core.envmon.edd_profile import (
    LabEDDProfile, validate_edd_profile,
)
from autogis.core.envmon.gdb_schema import compute_unique_key

FIXTURE = (Path(__file__).parent.parent / "fixtures"
           / "nysdec_edd_fixture.xlsx")
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "nysdec.yaml")


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


def test_profile_validates():
    qa = QACollector()
    validate_edd_profile(LabEDDProfile.load(PROFILE), qa)
    assert not [r for r in qa.records if r.severity == SEV_ERROR]


def test_stream_split_and_keys():
    _, results, qc, _ = _import()
    assert len(results) == 2
    assert len(qc) == 1
    rkeys = {compute_unique_key(dataclasses.asdict(r),
                                "Env_AnalyticalResults") for r in results}
    assert len(rkeys) == 2


def test_r6_date_extended_join_and_uppercase_types():
    # NOTE (brief deviation): AnalyticalResultRecord has no
    # PrepBatchID/AnalysisBatchID fields (batch ids are QC-only per
    # gdb_schema.py QCResultRecord), so the R6 join outcome for N-001/N-002
    # can't be asserted off the analytical rows directly. Verify at the
    # reader level instead: read_edd_file's raw rows carry the
    # __equis_prep_batch / __equis_analysis_batch synthesized columns
    # before normalize_edd_rows drops them, so we can confirm N-001 got
    # the uppercase-PREP batch (R5) and N-002 got the date-discriminated
    # ANALYSIS batch (R6) at the point they're actually attached. We also
    # confirm no missing-batch QA issue was raised for either sample.
    qa = QACollector()
    profile = LabEDDProfile.load(PROFILE)
    rows = read_edd_file(FIXTURE, profile, qa)
    data_rows = {r["sys_sample_code"]: r for r in rows
                 if r.get("__equis_stream") != "qc"}
    n1 = data_rows["N-001"]
    n2 = data_rows["N-002"]
    assert n1["__equis_prep_batch"] == "PB-1"        # uppercase PREP matched
    assert n1["__equis_analysis_batch"] == "AB-1"
    assert n2["__equis_analysis_batch"] == "AB-2"    # date-discriminated (R6)
    assert not [r for r in qa.records if r.category == "equis_missing_batch"]


def test_lab_blank_routed_qc_with_matrix_passthrough():
    _, _, qc, _ = _import()
    lb = qc[0]
    assert lb.QCType == "LAB_BLANK"
    assert lb.IsNonDetect == 1
    assert lb.AnalysisBatchID == "AB-1"


def test_matrix_mapped():
    samples, _, _, _ = _import()
    assert all(s.Matrix == "GW" for s in samples
               if s.SampleID.startswith("N-"))
