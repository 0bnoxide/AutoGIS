# tests/envmon/test_epar4_e2e.py
"""End-to-end: epar4 .xlsx fixture -> read_edd_file -> split -> both
normalizers -> key distinctness incl. the R9 reanalysis pair."""
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
           / "epar4_edd_fixture.xlsx")
PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "epar4.yaml")


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
    assert len(results) == 3      # Pb initial + Pb reanalysis + As
    assert len(qc) == 1           # LCS


def test_reanalysis_pair_keys_distinct():
    # R9: same sample/analyte/fraction, differing only by analysis_time
    _, results, _, _ = _import()
    lead = [r for r in results if r.AnalyteName == "Lead"]
    assert len(lead) == 2
    keys = {compute_unique_key(dataclasses.asdict(r),
                               "Env_AnalyticalResults") for r in lead}
    assert len(keys) == 2
    tokens = {r.MethodDilutionKey.rsplit("|", 1)[-1] for r in lead}
    assert tokens == {"03/17/2025@10:00", "03/17/2025@14:30"}


def test_test_sheet_fields_merged():
    # dilution/basis/prep live on TST; the join brought them across
    _, results, _, _ = _import()
    pb = next(r for r in results if r.AnalyteName == "Lead"
              and r.IsReportable == 1)
    assert pb.PrepMethodID == "E200.2"      # via lab_prep_method_name alias


def test_missing_test_entry_warns_but_imports():
    _, results, _, qa = _import()
    assert any(r.AnalyteName == "Arsenic" for r in results)
    assert [r for r in qa.records if r.category == "equis_missing_test"]


def test_lcs_qc_with_prep_typed_inline_batch():
    _, _, qc, _ = _import()
    lcs = qc[0]
    assert lcs.QCType == "LCS"
    assert lcs.PercentRecovery == 96.0
    assert lcs.AnalysisBatchID == "PB-1"    # R5 key-safety fill
    assert lcs.PrepBatchID == "PB-1"
