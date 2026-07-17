# tests/envmon/test_mining_e2e.py
"""End-to-end: mining .xlsx fixture -> read_edd_file -> split -> both
normalizers -> key distinctness. Loads the SHIPPED mining.yaml."""
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
           / "mining_edd_fixture.xlsx")
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "mining.yaml")


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


def test_stream_split_counts():
    _, results, qc, _ = _import()
    assert len(results) == 3      # M-001 Pb, M-002 As ND, FD-1 Pb
    assert len(qc) == 1           # LMS via the sample_type bridge


def test_keys_distinct_both_tables():
    _, results, qc, _ = _import()
    rkeys = {compute_unique_key(dataclasses.asdict(r),
                                "Env_AnalyticalResults") for r in results}
    qkeys = {compute_unique_key(dataclasses.asdict(r), "Env_QCResults")
             for r in qc}
    assert len(rkeys) == 3
    assert len(qkeys) == 1


def test_field_dup_qc_flagged_analytical():
    _, results, _, _ = _import()
    fd = next(r for r in results if r.SampleID == "FD-1")
    assert fd.QCType == "FIELD_DUP"


def test_ms_spike_fields_and_inline_analysis_batch():
    _, _, qc, _ = _import()
    ms = qc[0]
    assert ms.QCType == "MS"
    assert ms.PercentRecovery == 97.0
    assert ms.AnalysisBatchID == "AB-1"
    assert ms.ParentSampleID == "M-001"


def test_prep_method_and_date_propagate_on_analytical_row():
    # NOTE (brief deviation): AnalyticalResultRecord has no
    # PrepBatchID/AnalysisBatchID fields (batch ids are QC-only per
    # gdb_schema.py QCResultRecord) -- the R5 "PREP fills both ids" fix in
    # equis_reader._attach_inline_batch is a Env_QCResults key-safety
    # concern only. Assert the fields the analytical dataclass DOES carry
    # for M-001's PREP-typed inline batch: PrepMethodID/PrepDate.
    _, results, _, _ = _import()
    pb = next(r for r in results if r.SampleID == "M-001")
    assert pb.PrepMethodID == "E200.2"
    assert pb.PrepDate is not None


def test_nd_limits_converted():
    _, results, _, _ = _import()
    nd = next(r for r in results if r.SampleID == "M-002")
    assert nd.IsNonDetect == 1
    assert nd.DetectionLimit == 0.1         # 100 ug/L -> 0.1 mg/L
    assert nd.ReportingLimit == 0.5         # lower_reporting_limit routed
