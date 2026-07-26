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


def test_all_seventeen_date_options_are_isodate():
    """Guard against a future option being added as bare text."""
    from autogis.adapters.gui.introspect import introspect_cli
    dated = [(f.label, x.name) for f in introspect_cli() for x in f.fields
             if x.kind == "date"]
    assert len(dated) == 17, dated


def test_sync_survey123_since_accepts_the_advertised_timestamp_shape():
    from autogis.adapters.param_types import IsoDate
    envmon = autogis.commands["envmon"]
    command = envmon.commands["sync-survey123"]
    since = next(p for p in command.params if p.name == "since_date")
    assert isinstance(since.type, IsoDate)
    assert since.type.allow_time is True


def test_negative_limit_is_a_usage_error(tmp_path):
    """Closes #353: --limit had no floor, so a negative value silently reached
    the slicer instead of failing fast with a usage error."""
    hist = tmp_path / "h.csv"
    hist.write_text("timestamp,site_id,tool_name,status,message\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "run-history",
                                       "--run-history", str(hist), "--limit=-5"])
    assert res.exit_code == 2, res.output


def test_directory_params_reject_an_existing_file(tmp_path):
    """#353: a bare click.Path() accepted a FILE for a directory param."""
    results_csv = tmp_path / "results.csv"
    results_csv.write_text("x", encoding="utf-8")
    locations_csv = tmp_path / "locations.csv"
    locations_csv.write_text("x", encoding="utf-8")
    afile = tmp_path / "not-a-dir.txt"
    afile.write_text("x", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "export-wqx",
                                       "--results", str(results_csv),
                                       "--locations", str(locations_csv),
                                       "--out-dir", str(afile)])
    assert res.exit_code == 2, res.output
    assert "directory" in res.output.lower() or "file" in res.output.lower()


# Derived from the live Click tree (Task 7 Step 3) -- every bare click.Path()
# whose python dest name ends in "_dir" (the gdb family is excluded: it's
# forced to a folder picker by name in gui/introspect.py regardless of
# file_okay, so it isn't part of issue #353's original 12). sync-survey123
# added the thirteenth after this branch's baseline.
FOLDER_PARAMS = [
    ("envmon well-inspection-report", "output_dir"),
    ("envmon well-inspection-report", "harvest_dir"),
    ("envmon export-snapshot", "out_dir"),
    ("envmon create-sampling-event", "out_dir"),
    ("envmon export-wqx", "out_dir"),
    ("envmon export-survey-cad", "output_dir"),
    ("envmon condition-dem", "out_dir"),
    ("envmon gen-map-series", "out_dir"),
    ("envmon merge-event-results", "results_dir"),
    ("envmon build-report-package", "out_dir"),
    ("envmon batch-import-workbooks", "output_dir"),
    ("envmon export-civil3d", "out_dir"),
    ("envmon sync-survey123", "out_dir"),
]


def test_the_thirteen_folder_params_are_declared_dir_only():
    from autogis.adapters.gui.introspect import introspect_cli
    assert len(FOLDER_PARAMS) == 13, "derive the real list; do not guess"
    forms = {f.label: f for f in introspect_cli()}
    for label, dest in FOLDER_PARAMS:
        field = next(x for x in forms[label].fields if x.name == dest)
        assert field.is_dir is True, f"{label} --{dest} still accepts a file"
