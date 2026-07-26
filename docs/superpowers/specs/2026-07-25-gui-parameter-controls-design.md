# GUI parameter controls — pick values, don't type them

**Date:** 2026-07-25
**Status:** Implemented — proposed for review
**Scope:** `autogis/adapters/gui/` (PySide6 window) + `autogis/adapters/cli.py` (Click type declarations)
**Baseline:** `main` @ `a518237`
**Not in scope:** `autogis/adapters/toolbox.pyt` (see *Out of scope*)

> **Integration note, 2026-07-26:** current `main` independently closed #352
> with a real three-state checkbox in PR #365 and closed #353-#355/#358 in
> PR #372. This implementation preserves the stronger three-state contract:
> partially checked omits the override, while explicitly unchecked still emits
> `--no-incremental`. Survey123 Phase 2 also added `sync-survey123 --since`
> and its staging `--out` after the baseline; they extend the inventories to
> 17 ISO-date options and 13 directory params. This branch owns the remaining
> GUI fixes #350, #351, #356, and #357 plus the control metadata/rendering
> described below.

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

> ### ⚠ AMENDED 2026-07-25 after per-option verification
>
> The table below is the **verified** version. The original draft proposed `click.Choice` on 9
> options and `click.DateTime` on 16; per-option derivation found that **7 of the 9 dropdowns and
> all 16 date swaps would reject input the CLI accepts today**, violating this spec's own
> constraint. The mechanism changed, the goal did not — see
> `docs/superpowers/plans/2026-07-25-gui-parameter-controls.md` § "Scope corrections".
>
> The unifying fix: three custom `ParamType`s that **annotate rather than restrict**, each
> returning the input string unchanged so **no command body changes**.

| Change | Count | Declaration |
|---|---:|---|
| Constrained options → strict dropdown | 2 | `click.Choice(...)` — only where the body already validates the same set |
| Open-vocabulary options → editable dropdown | 7 | new `SuggestedChoice(values)` — suggests, refuses nothing |
| Date options → calendar | 16 | new `IsoDate(allow_time=...)` — validates, returns the string |
| Closed-vocabulary comma lists → checklist | 4 | new `CommaList(vocab)` |
| Numeric bounds | 46 of 54 | `click.IntRange` / `click.FloatRange` (only **2** get a maximum) |
| Folder params on a save-file dialog | 12 | `click.Path(file_okay=False)` |
| Undocumented options | 110 | add `help=` |

**Why `SuggestedChoice` and not `click.Choice`:** `KNOWN_MATRICES` is `{"GW","SOIL"}` but is a
*figure-spec* vocabulary — `config/lab_profiles/nysdec.yaml:75-81` maps to `SED`. `UNIT_REGISTRY`
omits `ppb`/`ppm` by design (`units.py:3-7`) while legacy workbooks use them, and a strict Choice
rejects `µg/L` spelled U+00B5 vs U+03BC. `run-history --tool` is a *log query* — restricting it to
today's command set makes a row written by a since-renamed command unqueryable.

**Why `IsoDate` and not `click.DateTime`:** all 16 bodies call `date.fromisoformat(...)` on the
value; a `datetime` raises `TypeError` there. `estimate-gw-flow-direction` fails **silently**,
writing `2026-07-01 00:00:00` into a CSV cell.

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

- `"date"` — from `IsoDate`, with `allow_time` preserved separately
- `"multichoice"` — from `isinstance(ptype, CommaList)`; `choices` populated

`kind="choice"` **combined with** the existing `repeatable=True` expresses a
multi-row choice control that emits N separate flags — no new descriptor is
needed for `--required-tool`. `strict=False` keeps each row editable.

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
| date-only `date` | `QDateEdit` + calendar popup; `(none)` state when optional |
| timestamp-capable `date` | `QLineEdit`; offsets/seconds exceed a date-only picker's contract |
| `multichoice` | checklist inside **one** form row; joined with `,` on read-back |
| suggested `choice` + `repeatable` | editable combo rows inside one container; emits N flags |
| closed-range `int` / `float` | `QSpinBox` / `QDoubleSpinBox`, `setRange` from `minimum`/`maximum` |
| open-ended `int` / `float` | `QLineEdit`; a finite Qt range would narrow valid CLI input |
| `repeatable` (free text/path) | +/− rows inside one container widget |
| `xor_group` | **grey the unused sibling, keep its text** — see 4.1a |
| the form as a whole | wrapped in a `QScrollArea` |

### 4.1 Expressing "unset"

`forms.py::_normalize` treats blank → `None` → option omitted, so the command's
own default applies. Open-ended numeric options remain line edits: Qt requires
a finite spin-box range, and the original ±1,000,000 fallback silently clamped
valid geospatial coordinates. A closed-range spin box with no default uses the
native sentinel mechanism below.

For a closed range, `QSpinBox.setSpecialValueText("(use default)")` can place
an unset sentinel one step below the real floor without excluding a legal
value. Qt displays that text at the minimum; read-back maps it to `None`. The
optional `QDateEdit`s use the same mechanism. **No custom numeric widget.**

### 4.1a Either/or (xor) behaviour

**Owner decision, 2026-07-25:** filling one side **disables** the sibling but **preserves whatever
is typed in it**. Clearing the filled side re-enables both, with the sibling's text intact. No
clearing, no confirmation prompt — a path the user typed is never destroyed by a side effect.

This is exactly `config_builder_dialog.py:241-251 _sync_xor`, which already does
`setEnabled(not other)` and nothing else. **Reuse it rather than writing a second one** — the only
additions are wiring it to the generic `xor_group` metadata and the `reconcile-locations`
exception below.

Two constraints from §6 apply directly: greying must be driven from the widget (not
`labelForField()`, which returns `None` for path rows), and `reconcile-locations --gdb`
unconditionally HALTs, so its pair must not steer the user into the dead-end side.

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
single repr token. See §10.

---

## 10. Filed bugs this design closes

Nine defects were found while scoping this work. Each was **reproduced by execution**, not
inferred, and filed 2026-07-25. Eight are closed by a slice above; one is unrelated and stands
alone.

| Issue | Defect | Closed by |
|---|---|---|
| [#350](https://github.com/0bnoxide/AutoGIS/issues/350) | Every `multiple=True` option renders as one `QLineEdit`; 5 STRING ones corrupt data **silently** (`coc advance --set` writes a malformed detail into the chain-of-custody audit trail, exit 0), 5 Path ones fail loudly | PR2 |
| [#351](https://github.com/0bnoxide/AutoGIS/issues/351) | `nargs>1` options always fail — `build_argv` emits the tuple as one repr token | PR2 |
| [#352](https://github.com/0bnoxide/AutoGIS/issues/352) | `harvest` form always emits `--no-incremental`, silently overriding a config's `incremental: true` — written by the GUI's *own* Site Config Builder | PR #365 (merged; preserved here) |
| [#353](https://github.com/0bnoxide/AutoGIS/issues/353) | **12** directory params declared bare `click.Path()` — no Click validation, and Browse opens a save-*file* dialog | PR #372 (merged); this branch retains control metadata |
| [#354](https://github.com/0bnoxide/AutoGIS/issues/354) | `select-soil-intervals --tiers <typo>` → 0 rows, header-only CSV, `Status: PASS`, exit 0 | PR #372 (merged); `CommaList` adds checklist metadata |
| [#355](https://github.com/0bnoxide/AutoGIS/issues/355) | `gen-synthetic-workbook --features <typo>` → raw `ValueError` traceback instead of a usage error | PR #372 (merged); `CommaList` adds checklist metadata |
| [#356](https://github.com/0bnoxide/AutoGIS/issues/356) | Per-field help invisible on ~50 defaulted fields — `setPlaceholderText` only paints when empty, and `setText(default)` runs first | PR1 (the `setToolTip` line) |
| [#357](https://github.com/0bnoxide/AutoGIS/issues/357) | Window minimum pinned to the layout minimum (874×871 on `build-conc-surface`); no `QScrollArea` | PR2 |
| [#358](https://github.com/0bnoxide/AutoGIS/issues/358) | `manage-callout-overrides clear` ignores `MapType`, deleting other map types' overrides | — (unrelated) |

Note that **#354 and #355 are the strongest argument for the Click-typing approach**: both are
"the vocabulary is closed but the CLI doesn't know it" defects, and both disappear as a
side-effect of declaring the type — no error-handling code written.

---

## 5. Deferred — Data-dependent vocabularies

**Owner decision, 2026-07-25: build later.** Ship PR1 and PR2, use them, and only then decide
whether typing these 14 is actually a nuisance. Nothing in PR1/PR2 forecloses it — they stay
plain text fields until someone asks.

The 14 remaining comma-list options (`--analytes`, `--borings`, `--received-ids`, `--sites`,
`--events`, `--analyte-filter`, …) have **no static vocabulary**: their legal values come from the
workbook, GDB, or results file selected in a *sibling field of the same form*.

Recorded here so the decision isn't re-derived from scratch — what it *would* take:

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
- **PR #365 owns the tri-state contract.** Partially checked maps to `None`
  (omit both flags); explicitly unchecked remains `False` and emits
  `--no-incremental`. The parameter-controls branch must preserve both paths.
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
