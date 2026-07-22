"""Linear workflow-recipe schema — save / load / validate (headless, arcpy-free).

The reusable substrate for roadmap Phase 5 (saved workflow recipes). A recipe is
a named, ordered list of steps serialized to YAML. The field shape mirrors the
GUI ``Workflow(name, steps)`` / ``Step(command, values, fail_on,
pause_on_warning, message)`` model exactly, but this module does NOT import the
GUI (core must not depend on adapters): it validates the pure-data dict form, and
the GUI maps ``Workflow <-> recipe dict`` on top of ``dump_recipe`` /
``load_recipe``. See docs/superpowers/specs/2026-07-22-workflow-recipe-core-design.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .config import ConfigError, load_config

RECIPE_VERSION = 1

# Optional step keys and their required types (command/values validated
# specially below). Unknown keys are rejected as typos.
_STEP_KNOWN_KEYS = {"command", "values", "fail_on", "pause_on_warning", "message"}
_VALID_FAIL_ON = {"error", "warning"}


def validate_recipe(data: Mapping[str, Any]) -> None:
    """Raise ``ConfigError`` if *data* is not a well-formed workflow recipe."""
    if not isinstance(data, Mapping):
        raise ConfigError("recipe must be a mapping at the top level")

    version = data.get("version", RECIPE_VERSION)
    if version != RECIPE_VERSION:
        raise ConfigError(
            f"recipe version {version!r} is not supported "
            f"(this build understands version {RECIPE_VERSION})")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("recipe 'name' must be a non-empty string")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ConfigError("recipe 'steps' must be a non-empty list")

    for i, step in enumerate(steps):
        _validate_step(step, i)


def _validate_step(step: Any, i: int) -> None:
    where = f"recipe step {i}"
    if not isinstance(step, Mapping):
        raise ConfigError(f"{where} must be a mapping")

    unknown = set(step) - _STEP_KNOWN_KEYS
    if unknown:
        # sort on repr: step keys may be mixed scalar types (e.g. YAML `1:` and
        # `foo:`) and sorting those directly raises TypeError, not ConfigError.
        raise ConfigError(f"{where}: unknown key(s) {sorted(map(repr, unknown))}")

    command = step.get("command")  # None (checkpoint) or list[str]
    if command is not None:
        if (not isinstance(command, list) or not command
                or not all(isinstance(c, str) and c for c in command)):
            raise ConfigError(
                f"{where}: 'command' must be null (a review checkpoint) or a "
                f"non-empty list of non-empty strings")

    values = step.get("values")
    if values is not None and not isinstance(values, Mapping):
        raise ConfigError(f"{where}: 'values' must be a mapping")

    fail_on = step.get("fail_on")
    # isinstance guard first: an unhashable value (list/dict) would raise
    # TypeError on the set membership instead of a clean ConfigError.
    if fail_on is not None and (not isinstance(fail_on, str)
                                or fail_on not in _VALID_FAIL_ON):
        raise ConfigError(
            f"{where}: 'fail_on' must be one of {sorted(_VALID_FAIL_ON)} or null")

    pause = step.get("pause_on_warning")
    if pause is not None and not isinstance(pause, bool):
        raise ConfigError(f"{where}: 'pause_on_warning' must be true/false")

    message = step.get("message")
    if message is not None and not isinstance(message, str):
        raise ConfigError(f"{where}: 'message' must be a string")


def load_recipe(path: Path) -> dict:
    """Load and validate a recipe YAML/JSON file. Raises ``ConfigError`` (incl.
    for a syntactically invalid file — load_config lets yaml.YAMLError through)."""
    path = Path(path)
    try:
        data = load_config(path)   # checks the file exists + is a mapping
    except yaml.YAMLError as exc:
        raise ConfigError(f"recipe {path} is not valid YAML: {exc}") from exc
    validate_recipe(data)
    return data


def dump_recipe(data: Mapping[str, Any]) -> str:
    """Validate *data* and serialize it to YAML (step/field order preserved)."""
    validate_recipe(data)
    return yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)


def save_recipe(data: Mapping[str, Any], path: Path) -> Path:
    """Validate and write *data* to *path* as YAML. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_recipe(data), encoding="utf-8")
    return path
