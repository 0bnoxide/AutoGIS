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
