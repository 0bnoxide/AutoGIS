"""Click-command -> form-field introspection for the unified GUI adapter.

Walks the ``autogis`` Click command tree (root group in
``autogis/adapters/cli.py``) and produces, for every leaf command, a
:class:`CommandForm` holding plain-data :class:`FormField` descriptors a GUI
can render a form from. Depends on ``click`` only — no GUI toolkit, no arcpy
(ADR-0051; the toolkit arrives in a later task per ADR-0050).

Path picker direction (``FormField.is_path_output``) is a *hint*, not ground
truth: ``click.Path(exists=True)`` params are inputs (open picker), bare
``click.Path()`` params are outputs (save picker). Known exceptions where an
*input* is declared without ``exists=True`` and is therefore reported as
output-direction:

- ``envmon evaluate-readiness --run-history`` / ``--qa-report`` /
  ``--figure-spec`` and ``envmon portfolio-metrics --run-history`` — inputs
  that may legitimately not exist yet (an absent run-history is treated as
  empty).
- ``envmon validate-db GDB`` — an input geodatabase, declared as bare
  ``click.Path()``.

A GUI should treat the flag as a default picker direction and always let the
user type a path.
"""
from __future__ import annotations

from dataclasses import dataclass

import click

__all__ = ["FormField", "CommandForm", "XOR_PAIRS", "introspect_cli"]


# ponytail: 5 hardcoded pairs, deliberately not a constraint DSL (ADR-0051).
# These are every pairwise either/or enforced inside a command *body* on main
# as of 2026-07-04 — body-level ``raise UsageError`` checks are invisible to
# click parameter introspection, hence this table. The planning pass counted
# 4; a search for the actual enforcement signal found the fifth
# (batch-import-workbooks).
#
# Known non-pair exception, deliberately NOT modeled:
#   ``envmon draft-plume-boundary``: --points is mutually exclusive with
#   --results/--coords *jointly* (one input mode xor BOTH of the other two) —
#   a three-way rule that doesn't fit a pair table. A GUI should surface that
#   command's help text rather than grey fields.
# Conditional requirements (e.g. sync-to-gdb's "--gdb requires --table",
# batch-import-workbooks' "--edd-dir requires --profile and --site") are also
# not modeled — the CLI's own UsageError messages cover them.
XOR_PAIRS: dict[str, tuple[str, str]] = {
    "envmon reconcile-locations": ("wells_csv", "gdb"),
    "envmon survey-to-well-elevation": ("wells_csv", "gdb"),
    "envmon update-well-elevations": ("wells_csv", "gdb"),
    "agol sync-to-gdb": ("out_csv", "gdb"),
    "envmon batch-import-workbooks": ("manifest", "edd_dir"),
}


@dataclass(frozen=True)
class FormField:
    """One renderable form field, mapped from a ``click.Parameter``."""

    name: str  # click param name (python identifier, e.g. "wells_csv")
    label: str  # humanized name for display
    kind: str  # "text" | "int" | "float" | "flag" | "choice" | "path"
    required: bool
    default: object
    choices: tuple[str, ...] | None = None  # populated for kind == "choice"
    help_text: str | None = None
    repeatable: bool = False  # click multiple=True: one value-widget, repeated
    is_path_output: bool = False  # kind == "path": save picker vs open picker
    xor_group: str | None = None  # shared id; fill one, grey its sibling


@dataclass(frozen=True)
class CommandForm:
    """One leaf command: where it lives, its help, and its form fields."""

    path: tuple[str, ...]  # e.g. ("envmon", "reconcile-locations")
    help_text: str | None
    fields: tuple[FormField, ...]
    unreachable_reason: str | None = None  # set -> grey out / hide / warn

    @property
    def label(self) -> str:
        return " ".join(self.path)


def _walk(group: click.Group, prefix: tuple[str, ...] = ()):
    """Yield (path, command) for every leaf. Same idiom as
    tests/test_capabilities.py's registration-drift walk."""
    for name, cmd in group.commands.items():
        path = prefix + (name,)
        if isinstance(cmd, click.Group):
            yield from _walk(cmd, path)
        else:
            yield path, cmd


def _field(param: click.Parameter, xor_pair: tuple[str, str] | None) -> FormField:
    kind = "text"
    choices: tuple[str, ...] | None = None
    is_path_output = False
    ptype = param.type
    if getattr(param, "is_flag", False):
        kind = "flag"
    elif isinstance(ptype, click.Choice):
        kind = "choice"
        choices = tuple(str(c) for c in ptype.choices)
    elif isinstance(ptype, click.Path):
        kind = "path"
        is_path_output = not ptype.exists  # heuristic; see module docstring
    elif ptype.name == "integer":
        kind = "int"
    elif ptype.name == "float":
        kind = "float"
    # everything else — incl. comma-separated list options like
    # --analytes "a,b,c" — is deliberately plain text: the value passes
    # through unchanged and the option's help documents the format.

    xor_group = None
    if xor_pair and param.name in xor_pair:
        xor_group = "/".join(xor_pair)

    return FormField(
        name=param.name,
        label=param.name.replace("_", " ").title(),
        kind=kind,
        required=bool(param.required),
        default=param.default,
        choices=choices,
        help_text=getattr(param, "help", None),
        repeatable=bool(getattr(param, "multiple", False)),
        is_path_output=is_path_output,
        xor_group=xor_group,
    )


def introspect_cli(root: click.Group | None = None,
                   unreachable: dict[str, str] | None = None,
                   ) -> list[CommandForm]:
    """Describe every leaf command in the tree as a :class:`CommandForm`.

    ``root`` defaults to the ``autogis`` CLI root group (imported lazily so
    this module stays cheap to import).

    ``unreachable`` maps a space-joined command path (e.g.
    ``"envmon optimize-callouts"``, ``"envmon manage-callout-overrides lock"``)
    to a human-readable reason. Matching commands are still walked and fully
    described — never silently omitted — but carry ``unreachable_reason`` so a
    GUI can grey out, hide, or warn. The intended callers' list is the
    ADR-0006 Pro-fallback-only tools plus the ADR-0039 dead-end families;
    deliberately not hardcoded here, since those are policy decisions that can
    be reopened without touching this module.
    """
    if root is None:
        from autogis.adapters.cli import autogis as root
    unreachable = unreachable or {}
    forms: list[CommandForm] = []
    for path, cmd in _walk(root):
        label = " ".join(path)
        pair = XOR_PAIRS.get(label)
        forms.append(CommandForm(
            path=path,
            help_text=cmd.help,
            fields=tuple(_field(p, pair) for p in cmd.params),
            unreachable_reason=unreachable.get(label),
        ))
    return forms
