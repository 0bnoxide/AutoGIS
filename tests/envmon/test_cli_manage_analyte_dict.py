import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write(tmp_path, data):
    p = tmp_path / "analytes.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_manage_analyte_dict_check_fails_on_collision(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10},
        "Toluene": {"aliases": ["b"], "abbreviation": "T", "display_order": 20}}})
    r = CliRunner().invoke(autogis, ["envmon", "manage-analyte-dict", p])
    assert r.exit_code == 1
    assert "alias_collision" in r.output


def test_manage_analyte_dict_list_prints_table(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "display_order": 10}}})
    r = CliRunner().invoke(autogis, ["envmon", "manage-analyte-dict", p, "--list"])
    assert r.exit_code == 0
    assert "Benzene" in r.output
