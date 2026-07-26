"""Form-values -> workflow ``Step`` builder for the unified GUI adapter.

Bridges what a GUI renders (:class:`~autogis.adapters.gui.introspect.CommandForm`
/ :class:`~autogis.adapters.gui.introspect.FormField`) to what
:func:`~autogis.adapters.gui.executor.run_step` executes
(:class:`~autogis.adapters.gui.executor.Step`) — nothing currently maps one to
the other, and the workflow builder (ADR-0050 decision 4) needs exactly this
to turn a filled-out form into a runnable step. Pure logic: no GUI toolkit,
no arcpy, same scoping as introspect.py/executor.py/runner.py.

Deliberately **not** re-validated here — left to the child command's own
guard, whose refusal `executor.decide()` already turns into a clean HALT with
stderr as the reason:

- Conditional requirements (``sync-to-gdb``'s "--gdb requires --table",
  ``batch-import-workbooks``'s "--edd-dir requires --profile and --site") —
  introspect.py's own docstring already scopes these out of the descriptors
  this module reads.
- Type-parseability of int/float/choice strings — Click's own parser in the
  child process is the single source of truth; duplicating it here would be
  a second place to keep in sync for the same rule.
- Path existence — ``click.Path(exists=True)`` in the child process already
  refuses a missing input file cleanly.

What *is* checked here, before ever launching a subprocess: a command
declared unreachable in this environment, a missing required field, and an
unsatisfied ``xor_group`` (introspect.py's own ``XOR_PAIRS`` metadata, not a
re-derivation of each command's body-level rule) — failures a GUI should
surface inline rather than via a child-process crash.
"""
from __future__ import annotations

from typing import Mapping

from .executor import Step
from .introspect import CommandForm, FormField

__all__ = ["FormValidationError", "build_step"]


class FormValidationError(ValueError):
    """A validation failure the GUI should surface inline (on ``.field`` if
    set), before launching a child process."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def _normalize(field: FormField, value: object) -> object:
    """Missing/blank -> None (omitted, so the command's own default
    applies) rather than passed through as a literal empty string. A
    ``False`` flag is a real, explicit value (the user unchecked a box that
    may default True) and is never treated as empty. A ``nargs>1`` field's
    typed text (#351, e.g. ``--bbox``'s "W S E N") is whitespace-split and
    count-checked before any of that -- an empty string still takes the
    blank -> None path above."""
    if _is_empty(value):
        return None
    if field.nargs > 1:
        parts = value.split() if isinstance(value, str) else list(value)
        if len(parts) != field.nargs:
            raise FormValidationError(
                f"{field.label}: expected {field.nargs} values, got "
                f"{len(parts)}.", field=field.name)
        return tuple(parts)
    if field.kind == "flag":
        return bool(value)
    if field.repeatable and not isinstance(value, (list, tuple)):
        return (value,)
    return value


def build_step(form: CommandForm, raw_values: Mapping[str, object], *,
               fail_on: str | None = None,
               pause_on_warning: bool = False) -> Step:
    """Validate ``raw_values`` (as a form widget would supply them) against
    ``form.fields`` and build a :class:`Step`.

    Raises :class:`FormValidationError` for an unreachable command, an
    unknown field name, a missing required field, or an xor_group where
    neither or both siblings are filled.
    """
    if form.unreachable_reason:
        raise FormValidationError(
            f"{form.label} is unreachable here: {form.unreachable_reason}")

    fields_by_name = {f.name: f for f in form.fields}
    unknown = set(raw_values) - set(fields_by_name)
    if unknown:
        raise FormValidationError(
            f"{form.label}: unknown field(s) {sorted(unknown)}")

    values = {f.name: _normalize(f, raw_values.get(f.name))
             for f in form.fields}

    for f in form.fields:
        if f.required and values[f.name] is None:
            raise FormValidationError(
                f"{form.label}: {f.label} is required.", field=f.name)

    groups: dict[str, list[FormField]] = {}
    for f in form.fields:
        if f.xor_group:
            groups.setdefault(f.xor_group, []).append(f)
    for members in groups.values():
        # A flag member (e.g. reconcile-locations' --gdb) is only "chosen"
        # when True -- an explicit False (checkbox left unchecked) must not
        # count as filled, or an unchecked flag plus an empty sibling would
        # wrongly read as "exactly one chosen."
        filled = [f for f in members
                 if (values[f.name] if f.kind == "flag" else values[f.name] is not None)]
        if len(filled) != 1:
            names = " / ".join(f.label for f in members)
            raise FormValidationError(
                f"{form.label}: choose exactly one of {names}.",
                field=members[0].name)

    values = {k: v for k, v in values.items() if v is not None}
    return Step(command=form.path, values=values,
               fail_on=fail_on, pause_on_warning=pause_on_warning)
