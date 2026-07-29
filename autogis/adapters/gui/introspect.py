"""Click-command -> form-field introspection for the unified GUI adapter.

Walks the ``autogis`` Click command tree (root group in
``autogis/adapters/cli.py``) and produces, for every leaf command, a
:class:`CommandForm` holding plain-data :class:`FormField` descriptors a GUI
can render a form from. Depends on ``click`` only — no GUI toolkit, no arcpy
(ADR-0052; the toolkit arrives in a later task per ADR-0050).

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

from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice

__all__ = ["FormField", "CommandForm", "XOR_PAIRS", "LABEL_OVERRIDES", "introspect_cli"]


# ponytail: 5 hardcoded pairs, deliberately not a constraint DSL (ADR-0052).
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


# ponytail: hand-curated label overrides, deliberately not a derived-from-type
# DSL. A repo-wide param-name survey (252 distinct names across ~130 leaf
# commands) found a cluster of cryptic Click dest names (``fmt``, ``out_dir``,
# ``sl_path``, ...) that ``.replace("_", " ").title()`` renders unreadably
# (e.g. "Sl Path", "No Dedup"). Every key below means the same thing on every
# command it appears on; names that are reused for genuinely different things
# across commands (``wells``, ``profile``, ``spec``, bare ``analytes``) are
# deliberately excluded -- one friendlier label would be wrong on one side of
# the split.
LABEL_OVERRIDES: dict[str, str] = {
    "out": "Output",
    "out_path": "Output Path",
    "out_dir": "Output Directory",
    "out_csv": "Output CSV",
    "out_xlsx": "Output Excel Workbook",
    "out_format": "Output Format",
    "output_dir": "Output Directory",
    "input_dir": "Input Directory",
    "harvest_dir": "Harvest Directory",
    "edd_dir": "EDD Directory",
    "specs_dir": "Figure Specs Directory",
    "mart_dir": "Data Mart Directory",
    "sl_path": "Screening Levels Path",
    "screening_path": "Screening Levels Path",
    "screening": "Screening Levels",
    "config_path": "Configuration Path",
    "site_config": "Site Configuration",
    "db_path": "Database Path",
    "fmt": "Format",
    "analytes_str": "Analyte List",
    "coord_format": "Coordinate Column Format",
    "gm_path": "Group Map Path",
    "wl_path": "Water Levels Path",
    "no_dedup": "Skip Deduplication",
    "anomaly_stdev": "Anomaly Std-Dev Threshold",
    "top_n": "Top N Results",
}


@dataclass(frozen=True)
class FormField:
    """One renderable form field, mapped from a ``click.Parameter``."""

    name: str  # click param name (python identifier, e.g. "wells_csv")
    label: str  # humanized name for display
    kind: str  # "text" | "int" | "float" | "flag" | "choice" | "path" | "date" | "multichoice"
    required: bool
    default: object
    choices: tuple[str, ...] | None = None  # populated for kind == "choice"
    help_text: str | None = None
    repeatable: bool = False  # click multiple=True: one value-widget, repeated
    nargs: int = 1  # click Option nargs>1 (e.g. --bbox W S E N): N whitespace-
    # separated values in one field (#351); 1 is the overwhelming common case.
    is_path_output: bool = False  # kind == "path": save picker vs open picker
    is_dir: bool = False  # kind == "path": directory-only -> folder picker
    xor_group: str | None = None  # shared id; fill one, grey its sibling
    strict: bool = True  # kind == "choice": False -> editable combo (SuggestedChoice)
    allow_time: bool = False  # kind == "date": keep timestamp-capable fields textual
    minimum: float | None = None  # kind == "int"/"float": from IntRange/FloatRange
    maximum: float | None = None


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
    is_dir = False
    strict = True
    allow_time = False
    minimum = maximum = None
    ptype = param.type
    if getattr(param, "is_flag", False):
        kind = "flag"
    elif isinstance(ptype, SuggestedChoice):
        kind = "choice"
        choices = tuple(ptype.choices)
        strict = False
    elif isinstance(ptype, CommaList):
        kind = "multichoice"
        choices = tuple(ptype.choices)
    elif isinstance(ptype, IsoDate):
        kind = "date"
        allow_time = ptype.allow_time
    elif isinstance(ptype, click.Choice):
        kind = "choice"
        choices = tuple(str(c) for c in ptype.choices)
    elif isinstance(ptype, click.Path):
        kind = "path"
        is_path_output = not ptype.exists  # heuristic; see module docstring
        # dir_okay & file_okay both default True (ambiguous, most params) --
        # only a param that opts out of files is unambiguously a folder.
        is_dir = ptype.dir_okay and not ptype.file_okay
    elif ptype.name in ("integer", "integer range"):
        # click.IntRange.name is "integer range", not "integer"; a bare
        # click.INT has no .min/.max, hence getattr(..., None).
        kind = "int"
        minimum, maximum = getattr(ptype, "min", None), getattr(ptype, "max", None)
    elif ptype.name in ("float", "float range"):
        kind = "float"
        minimum, maximum = getattr(ptype, "min", None), getattr(ptype, "max", None)
    # everything else — incl. comma-separated list options like
    # --analytes "a,b,c" — is deliberately plain text: the value passes
    # through unchanged and the option's help documents the format.

    # A file geodatabase (.gdb) *is* a directory on disk, but CLI gdb params are
    # declared inconsistently -- some bare click.Path() (file_okay left True, so
    # the generic test above can't see the folder) and some a plain
    # click.argument (STRING, e.g. upgrade-schema, which would render as a text
    # field with no Browse at all). Recognise the gdb param family by name and
    # force a folder picker for *every* tool's gdb: a directory path field whose
    # Browse opens a folder chooser, not a save-file dialog (a .gdb's internal
    # files aren't selectable there). Value passed to the CLI is unchanged.
    # Only text/path spellings: a boolean --gdb flag (reconcile-locations'
    # "also write to a gdb" toggle) is NOT a path and stays a checkbox.
    is_gdb = param.name in ("gdb", "gdb_path") or param.name.endswith("_gdb")
    if is_gdb and kind in ("text", "path"):
        kind = "path"
        is_dir = True

    xor_group = None
    if xor_pair and param.name in xor_pair:
        xor_group = "/".join(xor_pair)

    return FormField(
        name=param.name,
        label=LABEL_OVERRIDES.get(param.name, param.name.replace("_", " ").title()),
        kind=kind,
        required=bool(param.required),
        # param.default leaks Click's internal UNSET sentinel for a
        # required param with no declared default (Click >= 8.4).
        # to_info_dict()['default'] is Click's own public normalization of
        # that same value back to None -- discovered by the first GUI code
        # that actually renders .default (app.py pre-filling a text field
        # with str(UNSET) instead of leaving it blank).
        default=param.to_info_dict()["default"],
        choices=choices,
        help_text=getattr(param, "help", None),
        repeatable=bool(getattr(param, "multiple", False)),
        nargs=getattr(param, "nargs", 1) or 1,
        is_path_output=is_path_output,
        is_dir=is_dir,
        xor_group=xor_group,
        strict=strict,
        allow_time=allow_time,
        minimum=minimum,
        maximum=maximum,
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
            fields=tuple(
                _field(p, pair) for p in cmd.params
                if not getattr(p, "hidden", False)
            ),
            unreachable_reason=unreachable.get(label),
        ))
    return forms
