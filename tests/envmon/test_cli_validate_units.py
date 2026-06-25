import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_validate_units_cli_fails_on_cross_dimension(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {
        "GW": {"Benzene": {"value": None, "units": "mg/kg"}}}})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-units", "--analytes", analytes,
        "--screening", screening])
    assert r.exit_code == 1
    assert "cross_dimension" in r.output


def test_validate_units_cli_passes_clean(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {
        "GW": {"Benzene": {"value": None, "units": "ug/L"}}}})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-units", "--analytes", analytes,
        "--screening", screening, "--fail-on", "error"])
    assert r.exit_code == 0
    assert "Status: PASS" in r.output
