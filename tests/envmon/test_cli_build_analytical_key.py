"""CLI test for the headless build-analytical-key command (Tool 5.5)."""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis

_ANALYTE_YAML = """\
analytes:
  Benzene:
    abbreviation: B
    display_order: 10
    default_units_by_matrix: {GW: ug/L, SOIL: mg/kg}
    include_in_default_figures: true
  Methane:
    abbreviation: CH4
    display_order: 200
    default_units_by_matrix: {GW: mg/L}
    include_in_default_figures: false
"""

_SCREENING_YAML = """\
screening_levels:
  GW:
    Benzene: {value: null, units: ug/L, source: _TODO MDEQ RBSL}
"""


def _write(tmp_path):
    a = tmp_path / "analytes.yaml"
    a.write_text(_ANALYTE_YAML, encoding="utf-8")
    s = tmp_path / "screening.yaml"
    s.write_text(_SCREENING_YAML, encoding="utf-8")
    return a, s


def test_build_analytical_key_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "build-analytical-key" in result.output


def test_build_analytical_key_markdown_stdout(tmp_path):
    a, s = _write(tmp_path)
    result = CliRunner().invoke(autogis, [
        "envmon", "build-analytical-key",
        "--analyte-dict", str(a), "--screening-levels", str(s),
        "--matrix", "GW",
    ])
    assert result.exit_code == 0, result.output
    assert "NE" in result.output            # null screening -> Not Established
    assert "Methane" not in result.output   # excluded by default filter


def test_build_analytical_key_csv_out(tmp_path):
    a, s = _write(tmp_path)
    out = tmp_path / "key.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "build-analytical-key",
        "--analyte-dict", str(a), "--screening-levels", str(s),
        "--matrix", "GW", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "canonical" in text and "Benzene" in text


@pytest.mark.parametrize("which, text", [
    ("analytes", "analytes: null\n"),
    ("analytes", "analytes: [a, b]\n"),
    ("analytes", "a: [\n"),
    ("analytes", "- a\n"),
    ("screening", "screening_levels: [a]\n"),
    ("screening", ""),
])
def test_build_analytical_key_bad_input_is_clean_error(tmp_path, which, text):
    """#598: malformed inputs exit 1 with a clean message, not a traceback."""
    a, s = _write(tmp_path)
    (a if which == "analytes" else s).write_text(text, encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-analytical-key",
        "--analyte-dict", str(a), "--screening-levels", str(s), "--matrix", "GW",
    ])
    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_build_analytical_key_null_screening_is_not_established(tmp_path):
    """#598: a blank ``screening_levels:`` means no levels -> every row NE."""
    a, s = _write(tmp_path)
    s.write_text("screening_levels: null\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-analytical-key",
        "--analyte-dict", str(a), "--screening-levels", str(s), "--matrix", "GW",
    ])
    assert result.exit_code == 0, result.output
    assert "Benzene" in result.output and "NE" in result.output


@pytest.mark.parametrize("suffix", ["", ".csv", ".xlsx"])
def test_build_analytical_key_unwritable_out_is_clean_error(tmp_path, suffix):
    """#598: a directory as --out is a clean 'cannot write' error."""
    a, s = _write(tmp_path)
    out = tmp_path / f"out{suffix}"
    out.mkdir()
    result = CliRunner().invoke(autogis, [
        "envmon", "build-analytical-key",
        "--analyte-dict", str(a), "--screening-levels", str(s),
        "--matrix", "GW", "--out", str(out),
    ])
    assert result.exit_code == 1, result.output
    assert f"cannot write {out}" in result.output
