"""Env_QCResults schema + Step-3 AnalyticalResults additions (slice-1 spec)."""
import dataclasses

from autogis.core.envmon.gdb_schema import (
    TABLE_FIELDS, UNIQUE_KEYS, AnalyticalResultRecord, QCResultRecord,
    compute_unique_key,
)
from autogis.core.envmon.upgrade_schema import SCHEMA_VERSION


def test_schema_version_bumped():
    assert SCHEMA_VERSION == "2.5"


def test_env_qcresults_table_declared():
    names = [f[0] for f in TABLE_FIELDS["Env_QCResults"]]
    # paper-mapping finalized 33-column list, spot-checked head/tail + QC pillars
    assert names[0] == "ImportBatchID"
    assert names[-1] == "SourceRow"
    for col in ("QCType", "SampleID", "ParentSampleID", "AnalyteCanonicalName",
                "CASNumber", "MethodDilutionKey", "SpikeAmount",
                "PercentRecovery", "RPD", "RPDControlLimit"):
        assert col in names
    assert len(names) == 33


def test_env_qcresults_unique_key():
    assert UNIQUE_KEYS["Env_QCResults"] == [
        "SiteID", "Matrix", "AnalysisBatchID", "SampleID", "QCType",
        "AnalyteCanonicalName", "ResultFraction", "MethodID",
        "MethodDilutionKey"]


def test_qcresultrecord_matches_table_fields():
    record_fields = {f.name for f in dataclasses.fields(QCResultRecord)}
    schema_fields = {f[0] for f in TABLE_FIELDS["Env_QCResults"]}
    assert record_fields == schema_fields


def test_analytical_record_step3_fields_default_safe():
    fields = {f.name: f for f in dataclasses.fields(AnalyticalResultRecord)}
    assert fields["CASNumber"].default == ""
    assert fields["QuantitationLimit"].default is None
    assert fields["IsReportable"].default is None
    cols = {f[0] for f in TABLE_FIELDS["Env_AnalyticalResults"]}
    assert {"CASNumber", "QuantitationLimit", "IsReportable"} <= cols


def test_compute_unique_key_env_qcresults():
    rec = {"SiteID": "s1", "Matrix": "SOIL", "AnalysisBatchID": "438621",
           "SampleID": "B25-002AMT", "QCType": "MS",
           "AnalyteCanonicalName": "Lead", "ResultFraction": "Total",
           "MethodID": "E200.8", "MethodDilutionKey": "1"}
    key = compute_unique_key(rec, "Env_QCResults")
    assert key == ("S1", "SOIL", "438621", "B25-002AMT", "MS", "LEAD",
                   "TOTAL", "E200.8", "1")
