from pathlib import Path

from autogis.core.envmon.manage_screening_levels import (
    ScreeningEntry, check_screening_levels, load_screening_entries,
)
from click.testing import CliRunner
from autogis.adapters.cli import autogis

_VALID_YAML = """\
screening_levels:
  GW:
    Benzene: {value: 5.0, units: ug/L, source: "MDEQ RBSL 2024"}
  SOIL:
    Benzene: {value: 0.1, units: mg/kg, source: "MDEQ RBSL 2024"}
"""

_NULL_YAML = """\
screening_levels:
  GW:
    Benzene: {value: null, units: ug/L, source: "_TODO MDEQ RBSL"}
"""

_BAD_YAML = """\
screening_levels:
  GW:
    Benzene: {value: "not-a-number", source: "MDEQ"}
"""

_ANALYTES_YAML = """\
Benzene:
  canonical_name: Benzene
  default_units_by_matrix: {GW: ug/L, SOIL: mg/kg}
Toluene:
  canonical_name: Toluene
  default_units_by_matrix: {GW: ug/L}
"""


def test_valid_entry_passes(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_null_value_warns(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_NULL_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    cats = [r.category for r in qa.records]
    assert "null_value" in cats


def test_todo_source_warns(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_NULL_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    assert any("placeholder_source" == r.category for r in qa.records)


def test_missing_units_errors(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_BAD_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    cats = [r.category for r in qa.records]
    assert "missing_entry_key" in cats


def test_load_screening_entries_flat(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    entries = load_screening_entries(f)
    assert len(entries) == 2
    analytes = {e.analyte for e in entries}
    assert "Benzene" in analytes


def test_analyte_coverage_check_flags_missing(tmp_path):
    sl = tmp_path / "sl.yaml"
    sl.write_text(_VALID_YAML, encoding="utf-8")
    al = tmp_path / "an.yaml"
    al.write_text(_ANALYTES_YAML, encoding="utf-8")
    qa = check_screening_levels(sl, analytes_path=al)
    assert any(r.category == "analyte_not_covered" for r in qa.records)


def test_analyte_coverage_skipped_without_analytes_path(tmp_path):
    sl = tmp_path / "sl.yaml"
    sl.write_text(_VALID_YAML, encoding="utf-8")
    qa = check_screening_levels(sl)
    assert not any(r.category == "analyte_not_covered" for r in qa.records)


def test_valid_entry_no_analyte_not_covered(tmp_path):
    sl = tmp_path / "sl.yaml"
    sl.write_text(_VALID_YAML, encoding="utf-8")
    al = tmp_path / "an.yaml"
    al.write_text("Benzene:\n  canonical_name: Benzene\n  "
                  "default_units_by_matrix: {GW: ug/L, SOIL: mg/kg}\n",
                  encoding="utf-8")
    qa = check_screening_levels(sl, analytes_path=al)
    assert not any(r.category == "analyte_not_covered" for r in qa.records)


def test_manage_screening_levels_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "manage-screening-levels" in result.output


def test_cli_renders_qa_and_exits_nonzero_on_error(tmp_path):
    """The command must render QA and honor --fail-on (was silently dropping qa)."""
    f = tmp_path / "sl.yaml"
    f.write_text(_BAD_YAML, encoding="utf-8")
    result = CliRunner().invoke(autogis, ["envmon", "manage-screening-levels", str(f)])
    assert result.exit_code != 0


def test_cli_valid_screening_exits_zero(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    result = CliRunner().invoke(autogis, ["envmon", "manage-screening-levels", str(f)])
    assert result.exit_code == 0, result.output
