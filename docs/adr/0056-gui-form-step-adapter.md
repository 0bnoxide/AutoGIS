# ADR-0056: Form-values -> Step adapter — reuse XOR_PAIRS metadata, leave conditional/type validation to the child command

**Status:** Accepted

**Date:** 2026-07-05

## Context

Three toolkit-free GUI-adapter layers exist: `introspect.py` (ADR-0052,
Click tree -> `CommandForm`/`FormField`), `executor.py` (ADR-0053, `Step` ->
subprocess -> HALT/PAUSE/CONTINUE), and `runner.py` (ADR-0055, drives an
ordered `Workflow` of `Step`s through the executor). Nothing bridges the
first to the second: a GUI renders a `CommandForm`'s fields and collects raw
values from widgets (strings from text fields, bools from checkboxes, lists
from repeatable-field widgets), but no code turns that raw dict into a valid
`Step`. No ADR assigned this mapping to any other task — it is real,
missing, on-the-critical-path glue for the workflow builder (ADR-0050
decision 4), and it is fully testable without a GUI toolkit, same as the
three layers it sits between.

The design question this ADR resolves: how much validation belongs at this
layer versus left to the child CLI command's own guard clauses (which
`executor.decide()` already turns into a clean HALT with stderr as the
reason)?

## Decision

1. **`autogis/adapters/gui/forms.py` — pure logic, no GUI toolkit, no
   arcpy.** `build_step(form, raw_values, *, fail_on=None,
   pause_on_warning=False) -> Step`.

2. **What this layer validates, before ever launching a subprocess:**
   - An `unreachable_reason` command (a GUI shouldn't let a user submit a
     form for a tool already flagged unreachable in this environment).
   - An unknown field name in `raw_values` (a GUI/form-schema mismatch bug,
     not a user error — same "fail loud" stance as `build_argv`'s own
     unknown-parameter check).
   - Missing required fields (`FormField.required`).
   - `xor_group` (introspect.py's own `XOR_PAIRS` metadata, exposed on the
     `FormField`s themselves — **reused, not re-derived**): exactly one
     member of the group must be filled. A flag member counts as "filled"
     only when `True` — an explicit `False` (an unchecked box submitted by
     a real form widget, not merely absent) must not count as "chosen," or
     an unchecked flag alongside an empty text sibling would misread as
     "exactly one provided" when the user picked neither.

3. **What this layer deliberately does NOT validate** — left to the child
   command's own guard, whose refusal already surfaces cleanly through
   `executor.decide()`:
   - Conditional requirements (`sync-to-gdb`'s "--gdb requires --table",
     `batch-import-workbooks`'s "--edd-dir requires --profile and --site") —
     introspect.py's own docstring already scopes these out of the
     descriptors this module reads; modeling them here would be a second,
     driftable copy of each command's body-level rule.
   - Type-parseability of int/float/choice strings — Click's own parser in
     the child process is the single source of truth. Argv is inherently
     textual (`build_argv` just stringifies), so there is nothing to
     "coerce" at this layer beyond flag-boolean and repeatable-list shape.
   - Path existence — `click.Path(exists=True)` in the child process
     already refuses a missing input file cleanly.

4. **Normalization, not validation:** a blank/missing value becomes `None`
   (omitted from the final `Step.values`, so the command's own Click default
   applies) rather than passed through as a literal empty string; a single
   repeatable value is wrapped into a one-tuple; a `False` flag is kept as
   an explicit value (it may need to override a `default=True` flag as
   `--no-flag`), never silently dropped.

5. **No `build_workflow()` helper.** `runner.Workflow(name, steps)` already
   takes a plain tuple of `Step`s — a widget layer building a multi-step
   workflow calls `build_step()` once per configured step and constructs
   the `Workflow` directly; no additional glue is needed for that, and
   adding one would be an unrequested abstraction over a two-argument
   dataclass constructor.

## Consequences

### Positive

- The workflow builder (whenever the widget-layer task reaches it) gets a
  single, tested function turning "what the user typed into a form" into
  "a runnable Step," with the exact same validation semantics
  `introspect.py`'s `XOR_PAIRS` already documents — no duplicate rule table.
- Failures a GUI should show inline (missing required field, unsatisfied
  xor group) are distinguished from failures that should show as a
  subprocess HALT reason (a conditional requirement, a bad path) — cheap,
  fast, in-GUI validation for the former; the child command remains the
  single source of truth for the latter, so there's exactly one place each
  rule lives.
- Fully headless-testable: one integration test drives the *real*
  `introspect_cli()` output for `envmon reconcile-locations` (a real
  `wells_csv`/`gdb` xor pair, where `gdb` is a flag) through `build_step()`
  and `executor.build_argv()`, proving the whole
  form -> Step -> argv chain is actually wired together, not just
  internally self-consistent.

### Negative / accepted trade-offs

- A user can still hit a conditional-requirement or type-parse error from
  the child process after this layer's checks pass (e.g., `--gdb` without
  `--table`) — accepted, per decision 3: re-deriving every command's
  body-level rule here would be a second copy of the same logic, and
  `executor.decide()` already reports the child's refusal cleanly.
- `xor_group`'s "exactly one" framing is a simplification of some commands'
  actual semantics (e.g. `reconcile-locations`'s `--gdb` always errors
  headlessly regardless of `wells_csv`, directing the user to the `.pyt`
  toolbox) — accepted: it is still the right first-line UX (matching the
  option help text's own "mutually exclusive" framing), and the child
  process's own message is still the final word when a simplification
  doesn't capture a command's full nuance.

## Alternatives considered

1. **Re-derive each command's full body-level validation (conditional
   requirements, "gdb requires table", etc.) into a per-command rule
   table.** Rejected as over-build: this would be a second, driftable copy
   of logic that already lives in exactly one place (the command body) and
   is already reported cleanly by the executor's HALT path.
2. **Type-coerce raw values to `int`/`float`/etc. before building `Step`.**
   Rejected: `build_argv` stringifies every value into argv regardless
   (subprocess argv is textual), so there is nothing to gain by parsing a
   number here only to `str()` it again — Click's own parser in the child
   process is authoritative either way.
3. **Fold this into `introspect.py` or `executor.py` instead of a new
   module.** Rejected: `introspect.py` produces descriptors and
   deliberately has zero knowledge of `Step`/`executor.py` (keeps it usable
   standalone for read-only form rendering); `executor.py` deliberately has
   zero knowledge of how `Step.values` gets built (keeps it usable for
   programmatically-constructed steps, e.g. tests). A third small module
   matches the existing one-file-per-concern shape.

## Related decisions

- [ADR-0052](0052-gui-introspection-layer.md) — `CommandForm`/`FormField`/
  `XOR_PAIRS`, the descriptors this module reads and reuses without
  re-deriving.
- [ADR-0053](0053-gui-executor-qa-signal.md) — `Step`/`run_step`, what this
  module's output feeds into.
- [ADR-0055](0055-gui-workflow-runner-thread-boundary.md) — `Workflow`,
  which a widget layer assembles directly from `build_step()` outputs; no
  new helper needed per decision 5.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/forms.py`,
  `tests/test_gui_forms.py`.
