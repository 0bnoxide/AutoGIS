import pytest
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


@pytest.mark.parametrize("content", [
    b"",                       # empty document
    b"- benzene\n",            # list at the top level
    b"a: [\n",                 # invalid YAML
    b"\xff\xfe",               # not UTF-8
    b"analytes:\n  Benzene:\n",  # null entry
])
@pytest.mark.parametrize("flags", [[], ["--list"]])
def test_manage_analyte_dict_bad_yaml_exits_cleanly(tmp_path, content, flags):
    p = tmp_path / "analytes dict ü.yaml"
    p.write_bytes(content)
    r = CliRunner().invoke(autogis, ["envmon", "manage-analyte-dict", str(p), *flags])
    assert r.exit_code == 1
    assert isinstance(r.exception, SystemExit)  # clean exit, not a traceback
    assert "Error:" in r.output


def test_manage_analyte_dict_directory_exits_cleanly(tmp_path):
    r = CliRunner().invoke(autogis, ["envmon", "manage-analyte-dict", str(tmp_path)])
    assert r.exit_code == 1
    assert "could not be read" in r.output
