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
from autogis.core.common.workflow_recipe import validate_recipe


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
