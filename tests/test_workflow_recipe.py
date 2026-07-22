"""Tests for the Phase 5 workflow-recipe core schema (arcpy-free)."""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis as autogis_cli
from autogis.core.common.config import ConfigError
from autogis.core.common.workflow_recipe import (
    RECIPE_VERSION, dump_recipe, load_recipe, save_recipe, validate_recipe,
)


def _valid_recipe():
    return {
        "version": RECIPE_VERSION,
        "name": "Monitoring event processing",
        "steps": [
            {"command": ["envmon", "reconcile-locations"],
             "values": {"results_csv": "r.csv"}, "fail_on": "error",
             "pause_on_warning": True, "message": "reconcile"},
            {"command": None, "message": "Review layouts before export."},
        ],
    }


def test_valid_recipe_round_trips(tmp_path):
    d = _valid_recipe()
    validate_recipe(d)  # must not raise
    path = save_recipe(d, tmp_path / "sub" / "recipe.yaml")
    assert load_recipe(path) == d


def test_dump_preserves_step_and_field_order():
    text = dump_recipe(_valid_recipe())
    # name before steps; first step's command before values (sort_keys=False)
    assert text.index("name:") < text.index("steps:")
    assert text.index("command:") < text.index("values:")


def test_null_command_checkpoint_is_valid():
    validate_recipe({"name": "x", "steps": [{"command": None,
                                             "message": "checkpoint"}]})


@pytest.mark.parametrize("bad", [
    {"name": "x"},                                             # no steps
    {"name": "x", "steps": []},                                # empty steps
    {"name": "", "steps": [{"command": None}]},                # empty name
    {"steps": [{"command": None}]},                            # missing name
    {"name": "x", "steps": [{"command": []}]},                 # empty command list
    {"name": "x", "steps": [{"command": "envmon inspect"}]},   # command must be list/null
    {"name": "x", "steps": [{"command": ["envmon", ""]}]},     # empty command element
    {"name": "x", "steps": [{"command": [1, 2]}]},             # non-str command element
    {"name": "x", "steps": [{"command": None, "fail_on": "boom"}]},   # bad fail_on
    {"name": "x", "steps": [{"command": None, "fail_on": ["error"]}]},  # unhashable fail_on
    {"name": "x", "steps": [{"command": None, "fail_on": {}}]},         # unhashable fail_on
    {"name": "x", "steps": [{"command": None, "pause_on_warning": "yes"}]},  # non-bool
    {"name": "x", "steps": [{"command": None, "values": [1]}]},  # values not a mapping
    {"name": "x", "steps": [{"command": None, "bogus": 1}]},    # unknown key
    {"name": "x", "steps": [{1: "a", "bogus": "b", "command": None}]},  # mixed-type unknown keys
    {"version": 2, "name": "x", "steps": [{"command": None}]},  # wrong version
    {"name": "x", "steps": [None]},                            # step not a mapping
])
def test_validate_rejects_bad_recipe(bad):
    with pytest.raises(ConfigError):
        validate_recipe(bad)


def test_malformed_yaml_is_configerror_not_traceback(tmp_path):
    """A syntactically invalid recipe file must surface as ConfigError (clean
    CLI message), not an uncaught yaml.YAMLError traceback. Codex P2."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_recipe(bad)
    r = CliRunner().invoke(autogis_cli, ["envmon", "validate-recipe", str(bad)])
    assert r.exit_code != 0
    assert "could not be parsed" in r.output
    assert "Traceback" not in r.output   # clean error, no stack trace

    # same for a malformed .json recipe (load_config also parses JSON)
    badjson = tmp_path / "broken.json"
    badjson.write_text('{"name": "x", ', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_recipe(badjson)

    # and for a file that isn't valid UTF-8 (read_text -> UnicodeDecodeError)
    badbytes = tmp_path / "bytes.yaml"
    badbytes.write_bytes(b"name: \xff\xfe not utf-8\n")
    with pytest.raises(ConfigError):
        load_recipe(badbytes)


def test_cli_validate_recipe(tmp_path):
    good = save_recipe(_valid_recipe(), tmp_path / "good.yaml")
    r = CliRunner().invoke(autogis_cli, ["envmon", "validate-recipe", str(good)])
    assert r.exit_code == 0, r.output
    assert "OK" in r.output and "2 step(s)" in r.output

    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nsteps: []\n", encoding="utf-8")
    r2 = CliRunner().invoke(autogis_cli, ["envmon", "validate-recipe", str(bad)])
    assert r2.exit_code != 0
    assert "steps" in r2.output
