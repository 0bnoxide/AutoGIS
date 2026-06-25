from pathlib import Path

import yaml

from autogis.core.envmon.validate_config import validate_env_config
from autogis.core.common.qa import SEV_ERROR, SEV_INFO


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_validate_env_config_collects_cross_file_break(tmp_path):
    site = _write(tmp_path, "site.yaml", {
        "site_id": "H281", "site_name": "X", "project_number": "H281",
        "address": "a", "city": "c", "state": "s",
        "coordinate_system": "NAD83", "default_gdb": "g.gdb",
        "default_aprx_template": "t.aprx", "monitoring_wells_fc": "MW",
        "soil_borings_fc": "SB", "site_boundary_fc": "BND",
        "map_units": "feet", "plausible_gwe_range_ft": [1900, 2400]})
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "display_order": 10}}})
    figure = _write(tmp_path, "fig.yaml", {
        "figure_spec_id": "F1", "map_type": "GW_ANALYTICAL", "matrix": "GW",
        "layout_name": "L", "figure_title": "T",
        "output_filename_pattern": "{x}.pdf", "callout_template": {},
        "analytes": ["Benzene", "Nonexistium"]})
    qa = validate_env_config(site, [], [figure], analytes, None)
    cats = {(r.severity, r.category) for r in qa.records}
    assert (SEV_ERROR, "figure_analyte_not_in_dictionary") in cats


def test_validate_env_config_bad_file_becomes_load_error(tmp_path):
    bad = tmp_path / "site.yaml"
    bad.write_text(": : not valid yaml : :", encoding="utf-8")
    qa = validate_env_config(bad, [], [], None, None)
    assert (SEV_ERROR, "load_error") in {(r.severity, r.category) for r in qa.records}


def test_validate_env_config_notes_when_analytes_omitted(tmp_path):
    figure = _write(tmp_path, "fig.yaml", {
        "figure_spec_id": "F1", "map_type": "GW_ANALYTICAL", "matrix": "GW",
        "layout_name": "L", "figure_title": "T",
        "output_filename_pattern": "{x}.pdf", "callout_template": {},
        "analytes": ["Benzene"]})
    qa = validate_env_config(None, [], [figure], None, None)
    assert (SEV_INFO, "cross_file_skipped") in {
        (r.severity, r.category) for r in qa.records}
