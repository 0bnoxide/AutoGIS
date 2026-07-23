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


def workflow_to_recipe(workflow: Workflow) -> dict:
    """Serialize a ``Workflow`` back to a recipe dict — the inverse of
    :func:`recipe_to_workflow`, for the GUI's "save recipe" side.

    Round-trips: ``recipe_to_workflow(workflow_to_recipe(wf))`` reproduces *wf*.
    Optional fields at their defaults (empty ``values``, ``fail_on=None``,
    ``pause_on_warning=False``, empty ``message``) are omitted so the saved YAML
    stays minimal. The result is validated before returning.
    """
    steps: list[dict] = []
    for s in workflow.steps:
        step: dict = {"command": list(s.command) if s.command is not None else None}
        if s.values:
            step["values"] = dict(s.values)
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
