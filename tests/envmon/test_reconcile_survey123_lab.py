import csv
from pathlib import Path
import pytest
from autogis.core.envmon.reconcile_survey123_lab import (
    Survey123Sample, LabSample, reconcile_field_lab,
    reconcile_to_qa, load_survey123_csv,
)

_FIELD = [Survey123Sample("H281-MW01-20260615-GW", "MW-01", "2026-06-15", "GW")]
_LAB_MATCH = [LabSample("H281-MW01-20260615-GW", "MW-01", "2026-06-15", "GW", 10)]
_LAB_FUZZY = [LabSample("H281-MW01-20260615GW", "MW-01", "2026-06-15", "GW", 10)]  # no dash
_LAB_DATE_MISMATCH = [LabSample("H281-MW01-20260615-GW", "MW-01", "2026-06-16", "GW", 10)]
_LAB_MATRIX_MISMATCH = [LabSample("H281-MW01-20260615-GW", "MW-01", "2026-06-15", "SOIL", 10)]
_LAB_NO_MATCH = [LabSample("H281-MW99-20260615-GW", "MW-99", "2026-06-15", "GW", 10)]
_LAB_TRULY_NO_MATCH = [LabSample("UNRELATED-ZZZZZ-99991231-AIR", "ZZ-99", "1999-12-31", "AIR", 0)]


def test_exact_match_one_pair():
    r = reconcile_field_lab(_FIELD, _LAB_MATCH)
    assert len(r.matched) == 1
    assert r.field_only == []
    assert r.lab_only == []


def test_fuzzy_match_flags_sample_id_mismatch():
    r = reconcile_field_lab(_FIELD, _LAB_FUZZY, threshold=0.8)
    assert len(r.matched) == 1
    assert any("sample_id_mismatch" in f for f in r.flags)


def test_date_mismatch_flagged():
    r = reconcile_field_lab(_FIELD, _LAB_DATE_MISMATCH)
    assert any("date_mismatch" in f for f in r.flags)


def test_matrix_mismatch_qa_error():
    r = reconcile_field_lab(_FIELD, _LAB_MATRIX_MISMATCH)
    qa = reconcile_to_qa(r)
    assert any(rec.category == "matrix_mismatch" for rec in qa.records)


def test_field_only_sample():
    r = reconcile_field_lab(_FIELD, _LAB_TRULY_NO_MATCH)
    assert len(r.field_only) == 1
    assert r.matched == []


def test_lab_only_sample():
    r = reconcile_field_lab([], _LAB_MATCH)
    assert len(r.lab_only) == 1


def test_reconcile_to_qa_field_only_warning():
    r = reconcile_field_lab(_FIELD, _LAB_TRULY_NO_MATCH)
    qa = reconcile_to_qa(r)
    assert any(rec.category == "field_only_sample" for rec in qa.records)


def test_fuzzy_match_flags_location_mismatch():
    r = reconcile_field_lab(_FIELD, _LAB_NO_MATCH, threshold=0.85)
    assert len(r.matched) == 1
    assert any("location_mismatch" in f for f in r.flags)


def test_load_survey123_csv(tmp_path):
    p = tmp_path / "s123.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["SampleID","LocationID","SamplingDate","Matrix","SampledBy"])
        w.writeheader()
        w.writerow({"SampleID": "H281-MW01-20260615-GW", "LocationID": "MW-01",
                    "SamplingDate": "2026-06-15", "Matrix": "GW", "SampledBy": "Alice"})
    samples = load_survey123_csv(p)
    assert len(samples) == 1
    assert samples[0].location_id == "MW-01"


def test_reconcile_survey123_lab_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "reconcile-survey123-lab" in result.output
