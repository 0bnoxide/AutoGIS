"""#354 and #355 are the acceptance tests for the CommaList declarations: a
typo'd element must now be a clean usage error naming the legal values, rather
than a silent empty output or a raw traceback."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_bad_tiers_is_a_usage_error_not_a_silent_empty_file(tmp_path):
    """Closes #354: --tiers HOTSPT used to exit 0 with a header-only CSV."""
    src = tmp_path / "in.csv"
    src.write_text("LocationID,Top,Bottom,Result\nB-1,0,5,1.0\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--results-csv", str(src), "--out", str(tmp_path / "o.csv"),
        "--tiers", "HOTSPT",
    ])
    assert res.exit_code == 2, res.output
    assert "HOTSPT" in res.output
    assert "HOTSPOT" in res.output  # the legal values are listed


def test_bad_features_is_a_usage_error_not_a_traceback(tmp_path):
    """Closes #355: --features typo used to raise a raw ValueError."""
    res = CliRunner().invoke(autogis, [
        "envmon", "gen-synthetic-workbook",
        "--out", str(tmp_path / "wb.xlsx"),
        "--features", "nondetects,typo_feature",
    ])
    assert res.exit_code == 2, res.output
    assert "typo_feature" in res.output
    assert "Traceback" not in res.output


def test_valid_tiers_still_works(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("LocationID,Top,Bottom,Result\nB-1,0,5,1.0\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--results-csv", str(src), "--out", str(tmp_path / "o.csv"),
        "--tiers", "HOTSPOT",
    ])
    assert res.exit_code == 0, res.output


def test_unknown_dataset_is_a_usage_error():
    """Task 5: --dataset becomes a strict click.Choice -- opentopo.get_dataset()
    already refuses any code outside DEM_DATASETS, so nothing is newly lost."""
    res = CliRunner().invoke(autogis, ["envmon", "download-dem", "--dataset", "NOPE",
                                       "--bbox", "-105", "39", "-104", "40",
                                       "--out", "x.tif", "--dry-run"])
    assert res.exit_code == 2
    assert "NOPE" in res.output


def test_suggested_matrix_still_accepts_an_unlisted_code(tmp_path):
    """The whole point of SuggestedChoice: SED is real (nysdec.yaml) but is not
    in KNOWN_MATRICES, and must keep working. Regression guard -- passes both
    before and after Task 5's SuggestedChoice wiring."""
    src = tmp_path / "legacy.csv"
    src.write_text("LocationID,Analyte,Result\nB-1,Benzene,1.0\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "migrate-legacy-data", "--input-csv", str(src),
        "--output", str(tmp_path / "o.csv"), "--default-matrix", "SED",
    ])
    assert res.exit_code == 0, res.output


def test_run_history_tool_filter_accepts_a_retired_tool_name(tmp_path):
    """A log query must still be able to name a command that no longer exists.
    Regression guard -- passes both before and after Task 5's SuggestedChoice
    wiring. CSV columns must match run_history.RunRecord's actual schema."""
    hist = tmp_path / "run_history.csv"
    hist.write_text(
        "run_id,tool_name,site_id,event_id,started_at,finished_at,status,"
        "inputs,outputs,qa_count_error,qa_count_warning,qa_count_info,message\n"
        "r1,a-retired-tool,S1,__None__,2026-01-01T00:00:00,2026-01-01T00:00:01,"
        "success,{},{},0,0,0,ok\n",
        encoding="utf-8",
    )
    res = CliRunner().invoke(autogis, ["envmon", "run-history",
                                       "--run-history", str(hist),
                                       "--tool", "a-retired-tool"])
    assert res.exit_code == 0, res.output
    assert "a-retired-tool" in res.output


def test_malformed_event_date_is_a_usage_error(tmp_path):
    res = CliRunner().invoke(autogis, ["envmon", "gw-level-summary",
                                       "--event-date", "25-07-2026"])
    assert res.exit_code == 2
    assert "25-07-2026" in res.output


def test_since_still_accepts_a_full_timestamp(tmp_path):
    """cli.py:1590 uses datetime.fromisoformat -- narrowing to date-only would
    reject a value that works today."""
    hist = tmp_path / "run_history.csv"
    hist.write_text("timestamp,site_id,tool_name,status,message\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "run-history",
                                       "--run-history", str(hist),
                                       "--since", "2026-07-01T10:30:00"])
    assert res.exit_code == 0, res.output


def test_all_sixteen_date_options_are_isodate():
    """Guard against a future option being added as bare text."""
    from autogis.adapters.param_types import IsoDate
    from autogis.adapters.gui.introspect import introspect_cli
    dated = [(f.label, x.name) for f in introspect_cli() for x in f.fields
             if x.kind == "date"]
    assert len(dated) == 16, dated
