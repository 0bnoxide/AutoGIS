import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_validate_config_cli_fails_on_cross_file_break(tmp_path):
    site = _write(tmp_path, "site.yaml", {
        "site_id": "H281", "site_name": "X", "project_number": "H281",
        "address": "a", "city": "c", "state": "s", "coordinate_system": "NAD83",
        "default_gdb": "g.gdb", "default_aprx_template": "t.aprx",
        "monitoring_wells_fc": "MW", "soil_borings_fc": "SB",
        "site_boundary_fc": "BND", "map_units": "feet",
        "plausible_gwe_range_ft": [1900, 2400]})
    analytes = _write(tmp_path, "analytes.yaml",
                      {"analytes": {"Benzene": {"aliases": ["benzene"],
                                                "abbreviation": "B",
                                                "display_order": 10}}})
    figure = _write(tmp_path, "fig.yaml", {
        "figure_spec_id": "F1", "map_type": "GW_ANALYTICAL", "matrix": "GW",
        "layout_name": "L", "figure_title": "T",
        "output_filename_pattern": "{x}.pdf", "callout_template": {},
        "analytes": ["Benzene", "Nonexistium"]})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-config", site, "--figure", figure,
        "--analytes", analytes])
    assert r.exit_code == 1
    assert "figure_analyte_not_in_dictionary" in r.output


def test_validate_config_cli_passes_clean_bundle(tmp_path):
    site = _write(tmp_path, "site.yaml", {
        "site_id": "H281", "site_name": "X", "project_number": "H281",
        "address": "a", "city": "c", "state": "s", "coordinate_system": "NAD83",
        "default_gdb": "g.gdb", "default_aprx_template": "t.aprx",
        "monitoring_wells_fc": "MW", "soil_borings_fc": "SB",
        "site_boundary_fc": "BND", "map_units": "feet",
        "plausible_gwe_range_ft": [1900, 2400]})
    analytes = _write(tmp_path, "analytes.yaml",
                      {"analytes": {"Benzene": {"aliases": ["benzene"],
                                                "abbreviation": "B",
                                                "display_order": 10}}})
    figure = _write(tmp_path, "fig.yaml", {
        "figure_spec_id": "F1", "map_type": "GW_ANALYTICAL", "matrix": "GW",
        "layout_name": "L", "figure_title": "T",
        "output_filename_pattern": "{x}.pdf", "callout_template": {},
        "analytes": ["Benzene"]})
    r = CliRunner().invoke(autogis, [
        "envmon", "validate-config", site, "--figure", figure,
        "--analytes", analytes, "--fail-on", "error"])
    assert r.exit_code == 0
    assert "Status: PASS" in r.output
