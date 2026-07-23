"""Map a workflow recipe (core pure-data schema) to a runnable ``Workflow``.

This lives in the adapter layer (not core) because it depends on the GUI
``Workflow``/``Step`` model — core must not import adapters. Both the headless
``run-recipe`` CLI and (later) the GUI save/load can reuse this one mapping, so
the recipe format and the runtime objects never drift apart. See ADR-0103 /
docs/superpowers/specs/2026-07-22-workflow-recipe-core-design.md.
"""
from __future__ import annotations

from typing import Any, Mapping

from autogis.adapters.gui.executor import Step
from autogis.adapters.gui.runner import Workflow
from autogis.core.common.workflow_recipe import RECIPE_VERSION, validate_recipe


def recipe_to_workflow(data: Mapping[str, Any]) -> Workflow:
    """Build a runnable ``Workflow`` from a validated recipe dict.

    Re-validates first so a hand-built dict can't produce a malformed Workflow;
    a ``command`` list becomes a tuple and ``command: null`` stays a review
    checkpoint (``Step.command=None``), a 1:1 translation of the recipe fields.
    """
    validate_recipe(data)
    steps = tuple(
        Step(
            command=(tuple(s["command"]) if s.get("command") is not None
                     else None),
            values=dict(s.get("values") or {}),
            fail_on=s.get("fail_on"),
            pause_on_warning=bool(s.get("pause_on_warning", False)),
            message=s.get("message") or "",
        )
        for s in data["steps"]
    )
    return Workflow(name=data["name"], steps=steps)


def _yaml_native(obj: Any) -> Any:
    """Recursively convert tuples to lists so a value is YAML-safe and stable
    across dump/load. The GUI's ``forms._normalize`` stores a repeatable option
    as a tuple (e.g. ``profiles=("p1.yaml",)``); ``yaml.safe_dump`` can't
    represent a tuple, and a naive save would also reload it as a list and break
    the round-trip. Normalizing to lists here makes the recipe canonical."""
    if isinstance(obj, (list, tuple)):
        return [_yaml_native(x) for x in obj]
    if isinstance(obj, Mapping):
        return {k: _yaml_native(v) for k, v in obj.items()}
    return obj


def workflow_to_recipe(workflow: Workflow) -> dict:
    """Serialize a ``Workflow`` back to a recipe dict — the inverse of
    :func:`recipe_to_workflow`, for the GUI's "save recipe" side.

    Optional fields at their defaults (empty ``values``, ``fail_on=None``,
    ``pause_on_warning=False``, empty ``message``) are omitted so the saved YAML
    stays minimal. Nested tuples in ``values`` (a GUI repeatable option) are
    normalized to lists so the recipe survives ``dump_recipe``/``load_recipe``
    unchanged; the result is validated before returning.
    """
    steps: list[dict] = []
    for s in workflow.steps:
        step: dict = {"command": list(s.command) if s.command is not None else None}
        if s.values:
            step["values"] = {k: _yaml_native(v) for k, v in s.values.items()}
        if s.fail_on is not None:
            step["fail_on"] = s.fail_on
        if s.pause_on_warning:
            step["pause_on_warning"] = True
        if s.message:
            step["message"] = s.message
        steps.append(step)
    data = {"version": RECIPE_VERSION, "name": workflow.name, "steps": steps}
    validate_recipe(data)
    return data
