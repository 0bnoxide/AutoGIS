"""Env_QCResults schema + Step-3 AnalyticalResults additions (slice-1 spec)."""
import dataclasses

from autogis.core.envmon.gdb_schema import (
    TABLE_FIELDS, UNIQUE_KEYS, AnalyticalResultRecord, QCResultRecord,
    compute_unique_key,
)
from autogis.core.envmon.upgrade_schema import SCHEMA_VERSION


def test_schema_version_bumped():
    assert SCHEMA_VERSION == "2.8"


def test_screening_level_source_field_fits_config_sources():
    """Regression pin (ADR-0097 / F1).

    Env_AnalyticalResults.ScreeningLevelSource must hold every `source` string
    the importer can write from the canonical screening_levels.yaml. It was
    TEXT(64) while production sources are 128-162 chars, so real arcpy imports
    failed with 'Field length exceeded' — a write-time constraint this arcpy-free
    suite never saw. Assert the field length covers the longest configured source.
    """
    from pathlib import Path

    import yaml

    import autogis
    from autogis.core.envmon.gdb_schema import TABLE_SCHEMAS

    lengths = {f[0]: f[2] for f in TABLE_SCHEMAS["Env_AnalyticalResults"]}
    field_len = lengths["ScreeningLevelSource"]

    cfg = (Path(autogis.__file__).parent / "config" / "screening_levels"
           / "screening_levels.yaml")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    sources: list[str] = []

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "source" and isinstance(v, str):
                    sources.append(v)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for x in obj:
                _walk(x)

    _walk(data)
    longest = max((len(s) for s in sources), default=0)
    assert longest <= field_len, (
        f"ScreeningLevelSource is TEXT({field_len}) but the longest configured "
        f"source is {longest} chars; widen the field in gdb_schema.py")


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
