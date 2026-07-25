# GUI parameter controls — pick values, don't type them

**Date:** 2026-07-25
**Status:** Design — approved by owner, pending spec review
**Scope:** `autogis/adapters/gui/` (PySide6 window) + `autogis/adapters/cli.py` (Click type declarations)
**Baseline:** `main` @ `a518237`
**Not in scope:** `autogis/adapters/toolbox.pyt` (see *Out of scope*)

---

## 1. Problem

The user's request: *"revise the UI to add parameter buttons/check boxes/fields/dropdown for all
tools option parameters like `--format table`"*, clarified to: **"I don't want `--` commands issued
by typing, I want them selected by a UI element."**

The goal is therefore **not** "render the options" — they are already rendered. It is: **wherever an
option's legal values are knowable, the user picks from a control instead of typing a string.**

### 1.1 What is already true (verified — do not re-propose)

Measured against `main` @ `a518237` by importing the real Click tree:

- **`_rebuild_form()` (`app.py:358-413`) filters nothing.** It loops `for field in form.fields:`
  over every `click.Parameter`. There are 0 `hidden`, 0 `is_eager`, 0 `expose_value=False` params
  in the tree. No option is missing from the form.
- **`--format` is already a dropdown.** It is `click.Choice` on every command that declares it;
  `introspect.py` types it `kind="choice"` and `app.py:372-383` renders a `QComboBox` with the
  default preselected. Verified live: `envmon run-history` renders `fmt` as a combo containing
  `['', 'table', 'csv', 'json']`, current `'table'`. **The literal example in the request already
  ships.**
- Flags already render as `QCheckBox`; path params already render as a line edit plus a `Browse…`
  button whose dialog direction (`open`/`save`/`dir`) is correctly wired through
  `_dialog_kind` → `_pick_path`.

### 1.2 The actual typing surface

| Family | Count | Today | Legal values knowable from |
|---|---:|---|---|
| Constrained single-value options | 5 | free text | an existing module constant |
| Comma-separated lists, closed vocabulary | 4 | free text `"a,b"` | an existing module constant |
| Comma-separated lists, data-dependent | 14 | free text `"a,b"` | the file/GDB chosen in a sibling field |
| Date options | 16 | free text `YYYY-MM-DD` | Click's own `DateTime` |
| Tool-name options | 4 | free text | `TOOL_REGISTRY` (`capabilities.py:433`) |
| Numeric options | 54 | free text, **0 bounded** | `help=` already states ~18 bounds |

The exact options, derived from the live Click tree (not from line numbers):

**Constrained single-value (5)** — `download-dem --dataset` → `DEM_DATASETS` ·
`list-tools --domain` → registry-derived · `migrate-legacy-data --default-matrix` and
`build-conc-surface --matrix` → `KNOWN_MATRICES` · `migrate-legacy-data --default-units` →
`UNIT_REGISTRY`.

**Closed-vocabulary comma lists (4)** — `gen-synthetic-workbook --features` → `MESSINESS` ·
`validate-rtk-survey --extra-columns` and `import-rtk-survey --extra-columns` →
`_EXTRA_COLUMN_VOCAB` · `select-soil-intervals --tiers` → `IntervalTier`.

> **In-repo precedent:** `build-analytical-key --matrix` is *already* `click.Choice` over the same
> `KNOWN_MATRICES` vocabulary that `build-conc-surface --matrix` and
> `migrate-legacy-data --default-matrix` declare as bare text. The inconsistency is within one
> file — this slice makes the typed spelling uniform rather than inventing a new convention.

Baseline totals: **133 leaf commands · 803 params · 506 optional.**
Kinds: `path` 401 · `text` 202 · `choice` 93 · `flag` 53 · `float` 30 · `int` 24.
Also: **10** repeatable (`multiple=True`), **10** xor-group fields (5 pairs), **3** `nargs>1`.

The backing constants all exist and were verified present:
`DEM_DATASETS` (`core/envmon/opentopo.py:102`), `MESSINESS` (`core/envmon/synthetic_workbook.py:18`),
`IntervalTier` (`core/envmon/soil_interval_selector.py:29`), `UNIT_REGISTRY` (`core/common/units.py:14`),
`KNOWN_MATRICES` (`core/common/config_validation.py:18`),
`_EXTRA_COLUMN_VOCAB` (`core/envmon/import_rtk_survey.py:61`),
`TOOL_REGISTRY` (`runtime/capabilities.py:433`).

---

## 2. Principle

> **Click is the single source of truth. Every control is derived from a Click parameter type. The
> GUI never hardcodes a vocabulary.**

This is the existing ADR-0052 architecture — `introspect.py` walks the Click tree and emits
toolkit-free `FormField` descriptors; `app.py` is the only module that imports Qt. This design
**extends the type table**, it does not add a parallel one.

The practical consequence: **teaching `cli.py` its own types is what produces the dropdowns.**
A `click.Choice` added in `cli.py` becomes a `QComboBox` through code that already exists, and
simultaneously buys shell completion, a real parse-time error listing the legal values, and
CLI/`.pyt` parity. That is why the CLI-typing slice comes first.

### 2.1 Why not the alternatives

- **Hardcode vocabularies in `app.py`** — creates a second source of truth that silently drifts
  from the CLI. Rejected.
- **A GUI-side metadata sidecar** (YAML/dict mapping option → widget) — a config for values that
  already exist as Python constants two imports away. Rejected (YAGNI).

---

## 3. Slice 1 (PR1) — Type the CLI

**Touches:** `cli.py`, `introspect.py`, one line of `app.py`. **Ships independently.**

| Change | Count | Declaration |
|---|---:|---|
| Constrained options → dropdown | 5 | `click.Choice(sorted(CONSTANT))` |
| Date options → date control | 16 | `click.DateTime(formats=["%Y-%m-%d"])` |
| Tool-name options → dropdown | 4 | `click.Choice(sorted(TOOL_REGISTRY))` |
| Closed-vocabulary comma lists → checklist | 4 | new `CommaList(vocab)` `ParamType` |
| Numeric bounds | ~18 of 54 | `click.IntRange` / `click.FloatRange` |
| Folder params on a save-file dialog | 10 | `click.Path(file_okay=False)` |
| Undocumented options | 110 | add `help=` |

### 3.1 The `CommaList` param type

The 4 closed-vocabulary comma options (`--features`, `--extra-columns` ×2, `--tiers`) keep their
**existing CLI contract** — still `--features nondetects,rpd_sheet`, one comma-joined string. A
small `click.ParamType` subclass validates each element against the vocabulary and exposes
`.choices`, so `introspect.py` can emit `kind="multichoice"` with populated `choices`, and the GUI
joins the checked items with `","` on the way back out.

This is deliberately **not** a switch to `multiple=True`: that would change the command line
(`--features a --features b`), breaking saved recipes and any existing script.

### 3.2 `introspect.py` additions

`FormField` gains `minimum` / `maximum` (read off `IntRange`/`FloatRange`), and `kind` gains two
values:

- `"date"` — from `isinstance(ptype, click.DateTime)`
- `"multichoice"` — from `isinstance(ptype, CommaList)`; `choices` populated

`kind="choice"` **combined with** the existing `repeatable=True` already expresses "checklist that
emits N separate flags" — no new descriptor needed for `--required-tool`.

### 3.3 Why PR1 is safe alone

`_rebuild_form`'s `else` branch renders any unrecognised kind as today's `QLineEdit`. A `"date"` or
`"multichoice"` field therefore degrades to exactly the current behaviour until PR2 lands. The
`click.Choice` additions are the exception — those light up as dropdowns immediately, via the
existing path.

### 3.4 The one `app.py` line

`widget.setToolTip(field.help_text or "")` after the widget branch closes. Today help text reaches
the screen for **no** flag or choice field (the branches never touch `help_text`), and the
`setPlaceholderText` call at `app.py:388-389` is a **dead no-op** for ~50 fields because
`setText(default)` at `:386-387` runs first and Qt only shows a placeholder on an empty line edit.

---

## 4. Slice 2 (PR2) — Render it

**Touches:** `gui/` only — `app.py` primarily, plus `introspect.py`/`forms.py`/`executor.py` for
the `nargs` seam.

| Field shape | Control |
|---|---|
| `date` | `QDateEdit` + calendar popup; `(none)` state for the 15 optional ones |
| `multichoice` | checklist inside **one** form row; joined with `,` on read-back |
| `choice` + `repeatable` | checklist inside one row; emits N flags (`build_argv` already does this) |
| `int` / `float` | `QSpinBox` / `QDoubleSpinBox`, `setRange` from `minimum`/`maximum` |
| `repeatable` (free text/path) | +/− rows inside one container widget |
| `xor_group` | greying, reusing `_sync_xor` |
| the form as a whole | wrapped in a `QScrollArea` |

### 4.1 Expressing "unset"

`forms.py::_normalize` treats blank → `None` → option omitted, so the command's own default
applies. A spin box always holds a number and would break that contract for the **8** numeric
options that default to `None`.

Native fix: `QSpinBox.setSpecialValueText("(use default)")` with the minimum set one step below the
real floor. Qt displays that text at the minimum; the read-back maps it to `None`. Same mechanism
for the optional `QDateEdit`s. **No custom tri-state widget.**

### 4.2 Rejected controls (with reasons, so they are not re-proposed)

- **`QRadioButton`/`QButtonGroup` for xor pairs** — cannot express "neither chosen yet", which is
  the initial state of every form. Greying via `setEnabled` preserves it.
- **Spin boxes without `setSpecialValueText`** — see 4.1.
- **A chip/token widget for all 18 comma options** — 2 of them (`gen-map-series --sites/--events`)
  also accept a *file path* instead of a list, which a pure chip widget cannot express.

### 4.3 Bugs this slice necessarily fixes

Multi-value options are currently **unreachable** from the GUI: a repeatable field gets one
`QLineEdit`, so `export-wqx --results` and `lab-qa-trends --qc-results` — both `required=True,
multiple=True` — cannot do what they exist for. `nargs>1` options (`download-dem --bbox`,
`generate-subsurface-profile --start/--end`) always fail, because `build_argv` emits a tuple as a
single repr token. Both are filed as issues; PR2 closes them.

---

## 5. Slice 3 (PR3) — Data-dependent vocabularies

The 14 remaining comma-list options (`--analytes`, `--borings`, `--received-ids`, `--sites`,
`--events`, `--analyte-filter`, …) have **no static vocabulary**: their legal values come from the
workbook, GDB, or results file selected in a *sibling field of the same form*.

Requirements:

1. A per-option **enumerator** — a function `(source_path) -> tuple[str, ...]` living in `core/`,
   not the GUI, so the CLI can reuse it for validation.
2. A declared **dependency** from the option to the field that supplies its source.
3. **Async population** — reading a GDB or a workbook must not block the UI thread; reuse the
   existing `QThread` + signal pattern from `_StepWorker` rather than inventing a second one.
4. **Invalidation** when the source field changes, and a graceful **fallback to free text** when
   the source is empty, unreadable, or not yet chosen.

The fallback is not optional: the user must never be *blocked* from typing a value because a file
could not be read.

---

## 6. Constraints that bind the implementation

- **`rowCount() == len(form.fields)`** is asserted by `tests/test_gui_app.py:280` and `:289`.
  Every new control must occupy exactly **one** `QFormLayout` row — hence checklists and
  repeatable rows live inside a container widget.
- **`labelForField()` returns `None` for path rows** (documented at `tests/test_gui_app.py:296-299`,
  because those widgets are wrapped in a `QHBoxLayout` with the Browse button). xor greying must
  not route through labels.
- **`reconcile-locations --gdb` unconditionally raises "use the `.pyt`"**, so greying its sibling
  would steer the user into a guaranteed HALT. That pair needs an explicit exception.
- **`tests/test_gui_executor.py:150` asserts `--no-incremental`** is emitted. The tri-state fix
  changes that behaviour, so the test changes with it — deliberately, not incidentally.
- **`QDoubleSpinBox` follows the system locale**; a comma-decimal locale rejects `0.8`. Pin to C
  locale.
- **`--report` (82 fields) and `--fail-on` (66)** are injected and *overridden* by
  `executor.build_argv` regardless of what the user types. Hoisting them out of the per-command
  form would remove 148 widgets — but it breaks the `rowCount` assertions above, so it is
  **deferred**, not folded in silently.
- **ADR-0077 (arcpy doc-verification) does not apply.** The GUI adapter and `cli.py` are
  arcpy-free by design (ADR-0052/0057). It would apply the moment anyone edits `toolbox.pyt`.

---

## 7. Testing

Each slice keeps the existing **107 GUI tests** green and adds, per new kind:

1. **`introspect` test** — the option yields the expected `kind`, `choices`, `minimum`/`maximum`.
   Arcpy-free, runs in CI.
2. **`CliRunner` test** — a bad value now exits 2 and the message lists the legal values. This is
   the test that proves the CLI half is real independent of any GUI.
3. **Offscreen-Qt test** — `_rebuild_form` produces the expected widget class, and `_raw_values()`
   round-trips through `build_step()` to the expected `build_argv` output. Multi-value gets an
   explicit `argv.count("--opt") == 2` assertion, matching the existing precedent at
   `tests/test_gui_executor.py:125`.

Run: `python -m pytest -q` with `PYTHONPATH` set to the worktree root (without it, ~13
`test_gui_executor` subprocess tests fail spuriously). **CI is authoritative for pass/fail** —
it is the only environment that verifies the arcpy/arcgis-free invariant.

---

## 8. Out of scope

- **`toolbox.pyt`.** Its 19 tools already carry 16 `filter.type="ValueList"` dropdowns, native
  `GPBoolean` checkboxes, and `DEFolder`/`DEWorkspace` pickers — Pro's parameter UI is already
  richer than the PySide6 form. Only 2 tools have genuine gaps
  (`ExportContoursForCivil3D`, `DownloadOpenTopoDEM`). Any change there triggers ADR-0077
  doc-verification, so it belongs in its own task.
- **Hoisting `--report`/`--fail-on`** out of the per-command form (see §6).
- **The `--format` naming drift** (4 dest names, 8 choice sets) — correctly typed, renders fine.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| ~167 mechanical `cli.py` edits in PR1 (5 + 4 + 4 + 16 + 18 + 10 + 110) hide a real behaviour change | Every new `Choice`/`Range` gets a `CliRunner` test; the diff is mechanical and reviewable by category |
| Adding `click.Choice` rejects a value someone currently passes | The vocabularies are taken from constants the command body *already* validates against — the CLI moves the error earlier, it does not shrink the legal set. Verify per option that the body's check matches the constant. |
| `click.DateTime` changes the value the command body receives from `str` to `datetime` | Each of the 16 call sites must be checked; several already parse the string themselves |
| PR3's async population blocks the UI or leaks a thread | Reuse the `_StepWorker` QThread+signal pattern; fall back to free text on any failure |
