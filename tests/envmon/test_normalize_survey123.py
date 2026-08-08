import csv
import dataclasses
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    # Schema field names, not invented ones: this dict goes straight into
    # Env_WaterLevels, which has no DTW_ft column (#457).
    assert wl[0]["DepthToWater_ft"] == 12.5
    assert wl[0]["EventDate"] is not None


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


def test_field_dup_flag_appends_fd_suffix():
    qa = QACollector()
    _, samp = normalize_survey123_submission(
        {**_PAYLOAD, "QAFlags": "field_dup"}, "H281", "B1", qa)
    assert samp[0]["SampleID"] == "MW-01-20260615-GW-FD"


def test_two_field_duplicates_get_distinct_a_b_ids():
    ids = []
    for flag in ("field_dup_a", "field_dup_b"):
        _, samples = normalize_survey123_submission(
            {**_PAYLOAD, "QAFlags": flag}, "H281", "B1", QACollector())
        ids.append(samples[0]["SampleID"])

    assert ids == [
        "MW-01-20260615-GW-FD-A",
        "MW-01-20260615-GW-FD-B",
    ]


def test_multiple_field_duplicate_codes_are_rejected():
    qa = QACollector()
    _, samples = normalize_survey123_submission(
        {**_PAYLOAD, "QAFlags": "field_dup_a field_dup_b"},
        "H281", "B1", qa)

    assert samples == []
    assert any(r.severity == "ERROR"
               and r.category == "ambiguous_field_duplicate_code"
               for r in qa.records)


@pytest.mark.parametrize("raw", [
    "field_dup",                      # sole flag
    "turbid field_dup",               # space-delimited (XLSForm export)
    "turbid,field_dup",               # comma-delimited (feature service)
    "FIELD_DUP",                      # case-insensitive
    ["field_dup"],                    # JSON payload carrying a real list
    ["turbid", "field_dup"],          # str() of this matches nothing
    ("turbid", "field_dup"),
])
def test_field_dup_recognized_in_multi_select_shapes(raw):
    qa = QACollector()
    _, samp = normalize_survey123_submission({**_PAYLOAD, "QAFlags": raw},
                                             "H281", "B1", qa)
    assert samp[0]["SampleID"].endswith("-FD")


def test_field_dup_absent_or_other_flag_is_primary():
    qa = QACollector()
    _, s1 = normalize_survey123_submission({**_PAYLOAD, "QAFlags": "turbid"},
                                           "H281", "B1", qa)
    _, s2 = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert s1[0]["SampleID"] == s2[0]["SampleID"] == "MW-01-20260615-GW"


def test_field_duplicate_carries_the_metadata_rpd_pairing_reads():
    """evaluate_duplicate_rpd pairs on IsDuplicate 0/1 + ParentSampleID;
    NULLs there make the record neither parent nor duplicate and skip RPD."""
    qa = QACollector()
    _, dup = normalize_survey123_submission({**_PAYLOAD, "QAFlags": "field_dup"},
                                            "H281", "B1", qa)
    _, primary = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)

    assert dup[0]["IsDuplicate"] == 1
    assert dup[0]["DuplicateType"] == "FIELD_DUP"
    assert dup[0]["ParentSampleID"] == primary[0]["SampleID"]
    # the primary must be flagged too, or parent_map never contains it
    assert primary[0]["IsDuplicate"] == 0
    assert primary[0]["DuplicateType"] == ""
    assert primary[0]["ParentSampleID"] == ""


def test_normalized_duplicate_pairs_under_evaluate_duplicate_rpd():
    """End-to-end: the dicts this module emits actually pair downstream."""
    from autogis.core.envmon.evaluate_rpd_qa import evaluate_duplicate_rpd
    from autogis.core.envmon.gdb_schema import (AnalyticalResultRecord,
                                                SampleRecord)

    qa = QACollector()
    _, dup = normalize_survey123_submission({**_PAYLOAD, "QAFlags": "field_dup"},
                                            "H281", "B1", qa)
    _, primary = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)

    def blank(cls, **over):
        """*cls* with every required field blank, then overrides applied."""
        vals = {f.name: "" for f in dataclasses.fields(cls)
                if f.default is dataclasses.MISSING
                and f.default_factory is dataclasses.MISSING}
        vals.update(over)
        return cls(**vals)

    def as_record(d):
        names = {f.name for f in dataclasses.fields(SampleRecord)}
        return blank(SampleRecord,
                     **{k: v for k, v in d.items() if k in names})

    samples = [as_record(primary[0]), as_record(dup[0])]

    def result(sample_id, value):
        return blank(AnalyticalResultRecord, SampleID=sample_id,
                     AnalyteName="Benzene", ResultRawText=str(value),
                     ResultNumeric=value, IsDetected=1)

    records = evaluate_duplicate_rpd(
        samples,
        [result(samples[0].SampleID, 10.0), result(samples[1].SampleID, 12.0)],
        "H281", "B1", QACollector())

    assert len(records) == 1
    assert records[0].RPDStatus == "CALCULATED"
    assert records[0].RPDValue == pytest.approx(18.1818, rel=1e-3)


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


def test_route_rejects_ambiguous_duplicate_before_partial_insert(
        tmp_path, monkeypatch):
    from click.testing import CliRunner
    from autogis.adapters import cli as cli_mod
    from autogis.core.envmon import import_to_gdb
    from autogis.runtime import sessions

    payload = tmp_path / "submission.json"
    payload.write_text(json.dumps({
        **_PAYLOAD,
        "QAFlags": "field_dup_a field_dup_b",
    }), encoding="utf-8")
    batch_rows = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def insertRow(self, row):
            batch_rows.append(row)

    outcomes = []
    monkeypatch.setattr(cli_mod, "_guard", lambda tool: None)
    monkeypatch.setattr(
        sessions, "arcpy_env",
        lambda: SimpleNamespace(
            da=SimpleNamespace(InsertCursor=lambda *a: Cursor())))
    monkeypatch.setattr(
        import_to_gdb, "append_records_idempotent",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("normalization ERROR reached insertion")))
    monkeypatch.setattr(
        import_to_gdb, "finalize_batch",
        lambda *a, **k: outcomes.append(a[-1]))
    monkeypatch.setattr(import_to_gdb, "write_qa_to_gdb",
                        lambda *a, **k: 0)

    result = CliRunner().invoke(
        cli_mod.autogis,
        ["envmon", "route-survey123", str(payload),
         "--site", "H281", "--gdb", str(tmp_path / "test.gdb"),
         "--format", "json"],
    )

    assert result.exit_code != 0
    assert batch_rows
    assert outcomes == ["BLOCKED_BY_QA"]


def test_route_late_insert_error_finalizes_blocked(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from autogis.adapters import cli as cli_mod
    from autogis.core.envmon import import_to_gdb
    from autogis.runtime import sessions

    payload = tmp_path / "submission.json"
    payload.write_text(json.dumps(_PAYLOAD), encoding="utf-8")

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def insertRow(self, row):
            pass

    outcomes = []
    monkeypatch.setattr(cli_mod, "_guard", lambda tool: None)
    monkeypatch.setattr(
        sessions, "arcpy_env",
        lambda: SimpleNamespace(
            da=SimpleNamespace(InsertCursor=lambda *a: Cursor())))

    def append_with_late_error(gdb, table_name, records, qa, batch_id):
        if table_name == "Env_Samples":
            qa.add("ERROR", "duplicate_key_skipped",
                   "duplicate QC sample was skipped")
            return 0, 1
        return len(records), 0

    monkeypatch.setattr(import_to_gdb, "append_records_idempotent",
                        append_with_late_error)
    monkeypatch.setattr(
        import_to_gdb, "finalize_batch",
        lambda *a, **k: outcomes.append(a[-1]))
    monkeypatch.setattr(import_to_gdb, "write_qa_to_gdb",
                        lambda *a, **k: 0)

    result = CliRunner().invoke(
        cli_mod.autogis,
        ["envmon", "route-survey123", str(payload),
         "--site", "H281", "--gdb", str(tmp_path / "test.gdb"),
         "--format", "json"],
    )

    assert result.exit_code != 0
    assert outcomes == ["BLOCKED_BY_QA"]


# ── issue #439: a non-UTF-8 CSV crashed consumers with a raw codec error ───

def test_non_utf8_submissions_csv_raises_a_named_value_error(tmp_path):
    """cp1252 is the Windows/Excel default, so a well name with an accent
    reached the loader as undecodable bytes and every consuming CLI died with
    a raw UnicodeDecodeError traceback."""
    import pytest
    from autogis.core.common.qa import QACollector

    p = tmp_path / "subs_cp1252.csv"
    p.write_bytes(
        "WellID,SamplingDate,Matrix,SampledBy,COCNumber\n"
        "MW-é,2026-07-15,GW,AB,COC-001\n".encode("cp1252"))
    with pytest.raises(ValueError) as exc:
        load_survey123_csv_submissions(p, "H281", "B1", QACollector())
    msg = str(exc.value)
    assert "subs_cp1252.csv" in msg and "UTF-8" in msg
    assert not isinstance(exc.value, UnicodeDecodeError)


def test_missing_submissions_csv_raises_a_named_value_error(tmp_path):
    import pytest
    from autogis.core.common.qa import QACollector

    with pytest.raises(ValueError) as exc:
        load_survey123_csv_submissions(
            tmp_path / "nope.csv", "H281", "B1", QACollector())
    assert "nope.csv" in str(exc.value)
