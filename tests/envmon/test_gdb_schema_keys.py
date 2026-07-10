from __future__ import annotations

import datetime as dt
import textwrap
from dataclasses import asdict
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Task 5 — frozen 11-component key + distinctness + backward compat
# ---------------------------------------------------------------------------

def test_unique_key_is_the_frozen_11():
    assert UNIQUE_KEYS["Env_AnalyticalResults"] == [
        "SiteID", "Matrix", "LocationID", "SampleID", "SampleDate",
        "AnalyteCanonicalName", "DepthIntervalText", "SourceCell",
        "ResultFraction", "QCType", "MethodDilutionKey",
    ]


def _key(**ov):
    d = _result_dict(ResultFraction="", QCType="", MethodDilutionKey="")
    d.update(ov)
    return compute_unique_key(d, "Env_AnalyticalResults")


def test_fraction_pair_is_distinct():
    # WQX Total vs Dissolved of the same sample/analyte — the collision that
    # motivated this whole spec — must produce distinct keys.
    assert _key(ResultFraction="Total") != _key(ResultFraction="Dissolved")


def test_qc_flagged_row_distinct_from_parent():
    assert _key(QCType="") != _key(QCType="FIELD_DUP")


def test_dilution_rerun_distinct():
    assert _key(MethodDilutionKey="") != _key(MethodDilutionKey="D5")


def test_legacy_shape_key_unchanged():
    # Records in today's shape (discriminators absent -> defaulted "") must
    # produce the OLD 8-part key extended by three "" parts — same relative
    # uniqueness, so re-imports of pre-2.2 data still dedup identically.
    legacy = compute_unique_key(_result_dict(), "Env_AnalyticalResults")
    explicit = _key()
    # _result_dict has no discriminator keys -> None; records always carry ""
    assert explicit[:8] == legacy[:8]
    assert explicit[8:] == ("", "", "")


_TA_PROFILE_YAML = textwrap.dedent("""
    profile_id: test_lab
    lab_name: Test Lab
    format: flat_csv
    date_format: "%m/%d/%Y"
    encoding: utf-8
    columns:
      sample_id:       SysLocCode
      location_id:     SysLocCode
      event_date:      CollDate
      matrix:          Medium
      analyte:         Chemical
      result:          Result
      units:           Unit
      qualifier:       Qualifier
      reporting_limit: RL
      method:          AnalytMeth
      lab_sample_id:   LabID
    matrix_map:
      WS: GW
      SO: SOIL
    nondetect_qualifiers:
      - U
      - UJ
""").strip()

_TA_FIXTURE_CSV = (Path(__file__).parent / "fixtures" / "edd"
                   / "testamerica_simple.csv")

_TA_ANALYTES = {
    "Benzene": {
        "aliases": ["benzene"],
        "abbreviation": "BNZ",
        "analytical_group": "VOC",
        "method_group": "EPA8260",
        "default_units_by_matrix": {"GW": "ug/L"},
    },
    "Toluene": {
        "aliases": ["toluene"],
        "abbreviation": "TOL",
        "analytical_group": "VOC",
        "method_group": "EPA8260",
    },
}

_TA_SCREENING = {
    "GW": {
        "Benzene": {"value": 1.0, "units": "ug/L", "source": "USEPA MCL"},
    }
}


def _normalize_testamerica_fixture(tmp_path):
    # Reuse the exact fixture-loading pattern established in
    # tests/envmon/test_edd_importer.py (same profile shape, same CSV,
    # same analyte/screening fixtures).
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.edd_importer import read_edd_file, normalize_edd_rows
    from autogis.core.envmon.edd_profile import LabEDDProfile

    profile_path = tmp_path / "test_lab.yaml"
    profile_path.write_text(_TA_PROFILE_YAML, encoding="utf-8")
    profile = LabEDDProfile.load(profile_path)

    rows = read_edd_file(_TA_FIXTURE_CSV, profile)
    qa = QACollector()
    samples, results = normalize_edd_rows(
        rows, profile,
        site_id="H281", batch_id="B001",
        analyte_dictionary=dict(_TA_ANALYTES),
        screening_levels=_TA_SCREENING,
        qa=qa,
    )
    return samples, results


def test_backward_compat_testamerica_fixture_dedup_identical(tmp_path):
    # Run the existing TestAmerica EDD fixture through the real normalizer
    # and the widened key: every record must carry "" discriminators, and
    # distinct-key count must equal the record count (no new collisions,
    # no new splits).
    from dataclasses import asdict as _as

    samples, results = _normalize_testamerica_fixture(tmp_path)
    keys = [compute_unique_key(_as(r), "Env_AnalyticalResults")
            for r in results]
    assert len(set(keys)) == len(keys)
    assert all(k[8:] == ("", "", "") for k in keys)
