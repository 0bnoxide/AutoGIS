import csv
import re
from pathlib import Path
from autogis.core.envmon.normalize_survey123 import (
    Survey123Field, normalize_survey123_submission,
    load_survey123_csv_submissions,
)
from autogis.core.common.qa import QACollector

_PAYLOAD = {
    "WellID": "MW-01",
    "SamplingDate": "2026-06-15",
    "Matrix": "GW",
    "SampledBy": "Alice",
    "COCNumber": "H281-001",
    "DepthToWater_ft": 12.5,
    "Notes": "",
}


def test_minimal_payload_returns_water_level():
    qa = QACollector()
    wl, samp = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert len(wl) == 1
    assert wl[0]["LocationID"] == "MW-01"
    assert wl[0]["DTW_ft"] == 12.5


def test_minimal_payload_returns_sample_record():
    qa = QACollector()
    wl, samp = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert len(samp) == 1
    assert samp[0]["Matrix"] == "GW"


def test_missing_well_id_qa_error():
    qa = QACollector()
    bad = {k: v for k, v in _PAYLOAD.items() if k != "WellID"}
    normalize_survey123_submission(bad, "H281", "B1", qa)
    assert any(r.category == "missing_required_field" for r in qa.records)


def test_missing_dtw_omits_water_level():
    qa = QACollector()
    no_dtw = {k: v for k, v in _PAYLOAD.items() if k != "DepthToWater_ft"}
    wl, samp = normalize_survey123_submission(no_dtw, "H281", "B1", qa)
    assert wl == []


def test_csv_batch_two_rows(tmp_path):
    p = tmp_path / "s123.csv"
    rows = [
        {"WellID": "MW-01", "SamplingDate": "2026-06-15", "Matrix": "GW",
         "SampledBy": "Alice", "COCNumber": "H281-001", "DepthToWater_ft": "12.5", "Notes": ""},
        {"WellID": "MW-02", "SamplingDate": "2026-06-15", "Matrix": "GW",
         "SampledBy": "Bob", "COCNumber": "H281-001", "DepthToWater_ft": "8.3", "Notes": ""},
    ]
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    qa = QACollector()
    wl, samp = load_survey123_csv_submissions(p, "H281", "B1", qa)
    assert len(wl) == 2
    assert len(samp) == 2


def test_custom_field_map():
    qa = QACollector()
    payload = {"Well": "MW-01", "Date": "2026-06-15", "Type": "GW",
               "Crew": "Alice", "COC": "H281-001", "DTW": 10.0, "Notes": ""}
    fm = Survey123Field(well_id_field="Well", sampling_date_field="Date",
                        matrix_field="Type", sampled_by_field="Crew",
                        coc_number_field="COC", dtw_field="DTW")
    wl, samp = normalize_survey123_submission(payload, "H281", "B1", qa, field_map=fm)
    assert len(wl) == 1


def test_invalid_date_warns():
    qa = QACollector()
    bad_date = {**_PAYLOAD, "SamplingDate": "not-a-date"}
    normalize_survey123_submission(bad_date, "H281", "B1", qa)
    assert any(r.category == "invalid_date" for r in qa.records)


def test_missing_or_invalid_date_emits_error_and_unique_nodate_sample_id():
    qa1 = QACollector()
    _, samp1 = normalize_survey123_submission(
        {**_PAYLOAD, "SamplingDate": "not-a-date"}, "H281", "B1", qa1)
    qa2 = QACollector()
    _, samp2 = normalize_survey123_submission(
        {**_PAYLOAD, "SamplingDate": ""}, "H281", "B2", qa2)

    assert any(r.severity == "ERROR" and r.category == "invalid_date" for r in qa1.records)
    assert any(r.severity == "ERROR" and r.category == "invalid_date" for r in qa2.records)
    assert re.fullmatch(r"MW-01-NODATE-[0-9A-F]{6}-GW", samp1[0]["SampleID"])
    assert re.fullmatch(r"MW-01-NODATE-[0-9A-F]{6}-GW", samp2[0]["SampleID"])
    assert samp1[0]["SampleID"] != samp2[0]["SampleID"]


def test_happy_path_sample_id_pinned():
    qa = QACollector()
    _, samp = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert samp[0]["SampleID"] == "MW-01-20260615-GW"


def test_field_dup_yes_appends_fd_suffix():
    qa = QACollector()
    _, samp = normalize_survey123_submission(
        {**_PAYLOAD, "IsFieldDup": "yes"}, "H281", "B1", qa)
    assert samp[0]["SampleID"] == "MW-01-20260615-GW-FD"


def test_field_dup_absent_or_no_is_primary():
    qa = QACollector()
    _, s1 = normalize_survey123_submission({**_PAYLOAD, "IsFieldDup": "no"},
                                           "H281", "B1", qa)
    _, s2 = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert s1[0]["SampleID"] == s2[0]["SampleID"] == "MW-01-20260615-GW"


def test_route_survey123_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "route-survey123" in result.output


def test_route_survey123_guard_without_arcpy(tmp_path):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    csv = tmp_path / "s.csv"
    csv.write_text("WellID,SamplingDate,Matrix,SampledBy,COCNumber,DepthToWater_ft,Notes\n")
    result = CliRunner().invoke(
        autogis,
        ["envmon", "route-survey123", str(csv), "--site", "H281", "--gdb", str(tmp_path / "test.gdb")],
    )
    assert result.exit_code != 0


def test_route_survey123_json_flag_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "route-survey123", "--help"])
    assert "--format" in result.output
    assert "json" in result.output
