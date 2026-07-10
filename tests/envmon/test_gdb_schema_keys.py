from __future__ import annotations

import datetime as dt
from dataclasses import asdict

from autogis.core.envmon.gdb_schema import (
    UNIQUE_KEYS, compute_unique_key, TABLE_SCHEMAS, AnalyticalResultRecord,
)


def _result_dict(**overrides) -> dict:
    d = {
        "SiteID": "S1", "Matrix": "GW", "LocationID": "MW-1",
        "SampleID": "MW-1-0626", "SampleDate": dt.date(2026, 6, 26),
        "AnalyteCanonicalName": "Benzene", "DepthIntervalText": "",
        "SourceCell": "",
    }
    d.update(overrides)
    return d


def test_compute_unique_key_matches_key_fields_order():
    key = compute_unique_key(_result_dict(), "Env_AnalyticalResults")
    assert len(key) == len(UNIQUE_KEYS["Env_AnalyticalResults"])


def test_compute_unique_key_normalizes_like_append():
    # str strip+upper, date -> YYYY-MM-DD string: identical rows re-imported
    # from differently-cased sources must collide.
    a = compute_unique_key(_result_dict(SampleID=" mw-1-0626 "),
                           "Env_AnalyticalResults")
    b = compute_unique_key(_result_dict(SampleID="MW-1-0626"),
                           "Env_AnalyticalResults")
    assert a == b
    assert "2026-06-26" in a


def test_compute_unique_key_missing_field_yields_none_part():
    # d.get(k) semantics preserved: absent key -> None passes through.
    d = _result_dict()
    del d["SourceCell"]
    key = compute_unique_key(d, "Env_AnalyticalResults")
    assert None in key


def test_record_to_row_is_gone():
    import autogis.core.envmon.gdb_schema as gs
    assert not hasattr(gs, "record_to_row")


_NEW_FIELDS = [
    "ResultFraction", "QCType", "MethodDilutionKey", "MethodID",
    "MethodName", "AnalysisDate", "LimitType", "LabName",
    "PrepMethodID", "PrepDate", "ResultBasis", "MethodSpeciation",
]


def _full_record(**overrides) -> AnalyticalResultRecord:
    base = dict(
        ImportBatchID="B1", SiteID="S1", Matrix="GW", LocationID="MW-1",
        SampleID="MW-1-0626", ParentSampleID="",
        SampleDate=dt.date(2026, 6, 26), DepthTop_ft=None,
        DepthBottom_ft=None, DepthIntervalText="", AnalyticalGroup="",
        MethodGroup="", AnalyteName="Benzene",
        AnalyteCanonicalName="Benzene", AnalyteAbbreviation="Benz",
        ResultRawText="0.5", ResultNumeric=0.5, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=None,
        ScreeningLevelSource="", ExceedsScreeningLevel=None,
        DisplayText="0.5", DisplayColorClass="", SourceWorkbook="w",
        SourceSheet="s", SourceRow=2, SourceColumn="", SourceCell="",
    )
    base.update(overrides)
    return AnalyticalResultRecord(**base)


def test_new_fields_default_empty_or_none():
    rec = _full_record()   # legacy construction: no new kwargs
    d = asdict(rec)
    for f in _NEW_FIELDS:
        assert d[f] in ("", None), f
    # key discriminators specifically must be "" (idempotency), never None
    for f in ("ResultFraction", "QCType", "MethodDilutionKey"):
        assert d[f] == "", f


def test_field_projection_round_trip_every_new_field():
    # A dataclass attr whose name mismatches TABLE_SCHEMAS silently projects
    # to None on insert — assert exact name parity, both directions.
    rec = _full_record(
        ResultFraction="Total", QCType="FIELD_DUP", MethodDilutionKey="D5",
        MethodID="EPA 8260", MethodName="VOCs by GC/MS",
        AnalysisDate=dt.date(2026, 6, 27), LimitType="MDL", LabName="Pace",
        PrepMethodID="5030B", PrepDate=dt.date(2026, 6, 26),
        ResultBasis="DRY", MethodSpeciation="as N",
    )
    d = asdict(rec)
    schema_names = [f[0] for f in TABLE_SCHEMAS["Env_AnalyticalResults"]]
    # exact parity: every schema column has a dataclass attr and vice versa
    assert set(d) == set(schema_names)
    # every populated new field survives schema-ordered row projection
    row = [d.get(f) for f in schema_names]
    projected = dict(zip(schema_names, row))
    for f in _NEW_FIELDS:
        assert projected[f] == d[f], f
