"""The shipped example workflow recipes (Phase 5) must validate AND reference
real CLI commands — a starter template with a wrong tool name would be worse
than none. Arcpy-free."""
from pathlib import Path

import autogis
from autogis.adapters.gui.executor import _resolve_command
from autogis.core.common.workflow_recipe import load_recipe

RECIPES = Path(autogis.__file__).resolve().parent / "config" / "recipes"


def test_example_recipes_validate_and_commands_resolve():
    files = sorted(RECIPES.glob("*.yaml"))
    names = {f.name for f in files}
    assert {"monitoring_event_processing.yaml", "rtk_to_cad.yaml"} <= names
    for f in files:
        data = load_recipe(f)               # structural validation
        assert data["steps"]                # non-empty
        for step in data["steps"]:
            cmd = step.get("command")
            if cmd:                         # skip review checkpoints (null)
                _resolve_command(cmd)       # raises ValueError if not a real command
