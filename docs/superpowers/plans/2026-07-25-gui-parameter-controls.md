# GUI Parameter Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.
>
> **Calibration** (matching `2026-07-06-gui-workflow-builder.md`, this chapter's precedent): all
> **tests** and all **crux logic** — the param types, the introspect mapping, the `_raw_values`
> dispatch, the spin-box sentinel — are given as real code. Tasks 11–14 give their tests in full
> and specify unambiguous Qt widget boilerplate in prose, because that boilerplate is mechanical
> and the tests pin its contract exactly. If a prose step is ambiguous to you, the test above it
> is the specification.

**Goal:** Make every CLI option value selectable from a UI control in `autogis-gui` instead of
typed as a string, without narrowing what the CLI accepts today.

**Architecture:** Three custom `click.ParamType`s carry **UI intent without changing the value** —
each validates (or merely annotates) and returns the **original string unchanged**, so every
existing command body receives exactly what it receives now. `gui/introspect.py` reads those types
and reports new field kinds; `gui/app.py` renders them. Click stays the single source of truth and
no vocabulary is hardcoded in the GUI. **PR1** = the param types + `cli.py` declarations + one
`app.py` line. **PR2** = the Qt controls.

**Tech Stack:** Python 3.14 (CI: 3.11), Click 8.4.1, PySide6 (`gui` optional extra), pytest with
Qt's `offscreen` platform plugin.

**Spec:** `docs/superpowers/specs/2026-07-25-gui-parameter-controls-design.md`

## Global Constraints

- `core/` and `adapters/` must import with **neither `arcpy` nor `arcgis` present**. Everything
  here is arcpy-free; ADR-0077 doc-verification does **not** apply (no `toolbox.pyt` changes).
- **A change must never reject a value that works today.** This is the constraint that reshaped the
  whole plan — 7 of 9 candidate dropdowns and all 16 candidate `click.DateTime` swaps were rejected
  for violating it. When in doubt, annotate; do not restrict.
- **Every param type in `param_types.py` returns the input string unchanged.** No command body in
  this plan changes. If you find yourself editing a command body, stop — you have picked the wrong
  mechanism.
- Ponytail (full): laziest correct solution; reuse before writing; stdlib/native before new
  dependencies. Mark deliberate ceilings with a `ponytail:` comment naming the upgrade path.
- **`main` is READ-ONLY.** Work on branch `worktree-feat-gui-param-controls` in worktree
  `C:\Users\ichbi\AutoGIS\.claude\worktrees\feat-gui-param-controls`.
- **`_rebuild_form` must keep producing exactly one `QFormLayout` row per field**
  (`tests/test_gui_app.py:280`, `:289` assert `rowCount() == len(form.fields)`). Composite controls
  go inside one container widget added with a single `addRow()` call.
- **A `kind == "flag"` field must keep being added *directly*** — `addRow(label_text, checkbox)`,
  never wrapped in a container. `tests/test_gui_app.py:292-303` calls `labelForField(checkbox)`,
  which returns `None` for a wrapped widget and fails with `AttributeError`.
- **Blank means unset.** `forms.py::_normalize` maps blank → `None` → option omitted. Any control
  that cannot express blank must provide an explicit state that maps back to `None`.
- Tests: offscreen Qt, real widgets, never mock Qt. Hermetic `QSettings` — a bare `MainWindow()`
  pollutes the real registry (`tests/test_gui_app.py:59-66` `_isolate_qsettings`).
- Suite command (the `PYTHONPATH` is mandatory; without it ~13 `test_gui_executor` subprocess tests
  fail spuriously):
  ```
  cd "C:/Users/ichbi/AutoGIS/.claude/worktrees/feat-gui-param-controls" && \
  PYTHONPATH="C:/Users/ichbi/AutoGIS/.claude/worktrees/feat-gui-param-controls" python -m pytest -q
  ```
  **CI is authoritative for pass/fail** — it is the only environment that verifies the
  arcpy/arcgis-free invariant.
- Every task ends with a commit whose message ends with the repo's standard trailers.

## Scope corrections from the derivation pass (read before starting)

The spec was written before per-option verification. These supersede it:

| Spec said | Reality | Why |
|---|---|---|
| 5 constrained options → `click.Choice` | **2** get `Choice`; 3 get `SuggestedChoice` | `KNOWN_MATRICES` = `{"GW","SOIL"}` is a *figure-spec* vocabulary; `nysdec.yaml:75-81` maps to `SED` and a test uses `AIR`. `UNIT_REGISTRY` deliberately omits `ppb`/`ppm` (`units.py:3-7`) and a strict Choice rejects `µg/L` spelled with U+00B5 vs U+03BC. |
| 4 tool-name options → `click.Choice` | **4** get `SuggestedChoice` | Restricting refuses `--required-tool agol-promote` (the only string matching an `agol promote` run) and makes `run-history --tool` unable to query a row written by a since-renamed command. |
| 16 date options → `click.DateTime` | **16** get `IsoDate` | All 16 break under `DateTime` — the bodies call `date.fromisoformat(...)` on what would become a `datetime`. One fails *silently*: `estimate-gw-flow-direction` would write `2026-07-01 00:00:00` into a CSV cell. |
| ~18 numeric bounds | **46 of 54** justified; only **2** get a maximum | 10 strong (help text or body states it), 33 dimensional min-only, 3 weak (owner call). 8 get none — `--known-elevation`, `--anchor-x/y`, `--start`, `--end`, `--bbox` are legitimately negative or `nargs>1`. |
| 10 folder params | **12**, all verified real directories | Enumerated live; 0 ambiguous. |

Unchanged: the 4 comma-list checklists, the 110 missing `help=` strings, the tooltip line.

**Excluded deliberately:** `agol update-webmap --event-date` (`cli.py:3127`) is a `{event_date}`
template token with `default=""`. Verified: a date type plus `default=""` fails at **parse** time
even when the option is never passed. Do not touch it.

---

# PR1 — Declare the types

### Task 1: Create the param-types module

**Files:**
- Create: `autogis/adapters/param_types.py`
- Test: `tests/test_param_types.py`

**Interfaces:**
- Consumes: `click` only.
- Produces (Tasks 2, 4, 5, 6 rely on these exact names):
  - `CommaList(vocabulary: Iterable[str], *, case_sensitive: bool = True)` — attr `.choices: tuple[str, ...]`
  - `SuggestedChoice(values: Iterable[str])` — attr `.choices: tuple[str, ...]`
  - `IsoDate(*, allow_time: bool = False)` — attr `.allow_time: bool`
  - All three: `.convert()` returns the **original `str`**.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_param_types.py
"""Every type here must return the input string UNCHANGED -- that is the whole
point (no command body changes). These tests exist to pin that contract."""
import click
import pytest

from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice


def _convert(param_type, value):
    return param_type.convert(value, None, None)


class TestCommaList:
    VOCAB = ("nondetects", "rpd_sheet", "blanks")

    def test_returns_original_string_unchanged(self):
        t = CommaList(self.VOCAB)
        assert _convert(t, "nondetects,rpd_sheet") == "nondetects,rpd_sheet"

    def test_preserves_whitespace_and_order_verbatim(self):
        # The bodies do their own .split(",")/.strip(); we must not pre-chew it.
        t = CommaList(self.VOCAB)
        assert _convert(t, " nondetects , blanks ") == " nondetects , blanks "

    def test_empty_string_is_allowed(self):
        # Several of these options default to "".
        assert _convert(CommaList(self.VOCAB), "") == ""

    def test_unknown_element_fails_and_names_the_legal_values(self):
        t = CommaList(self.VOCAB)
        with pytest.raises(click.BadParameter) as exc:
            _convert(t, "nondetects,typo_feature")
        msg = str(exc.value)
        assert "typo_feature" in msg
        assert "nondetects" in msg and "rpd_sheet" in msg

    def test_case_insensitive_mode_accepts_other_casing(self):
        t = CommaList(("GW", "SOIL"), case_sensitive=False)
        assert _convert(t, "gw,soil") == "gw,soil"  # unchanged, still accepted

    def test_choices_attribute_exposes_vocabulary(self):
        assert CommaList(self.VOCAB).choices == self.VOCAB


class TestSuggestedChoice:
    def test_accepts_a_known_value(self):
        assert _convert(SuggestedChoice(("GW", "SOIL")), "GW") == "GW"

    def test_accepts_an_UNKNOWN_value_unchanged(self):
        # This is the entire reason this type exists instead of click.Choice.
        assert _convert(SuggestedChoice(("GW", "SOIL")), "SED") == "SED"

    def test_choices_attribute_exposes_suggestions(self):
        assert SuggestedChoice(("GW", "SOIL")).choices == ("GW", "SOIL")


class TestIsoDate:
    def test_returns_original_string_unchanged(self):
        assert _convert(IsoDate(), "2026-07-25") == "2026-07-25"

    def test_rejects_a_malformed_date(self):
        with pytest.raises(click.BadParameter):
            _convert(IsoDate(), "25-07-2026")

    def test_date_only_mode_rejects_a_timestamp(self):
        with pytest.raises(click.BadParameter):
            _convert(IsoDate(), "2026-07-25T10:30:00")

    def test_allow_time_mode_accepts_a_timestamp(self):
        # run-history --since calls datetime.fromisoformat today, so narrowing
        # it to date-only would reject a value that works.
        t = IsoDate(allow_time=True)
        assert _convert(t, "2026-07-25T10:30:00") == "2026-07-25T10:30:00"

    def test_allow_time_mode_still_accepts_a_bare_date(self):
        assert _convert(IsoDate(allow_time=True), "2026-07-25") == "2026-07-25"
```

- [ ] **Step 2: Run it to verify it fails**

Run:
```
PYTHONPATH="$PWD" python -m pytest tests/test_param_types.py -q
```
Expected: collection error — `ModuleNotFoundError: No module named 'autogis.adapters.param_types'`

- [ ] **Step 3: Write the implementation**

```python
# autogis/adapters/param_types.py
"""Click parameter types that carry UI intent without changing the value.

Every type here validates (or merely annotates) its input and returns the
**original string unchanged**, so each command body keeps receiving exactly
what it receives today -- no body in the repo changes because of this module.
The value added is metadata: ``gui/introspect.py`` reads these types to decide
which control to render (checklist, editable dropdown, calendar), and the CLI
gains a parse-time error instead of a downstream surprise.

Why ``SuggestedChoice`` instead of ``click.Choice``: Choice *restricts*, and
several AutoGIS vocabularies are open in practice. ``KNOWN_MATRICES`` is
``{"GW", "SOIL"}`` but is a figure-spec vocabulary -- config/lab_profiles/
nysdec.yaml maps to ``SED``. ``UNIT_REGISTRY`` deliberately omits ppb/ppm
(units.py:3-7) yet legacy workbooks use them. Tool-name filters must still
match rows in an old run_history.csv written by a since-renamed command.
Restricting any of those would refuse input the CLI accepts today.

Why ``IsoDate`` instead of ``click.DateTime``: DateTime hands the body a
``datetime`` object. All 16 date options in cli.py call
``date.fromisoformat(...)`` on the value, which raises TypeError on a datetime;
one (``estimate-gw-flow-direction``) fails *silently* by writing
"2026-07-01 00:00:00" into a CSV cell. Validating the string and passing it
through keeps every call site working untouched.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import click

__all__ = ["CommaList", "IsoDate", "SuggestedChoice"]


class SuggestedChoice(click.ParamType):
    """Offers a known vocabulary to the GUI but accepts ANY value.

    Renders as an *editable* combo box: pick a suggestion or type your own.
    Deliberately performs no validation -- see the module docstring.
    """

    name = "text"  # stays 'text' so nothing downstream re-types it

    def __init__(self, values: Iterable[str]):
        self.choices: tuple[str, ...] = tuple(values)

    def convert(self, value, param, ctx):
        return value

    def get_metavar(self, param, ctx=None):  # pragma: no cover - cosmetic
        return "TEXT"


class CommaList(click.ParamType):
    """A comma-joined subset of a CLOSED vocabulary.

    Keeps the existing CLI contract exactly -- still ``--features a,b`` -- and
    returns the original string, because each consuming body does its own
    ``.split(",")`` with its own strip/dedupe/case rules.
    """

    name = "commalist"

    def __init__(self, vocabulary: Iterable[str], *, case_sensitive: bool = True):
        self.choices: tuple[str, ...] = tuple(vocabulary)
        self.case_sensitive = case_sensitive

    def convert(self, value, param, ctx):
        if value is None or value == "":
            return value  # several options default to ""; blank means "none"
        haystack = (self.choices if self.case_sensitive
                    else tuple(c.casefold() for c in self.choices))
        for element in value.split(","):
            element = element.strip()
            if not element:
                continue  # bodies already tolerate blanks; don't get stricter
            probe = element if self.case_sensitive else element.casefold()
            if probe not in haystack:
                self.fail(
                    f"{element!r} is not one of "
                    f"{', '.join(repr(c) for c in self.choices)}.",
                    param, ctx)
        return value


class IsoDate(click.ParamType):
    """An ISO date, validated but returned as the original string.

    ``allow_time`` mirrors what the consuming body actually parses: most call
    sites use ``date.fromisoformat`` (date only), but ``run-history --since``
    uses ``datetime.fromisoformat`` and must keep accepting a full timestamp.
    """

    name = "isodate"

    def __init__(self, *, allow_time: bool = False):
        self.allow_time = allow_time

    def convert(self, value, param, ctx):
        if value is None or value == "":
            return value
        parser = datetime.fromisoformat if self.allow_time else date.fromisoformat
        try:
            parser(value)
        except (TypeError, ValueError):
            want = ("an ISO date or timestamp (YYYY-MM-DD[THH:MM:SS])"
                    if self.allow_time else "an ISO date (YYYY-MM-DD)")
            self.fail(f"{value!r} is not {want}.", param, ctx)
        return value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```
PYTHONPATH="$PWD" python -m pytest tests/test_param_types.py -q
```
Expected: `14 passed`

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/param_types.py tests/test_param_types.py
git commit -m "feat(cli): param types carrying UI intent without changing the value

CommaList, SuggestedChoice and IsoDate each validate (or merely annotate)
their input and return the ORIGINAL STRING, so no command body changes.
introspect.py will read them to pick a control.

SuggestedChoice exists instead of click.Choice because several vocabularies
are open in practice (SED/AIR matrix codes, ppb/ppm units, renamed tool names
in an old run_history.csv). IsoDate exists instead of click.DateTime because
all 16 date call sites parse the string themselves.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Teach introspect.py the three types

**Files:**
- Modify: `autogis/adapters/gui/introspect.py` (`FormField`, `_field`)
- Test: `tests/test_gui_introspect.py`

**Interfaces:**
- Consumes: `CommaList`, `SuggestedChoice`, `IsoDate` from Task 1.
- Produces (PR2 relies on these exactly):
  - `FormField.kind` gains `"date"` and `"multichoice"`.
  - `FormField.strict: bool = True` — `False` means an *editable* combo.
  - `FormField.minimum: float | int | None = None`, `FormField.maximum: float | int | None = None`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gui_introspect.py
import click

from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice
from autogis.adapters.gui.introspect import introspect_cli


def _only_field(param_decls, **kw):
    """Build a one-option command and return its non-help FormField."""
    @click.group()
    def root():
        pass

    @root.command("probe")
    @click.option(*param_decls, **kw)
    def probe(**_):
        pass

    form = next(f for f in introspect_cli(root) if f.path == ("probe",))
    return form.fields[0]


def test_comma_list_becomes_multichoice_with_choices():
    f = _only_field(["--features"], type=CommaList(("a", "b")), default="")
    assert f.kind == "multichoice"
    assert f.choices == ("a", "b")


def test_suggested_choice_is_a_non_strict_choice():
    f = _only_field(["--matrix"], type=SuggestedChoice(("GW", "SOIL")))
    assert f.kind == "choice"
    assert f.choices == ("GW", "SOIL")
    assert f.strict is False


def test_plain_click_choice_stays_strict():
    f = _only_field(["--fmt"], type=click.Choice(["a", "b"]))
    assert f.kind == "choice"
    assert f.strict is True


def test_iso_date_becomes_date_kind():
    f = _only_field(["--event-date"], type=IsoDate())
    assert f.kind == "date"


def test_int_range_exposes_bounds():
    f = _only_field(["--limit"], type=click.IntRange(min=0, max=99))
    assert f.kind == "int"
    assert (f.minimum, f.maximum) == (0, 99)


def test_unbounded_int_has_no_bounds():
    f = _only_field(["--limit"], type=int)
    assert (f.minimum, f.maximum) == (None, None)
```

Also update the existing kinds guard — find the `KINDS` set at `tests/test_gui_introspect.py:7`
and extend it:

```python
KINDS = {"text", "int", "float", "flag", "choice", "path", "date", "multichoice"}
```

- [ ] **Step 2: Run it to verify it fails**

Run:
```
PYTHONPATH="$PWD" python -m pytest tests/test_gui_introspect.py -q
```
Expected: FAIL — `AttributeError: 'FormField' object has no attribute 'strict'`

- [ ] **Step 3: Write the implementation**

In `autogis/adapters/gui/introspect.py`, add the import near the top:

```python
from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice
```

Add three fields to the `FormField` dataclass (after `xor_group`, so existing positional
construction is unaffected):

```python
    strict: bool = True  # kind == "choice": False -> editable combo (SuggestedChoice)
    minimum: float | None = None  # kind == "int"/"float": from IntRange/FloatRange
    maximum: float | None = None
```

In `_field`, insert these branches **before** the existing `isinstance(ptype, click.Choice)`
check (`SuggestedChoice` is not a Choice subclass, but keeping the custom types first makes the
precedence explicit), and capture the numeric bounds:

```python
    strict = True
    minimum = maximum = None
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
    elif isinstance(ptype, click.Choice):
        kind = "choice"
        choices = tuple(str(c) for c in ptype.choices)
    elif isinstance(ptype, click.Path):
        ...unchanged...
    elif ptype.name in ("integer", "integer range"):
        kind = "int"
        minimum, maximum = getattr(ptype, "min", None), getattr(ptype, "max", None)
    elif ptype.name in ("float", "float range"):
        kind = "float"
        minimum, maximum = getattr(ptype, "min", None), getattr(ptype, "max", None)
```

and pass `strict=strict, minimum=minimum, maximum=maximum` into the returned `FormField`.

> **The range names are load-bearing.** Verified against Click 8.4.1: `click.IntRange().name` is
> `"integer range"`, not `"integer"` (`FloatRange` → `"float range"`). The pre-existing
> `elif ptype.name == "integer"` test therefore does **not** match a range type — every one of
> Task 7's 46 bounded options would silently fall through to `kind="text"` and render as a plain
> line edit instead of a spin box. This is harmless on today's `main` only because 0 of 54 numeric
> options currently use a range type.
>
> `click.IntRange`/`FloatRange` carry `.min`/`.max`; a bare `int`/`float` type does not, hence
> `getattr(..., None)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```
PYTHONPATH="$PWD" python -m pytest tests/test_gui_introspect.py tests/test_gui_app.py -q
```
Expected: all pass. `test_gui_app.py` must be green **unchanged** — PR1 adds no widgets, and
`_rebuild_form`'s `else` branch renders `date`/`multichoice` as today's `QLineEdit`.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/gui/introspect.py tests/test_gui_introspect.py
git commit -m "feat(gui): introspect the new param types into field kinds

FormField gains kind 'date' and 'multichoice', a strict flag (False -> editable
combo for SuggestedChoice), and minimum/maximum read off IntRange/FloatRange.
app.py is untouched: its else-branch still renders unknown kinds as a line edit,
so this commit changes no visible behavior.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Surface every option's help as a tooltip (closes #356)

**Files:**
- Modify: `autogis/adapters/gui/app.py` (`_rebuild_form`, after the widget if/elif chain)
- Test: `tests/test_gui_app.py`

**Why this is its own task:** it is one line, it is the highest value-per-character change in the
plan, and it is the only `app.py` edit in PR1. Today help text reaches the screen for **no** flag
or choice field, and `setPlaceholderText` at `app.py:388-389` is a dead no-op for ~50 fields
because `setText(default)` at `:386-387` runs first and Qt only paints a placeholder when the
line edit is empty.

- [ ] **Step 1: Write the failing test**

```python
def test_every_field_widget_gets_its_help_as_a_tooltip(qapp):
    win = MainWindow()
    # envmon run-history has a flag-free mix incl. a choice with help text.
    win._command_box.setCurrentText("envmon run-history")
    form = win._forms["envmon run-history"]
    for field in form.fields:
        if not field.help_text:
            continue
        assert win._field_widgets[field.name].toolTip() == field.help_text, field.name


def test_tooltip_reaches_choice_and_flag_widgets(qapp):
    """Regression for #356: the choice/flag branches never touched help_text."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    status = win._field_widgets["status"]          # QComboBox, has help
    assert status.toolTip() == "Filter by run status."
```

- [ ] **Step 2: Run it to verify it fails**

Run:
```
PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q -k tooltip
```
Expected: FAIL — `assert '' == 'Filter by run status.'`

- [ ] **Step 3: Write the implementation**

In `_rebuild_form`, immediately after the `if/elif/else` widget chain closes (i.e. after the
current line 389 `widget.setPlaceholderText(field.help_text)`) and **before** the `label_text`
assignment, add:

```python
            # Help reaches the screen for EVERY kind, not just line edits: the
            # flag/choice branches never set it, and setPlaceholderText above is
            # a no-op whenever a default was already written into the field (#356).
            if field.help_text:
                widget.setToolTip(field.help_text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```
PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "fix(gui): show every option's help as a tooltip

Closes #356. The flag and choice branches never touched help_text, and
setPlaceholderText is a no-op for any field whose default was already written
into it -- so ~117 fields had help the user could never see.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: CommaList on the 4 closed-vocabulary options (closes #354, #355)

**Files:**
- Modify: `autogis/adapters/cli.py` lines `949-950`, `3278-3282`, `3356-3360`, `5017-5019`
- Test: `tests/test_param_types_cli.py` (create)

**Interfaces:** consumes `CommaList` (Task 1). Vocabularies, all verified present:
`MESSINESS` (`core/envmon/synthetic_workbook.py:18-21`), `_EXTRA_COLUMN_VOCAB`
(`core/envmon/import_rtk_survey.py:61-64`), `IntervalTier` (`core/envmon/soil_interval_selector.py:29-33`).

**Case rules differ per option and must be preserved** — `cli.py:959` and `:3296`/`:3369` are
case-sensitive; `cli.py:5033` upper-cases before comparing, so `--tiers` takes
`case_sensitive=False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_param_types_cli.py
"""#354 and #355 are the acceptance tests for the CommaList declarations: a
typo'd element must now be a clean usage error naming the legal values, rather
than a silent empty output or a raw traceback."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_bad_tiers_is_a_usage_error_not_a_silent_empty_file(tmp_path):
    """Closes #354: --tiers HOTSPT used to exit 0 with a header-only CSV."""
    src = tmp_path / "in.csv"
    src.write_text("LocationID,Top,Bottom,Result\nB-1,0,5,1.0\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--input", str(src), "--out", str(tmp_path / "o.csv"),
        "--tiers", "HOTSPT",
    ])
    assert res.exit_code == 2, res.output
    assert "HOTSPT" in res.output
    assert "HOTSPOT" in res.output  # the legal values are listed


def test_bad_features_is_a_usage_error_not_a_traceback(tmp_path):
    """Closes #355: --features typo used to raise a raw ValueError."""
    res = CliRunner().invoke(autogis, [
        "envmon", "gen-synthetic-workbook",
        "--out", str(tmp_path / "wb.xlsx"),
        "--features", "nondetects,typo_feature",
    ])
    assert res.exit_code == 2, res.output
    assert "typo_feature" in res.output
    assert "Traceback" not in res.output


def test_valid_tiers_still_works(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("LocationID,Top,Bottom,Result\nB-1,0,5,1.0\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--input", str(src), "--out", str(tmp_path / "o.csv"),
        "--tiers", "HOTSPOT",
    ])
    assert res.exit_code == 0, res.output
```

> Before writing the assertions, run `python -c "from autogis.core.envmon.soil_interval_selector
> import IntervalTier; print(IntervalTier)"` and use the **real** tier names in place of
> `HOTSPOT`. Do not guess them.

- [ ] **Step 2: Run it to verify it fails**

Run:
```
PYTHONPATH="$PWD" python -m pytest tests/test_param_types_cli.py -q
```
Expected: FAIL — exit code is 0 (the #354 silent-success bug) / a traceback (#355).

- [ ] **Step 3: Write the implementation**

Add near `cli.py`'s existing module imports (lines 1-14):

```python
from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice
```

Then add `type=` to each of the four options, leaving every other argument untouched:

- `cli.py:949-950` `--features` → `type=CommaList(MESSINESS)`
- `cli.py:3278-3282` `--extra-columns` → `type=CommaList(_EXTRA_COLUMN_VOCAB)`
- `cli.py:3356-3360` `--extra-columns` → `type=CommaList(_EXTRA_COLUMN_VOCAB)`
- `cli.py:5017-5019` `--tiers` → `type=CommaList(<IntervalTier values>, case_sensitive=False)`

Import each vocabulary at module level alongside the param types. Per the derivation, this costs
0.0042 s and adds 5 modules, with no cycle in either direction — `capabilities` is already loaded
transitively via `guard.py:16`.

**Do not remove the existing body checks.** They also serve non-CLI callers and, in
`soil_interval_selector.py:96-97`, do the actual filtering work.

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```
PYTHONPATH="$PWD" python -m pytest tests/test_param_types_cli.py tests/envmon -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/test_param_types_cli.py
git commit -m "fix(cli): declare the 4 closed-vocabulary comma options

Closes #354, closes #355. --features/--extra-columns/--tiers now validate each
comma element at parse time and name the legal values, instead of exiting 0
with an empty file (#354) or raising a raw ValueError traceback (#355).

The CLI contract is unchanged -- still --features a,b -- and each body keeps
its own split/strip/case handling because CommaList returns the string as-is.
The GUI gets a checklist for free once PR2 lands.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Dropdowns — 2 strict, 7 suggesting

**Files:**
- Modify: `autogis/adapters/cli.py` at `3931-3932`, `4904` (strict) and `5293`, `5294`,
  `5527-5530`, `5531-5533`, `709-710`, `736-737`, `1568`, `3391` (suggesting)
- Test: `tests/test_param_types_cli.py`

**The two strict ones** (verified: the body already validates against exactly this set, so no
working value is lost):
- `download-dem --dataset` → `click.Choice(tuple(DEM_DATASETS), case_sensitive=False)` plus
  `metavar="CODE"`. **Without the metavar, Click prints all 17 codes lowercased in `--help`.**
  Note `tests/envmon/test_cli_download_dem.py:46-52` asserts a difflib "did you mean" hint that
  Click's own error replaces — **that test must be rewritten in this commit**.
- `list-tools --domain` → `click.Choice(sorted({t.domain for t in TOOL_REGISTRY}),
  case_sensitive=False)`. Derive it from the registry, never hardcode, so a new domain can't
  desync. Its two sibling options on the same command are already `Choice` — this closes the gap.

**The seven suggesting ones** — `SuggestedChoice(...)`, which offers the list to the GUI and
refuses nothing:
- `migrate-legacy-data --default-matrix`, `build-conc-surface --matrix` →
  `SuggestedChoice(sorted(KNOWN_MATRICES) + ["SED", "SW"])`
- `migrate-legacy-data --default-units`, `build-conc-surface --unit` →
  `SuggestedChoice(sorted(UNIT_REGISTRY))`
- `evaluate-readiness --required-tool`, `portfolio-metrics --required-tool`,
  `run-history --tool`, `register-source-doc --tool` →
  `SuggestedChoice(sorted(t.name for t in TOOL_REGISTRY))`

- [ ] **Step 1: Write the failing test**

```python
def test_unknown_dataset_is_a_usage_error():
    res = CliRunner().invoke(autogis, ["envmon", "download-dem", "--dataset", "NOPE",
                                       "--bbox", "-105", "39", "-104", "40",
                                       "--out", "x.tif", "--dry-run"])
    assert res.exit_code == 2
    assert "NOPE" in res.output


def test_suggested_matrix_still_accepts_an_unlisted_code(tmp_path):
    """The whole point of SuggestedChoice: SED is real (nysdec.yaml) but is not
    in KNOWN_MATRICES, and must keep working."""
    src = tmp_path / "legacy.csv"
    src.write_text("LocationID,Analyte,Result\nB-1,Benzene,1.0\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, [
        "envmon", "migrate-legacy-data", "--input", str(src),
        "--out", str(tmp_path / "o.csv"), "--default-matrix", "SED",
    ])
    assert res.exit_code == 0, res.output


def test_run_history_tool_filter_accepts_a_retired_tool_name(tmp_path):
    """A log query must still be able to name a command that no longer exists."""
    hist = tmp_path / "run_history.csv"
    hist.write_text("timestamp,site_id,tool_name,status,message\n"
                    "2026-01-01T00:00:00,S1,a-retired-tool,success,ok\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "run-history",
                                       "--history-path", str(hist),
                                       "--tool", "a-retired-tool"])
    assert res.exit_code == 0, res.output
    assert "a-retired-tool" in res.output
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$PWD" python -m pytest tests/test_param_types_cli.py -q`
Expected: the `--dataset` test fails (exit 1, not 2); the other two pass already and are
**regression guards** — they must still pass after Step 3. If either goes red in Step 4, the
`SuggestedChoice` wiring is wrong.

- [ ] **Step 3: Write the implementation**

Apply the nine `type=` additions listed above. Import `DEM_DATASETS`, `DEFAULT_DATASET`,
`KNOWN_MATRICES`, `UNIT_REGISTRY`, `TOOL_REGISTRY` at module level.

Then rewrite `tests/envmon/test_cli_download_dem.py:46-52` — the difflib hint is now Click's
choice list:

```python
def test_unknown_dataset_lists_the_valid_codes():
    res = CliRunner().invoke(autogis, ["envmon", "download-dem", "--dataset", "usgs10",
                                       "--bbox", "-105", "39", "-104", "40",
                                       "--out", "x.tif", "--dry-run"])
    assert res.exit_code == 2
    assert "usgs10m" in res.output.lower()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$PWD" python -m pytest tests/ -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/
git commit -m "feat(cli): declare dropdown vocabularies (2 strict, 7 suggesting)

--dataset and --domain become click.Choice: their bodies already validate
against exactly these sets, so no working value is lost.

The other seven become SuggestedChoice, which offers the vocabulary to the GUI
but refuses nothing -- restricting them would reject values that work today:
SED/AIR matrix codes (nysdec.yaml), ppb/ppm units that UNIT_REGISTRY omits by
design, and tool names in an old run_history.csv written by a since-renamed
command.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: IsoDate on the 16 date options

**Files:**
- Modify: `autogis/adapters/cli.py` at `780`, `812`, `857`, `913`, `1016`, `1141`, `1574`,
  `2152`, `2860`, `3176`, `4030`, `4612`, `5210`, `5336`, `5339`, `5520`
- Test: `tests/test_param_types_cli.py`

**Every one takes `IsoDate()` except `run-history --since` (`cli.py:1574`), which takes
`IsoDate(allow_time=True)`** — verified at `cli.py:1591`, it calls `datetime.fromisoformat`, so
date-only validation would reject a timestamp that works today.

**Do NOT touch `agol update-webmap --event-date` (`cli.py:3127`).** It is a `{event_date}`
template token with `default=""`; a date type plus that default fails at parse time even when the
option is never passed.

**No command body changes.** If a test failure tempts you to edit one, the wiring is wrong.

- [ ] **Step 1: Write the failing test**

```python
def test_malformed_event_date_is_a_usage_error(tmp_path):
    res = CliRunner().invoke(autogis, ["envmon", "gw-level-summary",
                                       "--event-date", "25-07-2026"])
    assert res.exit_code == 2
    assert "25-07-2026" in res.output


def test_since_still_accepts_a_full_timestamp(tmp_path):
    """cli.py:1591 uses datetime.fromisoformat -- narrowing to date-only would
    reject a value that works today."""
    hist = tmp_path / "run_history.csv"
    hist.write_text("timestamp,site_id,tool_name,status,message\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "run-history",
                                       "--history-path", str(hist),
                                       "--since", "2026-07-01T10:30:00"])
    assert res.exit_code == 0, res.output


def test_all_sixteen_date_options_are_isodate():
    """Guard against a future option being added as bare text."""
    from autogis.adapters.param_types import IsoDate
    from autogis.adapters.gui.introspect import introspect_cli
    dated = [(f.label, x.name) for f in introspect_cli() for x in f.fields
             if x.kind == "date"]
    assert len(dated) == 16, dated
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$PWD" python -m pytest tests/test_param_types_cli.py -q -k date`
Expected: FAIL — malformed date currently exits 1 with a `ValueError`-derived message, and the
count assertion reports 0.

- [ ] **Step 3: Write the implementation**

Add `type=IsoDate()` to the 15, and `type=IsoDate(allow_time=True)` to `cli.py:1574`. Change
nothing else on any of those lines.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$PWD" python -m pytest tests/ -q`
Expected: full suite green — **no body changed**, so every existing date test still passes.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/test_param_types_cli.py
git commit -m "feat(cli): validate the 16 ISO date options without changing their type

IsoDate validates the format and returns the same string, so all 16 command
bodies keep receiving a str and none of them change. click.DateTime was
rejected: it hands the body a datetime where the code calls
date.fromisoformat(), and one site (estimate-gw-flow-direction) would fail
SILENTLY by writing '2026-07-01 00:00:00' into a CSV cell.

--since takes allow_time=True because cli.py:1591 parses it with
datetime.fromisoformat and must keep accepting a full timestamp.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Numeric bounds and folder pickers (closes #353)

**Files:**
- Modify: `autogis/adapters/cli.py` (46 numeric options, 12 path options)
- Test: `tests/test_param_types_cli.py`

**Numeric bounds — evidence-only.** 46 of 54 are justifiable; **only 2 get a maximum** (the two
fuzzy-match `--threshold` options, capped at `1.0` because `difflib.SequenceMatcher.ratio()` is
documented to return `[0.0, 1.0]`). The other 44 are **minimum-only**. Do **not** invent a maximum
— an unjustified ceiling is a bug that rejects a legitimate value.

Leave these 8 unbounded: `--known-elevation`, `--anchor-x`, `--anchor-y` (legitimately negative),
`--start`, `--end`, `--bbox` (coordinates, and `nargs>1`), plus the 2 remaining flagged weak.

Treat `--turnaround`, `--cell-size`, `--max-depth-ft` as **owner questions, not edits** — note
them in the PR description and leave them alone. `--cell-size` in particular currently treats `0`
as "auto" by accident of `cell_size or ...` truthiness, so `IntRange(min=1)` would change behavior.

**Folder pickers — 12 params**, all verified real directories (the body `mkdir`s them or writes
several files into them). Add `file_okay=False` to each bare `click.Path()`.

- [ ] **Step 1: Write the failing test**

```python
def test_negative_limit_is_a_usage_error(tmp_path):
    hist = tmp_path / "h.csv"
    hist.write_text("timestamp,site_id,tool_name,status,message\n", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "run-history",
                                       "--history-path", str(hist), "--limit", "-5"])
    assert res.exit_code == 2


def test_directory_params_reject_an_existing_file(tmp_path):
    """#353: a bare click.Path() accepted a FILE for a directory param."""
    afile = tmp_path / "not-a-dir.txt"
    afile.write_text("x", encoding="utf-8")
    res = CliRunner().invoke(autogis, ["envmon", "export-wqx",
                                       "--results", str(afile),
                                       "--out-dir", str(afile)])
    assert res.exit_code == 2
    assert "directory" in res.output.lower() or "file" in res.output.lower()


# Populate from the Step-3 derivation command below. MUST contain exactly 12
# entries -- a name-suffix heuristic is NOT good enough here, because several of
# the 12 are not named *_dir and would be silently skipped.
FOLDER_PARAMS = [
    # ("envmon export-wqx", "out_dir"),  <- replace with the derived 12
]


def test_the_twelve_folder_params_are_declared_dir_only():
    from autogis.adapters.gui.introspect import introspect_cli
    assert len(FOLDER_PARAMS) == 12, "derive the real list; do not guess"
    forms = {f.label: f for f in introspect_cli()}
    for label, dest in FOLDER_PARAMS:
        field = next(x for x in forms[label].fields if x.name == dest)
        assert field.is_dir is True, f"{label} --{dest} still accepts a file"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$PWD" python -m pytest tests/test_param_types_cli.py -q -k "limit or dir"`
Expected: FAIL — `--limit -5` exits 0 today; the `*_dir` guard lists 12 leaks.

- [ ] **Step 3: Write the implementation**

Apply `click.IntRange(min=...)` / `click.FloatRange(min=...)` to the 46, and `file_okay=False`
to the 12 `click.Path()` declarations. Re-derive the exact 46 and 12 with:

```
PYTHONPATH="$PWD" python -c "
import click
from autogis.adapters.cli import autogis as r
def walk(g,p=()):
    for n,c in g.commands.items():
        q=p+(n,)
        yield from (walk(c,q) if isinstance(c,click.Group) else [(q,c)])
for path,cmd in walk(r):
    for x in cmd.params:
        t=x.type
        if t.name in ('integer','float') and not hasattr(t,'min'):
            print('NUM', ' '.join(path), x.opts, x.default)
        if isinstance(t,click.Path) and t.file_okay and t.dir_okay and x.name.endswith('_dir'):
            print('DIR', ' '.join(path), x.opts)
"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$PWD" python -m pytest tests/ -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/test_param_types_cli.py
git commit -m "fix(cli): evidence-based numeric bounds and dir-only folder params

Closes #353. 12 directory params were bare click.Path(), so Click accepted a
file for them and the GUI Browse button opened a save-FILE dialog with an
overwrite warning for a directory the tool mkdirs.

46 of 54 numeric options gain a bound; only 2 gain a MAXIMUM (the fuzzy-match
thresholds, since SequenceMatcher.ratio() is documented as [0.0, 1.0]). The
rest are minimum-only -- an unjustified ceiling would reject a legitimate
value. 8 stay unbounded (coordinates and elevations are legitimately negative).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

# PR2 — Render the controls

> **Branch from PR1.** Every task below is `gui/`-only.

### Task 8: Guard `_raw_values` before adding any new widget

**Files:**
- Modify: `autogis/adapters/gui/app.py` (`_raw_values`, `:424-433`)
- Test: `tests/test_gui_app.py`

**This task must come first.** `_raw_values`'s `else` branch calls `.text()`, and `QSpinBox`,
`QDoubleSpinBox` and `QDateEdit` **all inherit `.text()`**. Adding any of them without fixing this
first silently ships `"(use default)"` or a locale-formatted `"0,800"` to the child process. Doing
the guard first turns that silent corruption into an explicit, tested dispatch.

- [ ] **Step 1: Write the failing test**

```python
def test_raw_values_rejects_an_unknown_widget_type(qapp):
    """A widget class nobody taught _raw_values about must fail loudly, not
    fall through to .text() and ship whatever string Qt happens to render."""
    from PySide6.QtWidgets import QSpinBox
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    win._field_widgets["limit"] = QSpinBox()  # not yet handled
    with pytest.raises(TypeError, match="QSpinBox"):
        win._raw_values()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q -k raw_values`
Expected: FAIL — no exception raised; `.text()` returns `"0"`.

- [ ] **Step 3: Write the implementation**

Replace `_raw_values`'s body with an explicit dispatch whose final branch raises:

```python
    def _raw_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for name, widget in self._field_widgets.items():
            if isinstance(widget, QCheckBox):
                values[name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                values[name] = widget.text()
            else:
                # QSpinBox/QDoubleSpinBox/QDateEdit all inherit .text(), so a
                # silent fallthrough would ship "(use default)" or a
                # comma-decimal "0,800" to the child process. Fail loudly.
                raise TypeError(
                    f"_raw_values has no rule for {type(widget).__name__} "
                    f"(field {name!r})")
        return values
```

> `QLineEdit` must be checked **explicitly**, not left as the fallback.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q`
Expected: all pass — every widget in use today is one of the three named classes.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "refactor(gui): make _raw_values dispatch explicitly and fail loudly

QSpinBox, QDoubleSpinBox and QDateEdit all inherit .text(), so the old
else-branch would have silently shipped '(use default)' or a locale-formatted
'0,800' to the child process the moment one was added. No behavior change
today; this is the guardrail the rest of PR2 leans on.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Scroll the form (closes #357)

**Files:**
- Modify: `autogis/adapters/gui/app.py` `:211-214`
- Test: `tests/test_gui_app.py`

- [ ] **Step 1: Write the failing test**

```python
def test_window_can_shrink_below_the_form_height(qapp):
    """#357: the layout minimum pinned the window to ~874x871, putting the Run
    button and output pane permanently off-screen on a 768p display."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon build-conc-surface")  # 15 fields
    win.resize(400, 300)
    qapp.processEvents()
    assert win.minimumSizeHint().height() < 700
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q -k shrink`
Expected: FAIL — height is ~871.

- [ ] **Step 3: Write the implementation**

Add `QScrollArea` to the `PySide6.QtWidgets` import, then replace `:211-214`:

```python
        self._form_layout = QFormLayout()
        form_container = QWidget()
        form_container.setLayout(self._form_layout)
        # Without a scroll area the layout minimum pins the window at ~874x871
        # for a 15-field command, pushing Run and the output pane off a 768p
        # screen with no way to shrink (#357).
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_container)
        outer.addWidget(form_scroll)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "fix(gui): scroll the parameter form

Closes #357.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Spin boxes with an explicit "(use default)" state

**Files:**
- Modify: `autogis/adapters/gui/app.py` (`_rebuild_form` numeric branch, `_raw_values`)
- Test: `tests/test_gui_app.py`

**Design (all six behaviors proved by offscreen probe during derivation):**
- `kind == "int"` → `QSpinBox`; `kind == "float"` → `QDoubleSpinBox`.
- Range from `field.minimum`/`field.maximum`, defaulting to a wide sane span when `None`.
- When the field is **optional and has no default**, set the minimum one step **below** the real
  floor and `setSpecialValueText("(use default)")`; `_raw_values` maps that sentinel back to `""`
  so `forms._normalize` omits the option.
- **Pin the locale**: `widget.setLocale(QLocale.c())`. Confirmed real during derivation — on a
  comma-decimal machine the widget renders `0,800`, which Click's `FLOAT` rejects with a
  usage error the user cannot diagnose.

- [ ] **Step 1: Write the failing test**

```python
def test_optional_numeric_defaults_to_the_use_default_sentinel(qapp):
    from PySide6.QtWidgets import QSpinBox
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    w = win._field_widgets["limit"]
    assert isinstance(w, QSpinBox)
    assert w.value() == w.minimum()
    assert w.specialValueText() == "(use default)"
    assert win._raw_values()["limit"] == ""   # -> omitted by forms._normalize


def test_setting_a_number_round_trips_to_argv(qapp):
    from autogis.adapters.gui.executor import build_argv
    from autogis.adapters.gui.forms import build_step
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    win._field_widgets["limit"].setValue(25)
    step = build_step(win._forms["envmon run-history"], win._raw_values())
    assert "--limit" in build_argv(step.command, step.values)
    assert "25" in build_argv(step.command, step.values)


def test_float_uses_c_locale_so_a_comma_decimal_machine_cannot_break_it(qapp):
    from PySide6.QtCore import QLocale
    win = MainWindow()
    win._command_box.setCurrentText("envmon reconcile-locations")
    w = win._field_widgets["threshold"]
    assert w.locale() == QLocale.c()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_app.py -q -k numeric`
Expected: FAIL — `assert isinstance(QLineEdit, QSpinBox)`.

- [ ] **Step 3: Write the implementation**

In `_rebuild_form`, before the final `else`, add:

```python
            elif field.kind in ("int", "float"):
                widget = QSpinBox() if field.kind == "int" else QDoubleSpinBox()
                widget.setLocale(QLocale.c())  # a comma-decimal locale renders
                                               # "0,800", which Click rejects
                low = field.minimum if field.minimum is not None else -10**6
                high = field.maximum if field.maximum is not None else 10**6
                if field.default is None:
                    # A spin box always holds a number, but blank->omitted is
                    # the contract (forms._normalize). Qt's own answer: put a
                    # sentinel one step below the floor and label it.
                    widget.setRange(low - 1, high)
                    widget.setSpecialValueText("(use default)")
                    widget.setValue(low - 1)
                else:
                    widget.setRange(low, high)
                    widget.setValue(field.default)
```

In `_raw_values`, add **before** the `QLineEdit` branch (a spin box is not a line edit, but order
the dispatch defensively):

```python
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                # The sentinel means "unset" -> "" -> omitted by _normalize.
                values[name] = ("" if widget.text() == widget.specialValueText()
                                else widget.value())
```

Add `QSpinBox`, `QDoubleSpinBox` to the widgets import and `QLocale` to the `QtCore` import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH="$PWD" QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "feat(gui): spin boxes for numeric options, with an explicit unset state

setSpecialValueText('(use default)') at a sentinel one step below the floor
keeps 'blank means omitted' expressible, which is why a bare spin box was
rejected in the design. Locale pinned to C: a comma-decimal machine renders
0,800 and Click's FLOAT rejects it with an undiagnosable usage error.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: Calendar picker for `kind == "date"`

**Files:** Modify `autogis/adapters/gui/app.py`; Test `tests/test_gui_app.py`

Same shape as Task 10. `QDateEdit` with `setCalendarPopup(True)`, `setDisplayFormat("yyyy-MM-dd")`,
`setLocale(QLocale.c())`. For the 15 optional ones set `setSpecialValueText("(none)")` at
`minimumDate()`; `_raw_values` maps that back to `""`, otherwise
`widget.date().toString("yyyy-MM-dd")`.

- [ ] **Step 1: Write the failing test**

```python
def test_date_field_is_a_calendar_and_defaults_to_none(qapp):
    from PySide6.QtWidgets import QDateEdit
    win = MainWindow()
    win._command_box.setCurrentText("envmon gw-level-summary")
    w = win._field_widgets["event_date"]
    assert isinstance(w, QDateEdit)
    assert w.calendarPopup() is True
    assert win._raw_values()["event_date"] == ""


def test_picked_date_serializes_as_iso(qapp):
    from PySide6.QtCore import QDate
    win = MainWindow()
    win._command_box.setCurrentText("envmon gw-level-summary")
    win._field_widgets["event_date"].setDate(QDate(2026, 7, 25))
    assert win._raw_values()["event_date"] == "2026-07-25"
```

- [ ] **Step 2: Run it** — Expected: FAIL, widget is a `QLineEdit`.
- [ ] **Step 3: Implement** the `elif field.kind == "date":` branch plus the `QDateEdit` case in
      `_raw_values`, mirroring Task 10's sentinel handling.
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — Expected: green.
- [ ] **Step 5: Commit** `feat(gui): calendar picker for the 16 ISO date options`.

---

### Task 12: Editable combo + multichoice checklist

**Files:** Modify `autogis/adapters/gui/app.py`; Test `tests/test_gui_app.py`

Two small branches:
- `kind == "choice"` and `field.strict is False` → the existing `QComboBox` plus
  `setEditable(True)` and `setInsertPolicy(QComboBox.NoInsert)`. **`_raw_values` needs no
  change** — `currentText()` already returns typed text.
  **Constraint:** `tests/test_gui_app.py:459-480` requires a strict choice to keep its leading
  blank item and to return `""` (not `None`) when unset. Do not disturb that path.
- `kind == "multichoice"` → a checkable `QListWidget` (proved workable during derivation) inside
  **one** container so `rowCount()` is unchanged. `_raw_values` joins the checked items with
  `","`, matching the CLI contract `CommaList` preserves.

- [ ] **Step 1: Write the failing test**

```python
def test_suggested_choice_combo_is_editable_and_accepts_typed_text(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon build-conc-surface")
    w = win._field_widgets["matrix"]
    assert w.isEditable() is True
    w.setCurrentText("SED")                     # not in the suggestion list
    assert win._raw_values()["matrix"] == "SED"


def test_strict_choice_stays_non_editable(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    assert win._field_widgets["fmt"].isEditable() is False


def test_multichoice_renders_a_checklist_in_one_row(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon gen-synthetic-workbook")
    form = win._forms["envmon gen-synthetic-workbook"]
    assert win._form_layout.rowCount() == len(form.fields)   # still 1 row/field
    w = win._field_widgets["features"]
    w.item(0).setCheckState(Qt.Checked)
    w.item(1).setCheckState(Qt.Checked)
    assert "," in win._raw_values()["features"]
```

- [ ] **Step 2: Run it** — Expected: FAIL on `isEditable`.
- [ ] **Step 3: Implement** both branches and the `QListWidget` case in `_raw_values`.
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — Expected: green.
- [ ] **Step 5: Commit** `feat(gui): editable suggestion combos and multi-select checklists`.

---

### Task 13: Multi-value rows (closes #350)

**Files:** Modify `autogis/adapters/gui/app.py`; Test `tests/test_gui_app.py`, `tests/test_gui_executor.py`

A `field.repeatable` field renders as a container holding one value row plus a `+` button; each
added row gets a `−`. `_raw_values` returns a **list** of the non-empty rows — `forms._normalize`
and `build_argv:175-177` already handle a list correctly, which is why nothing below `app.py`
changes.

**Constraints:** the container occupies one `QFormLayout` row. The `+`/`−` buttons must **not**
use `objectName("field-browse")` — `tests/test_gui_app.py:105-145` counts those.

- [ ] **Step 1: Write the failing test**

```python
def test_repeatable_field_emits_the_option_once_per_value(qapp):
    from autogis.adapters.gui.executor import build_argv
    from autogis.adapters.gui.forms import build_step
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    w = win._field_widgets["set_pairs"]
    w.set_values(["temperature_c=4.0", "carrier=FedEx"])   # helper on the container
    assert win._raw_values()["set_pairs"] == ["temperature_c=4.0", "carrier=FedEx"]
    form = win._forms["envmon coc advance"]
    step = build_step(form, {**win._raw_values(), "store_path": "s.json",
                             "to_state": "released", "actor": "t", "coc": "C-1"})
    assert build_argv(step.command, step.values).count("--set") == 2


def test_repeatable_container_is_one_form_row(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    form = win._forms["envmon coc advance"]
    assert win._form_layout.rowCount() == len(form.fields)
```

- [ ] **Step 2: Run it** — Expected: FAIL, `set_pairs` is a `QLineEdit` with no `set_values`.
- [ ] **Step 3: Implement** a small `_RepeatableRows(QWidget)` helper class with
      `values() -> list[str]` and `set_values(list[str])`, plus its `_raw_values` case.
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — Expected: green.
- [ ] **Step 5: Commit** `fix(gui): multi-value rows for repeatable options — closes #350`.

---

### Task 14: `nargs>1`, tri-state flag, xor greying (closes #351, #352)

**Files:** Modify `autogis/adapters/gui/{introspect,forms,executor,app}.py`; Tests as listed

Three small independent fixes, grouped because each is a handful of lines:

1. **`nargs>1` (#351)** — `introspect.FormField` gains `nargs: int = 1`; `forms._normalize`
   splits the typed string on whitespace and validates the count; `executor.build_argv` emits the
   parts as separate tokens instead of one repr. All three must change together — a widget-only
   fix does not work, because `build_argv` reprs the tuple independently.
2. **Tri-state flag (#352)** — in `forms._normalize`, a `kind == "flag"` field whose
   `field.default is None` and whose value is falsey returns `None` (omitted) rather than `False`.
   That stops the `harvest` form emitting `--no-incremental` over a config's `incremental: true`.
   **`tests/test_gui_executor.py:150` asserts the current behavior and must be updated in this
   commit** — deliberately, not incidentally.
3. **xor greying** — filling one side calls `setEnabled(False)` on the sibling and **keeps its
   text**; clearing re-enables both. Reuse the shape of `config_builder_dialog.py:241-251`.
   Drive it from the widget, never `labelForField()` (returns `None` for path rows).
   **Exception:** `reconcile-locations --gdb` unconditionally HALTs (`cli.py:576`), so do not
   grey its sibling into that dead end — leave that pair as it is today and add a
   `ponytail:` comment saying why.

- [ ] **Step 1: Write the failing tests** (one per fix)

```python
def test_bbox_emits_four_separate_tokens(qapp):
    from autogis.adapters.gui.executor import build_argv
    from autogis.adapters.gui.forms import build_step
    win = MainWindow()
    win._command_box.setCurrentText("envmon download-dem")
    win._field_widgets["bbox"].setText("-105 39 -104 40")
    step = build_step(win._forms["envmon download-dem"],
                      {**win._raw_values(), "out": "x.tif"})
    argv = build_argv(step.command, step.values)
    i = argv.index("--bbox")
    assert argv[i + 1:i + 5] == ["-105", "39", "-104", "40"]


def test_untouched_tristate_flag_is_omitted():
    """#352: an untouched --incremental/--no-incremental checkbox must not
    override the config's own setting."""
    from autogis.adapters.gui.forms import build_step
    from autogis.adapters.gui.introspect import introspect_cli
    form = next(f for f in introspect_cli() if f.label == "harvest")
    step = build_step(form, {"config_path": "c.yaml", "incremental": False})
    assert "incremental" not in step.values


def test_filling_one_xor_side_disables_the_other_but_keeps_its_text(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon update-well-elevations")
    gdb, csv = win._field_widgets["gdb"], win._field_widgets["wells_csv"]
    gdb.setText("C:/old/site.gdb")
    csv.setText("C:/data/wells.csv")
    qapp.processEvents()
    assert gdb.isEnabled() is False
    assert gdb.text() == "C:/old/site.gdb"      # preserved, per owner decision
    csv.clear()
    qapp.processEvents()
    assert gdb.isEnabled() is True
```

- [ ] **Step 2: Run them** — Expected: three failures.
- [ ] **Step 3: Implement** the three fixes.
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — Expected: green, with
      `tests/test_gui_executor.py:150` updated.
- [ ] **Step 5: Commit** `fix(gui): nargs, tri-state flags and xor greying — closes #351, #352`.

---

## Done criteria

- [ ] Full suite green locally **and in CI** (CI is authoritative — it is the only env that
      verifies the arcpy/arcgis-free invariant).
- [ ] Issues #350, #351, #352, #353, #354, #355, #356, #357 closed by their commits.
- [ ] `python -m autogis envmon --help` renders without a wall of lowercased dataset codes.
- [ ] Manual smoke: launch `autogis-gui`, pick `envmon build-conc-surface`, confirm the window
      shrinks, the matrix combo accepts a typed `SED`, and `--event-date` shows a calendar.
- [ ] An ADR recording the `SuggestedChoice`/`IsoDate` "annotate, don't restrict" decision — it is
      a structural choice about how CLI types carry UI intent (see `docs/adr/README.md`,
      number against `origin/main` **and all open PRs**).
