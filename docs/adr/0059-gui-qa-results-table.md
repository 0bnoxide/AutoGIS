# ADR-0059: GUI QA-results table — render the executor's parsed qa_rows as a worst-severity-first, drop-empty-columns table

**Status:** Accepted

**Date:** 2026-07-06

## Context

The walking-skeleton window (ADR-0057) runs one headless command and dumps
`Decision` / `Reason` / `stdout` / `stderr` into a `QPlainTextEdit`. The
executor (ADR-0053) already injects `--report <job>/qa.csv` into every command
that declares the shared `--report` option and parses it back into
`StepResult.qa_rows` — a tuple of dicts with `QARecord`'s 15 fields
(`severity`, `category`, `message`, `recommended_action`, `site_id`,
`location_id`, `sample_id`, `sample_date`, `analyte_name`, `source_workbook`,
`source_sheet`, `source_row`, `source_column`, `source_cell`,
`import_batch_id`). `app.py` **ignored** `qa_rows`.

This was **not** "the QA data was invisible": `cli.py`'s `_render_qa` already
`click.echo`s each record as `[SEVERITY] category: message -> action`, and the
window's stdout pane already showed that flat text. What was missing was the
*structured* form — sorted, per-column, color-coded — and the per-record
locator columns (`site_id` / `sample_id` / `analyte_name` / `source_cell` …)
that the stdout summary never prints at all.

The unified-GUI planning doc
(`docs/superpowers/specs/2026-07-03-unified-gui-planning.md` §2.3) named "a
generic QA-result display component" as the *more* feasible MVP piece than a
generic input form (the QA output side is far more uniform than the input
side). This slice is that component. The user chose it (via `AskUserQuestion`)
over the handoff's other candidates (LOCAL-tool support, workflow builder, the
`unreachable` dict), and it is a smaller, self-contained slice than any of
those.

## Decision

1. **Render `StepResult.qa_rows` in a `QTableWidget`** placed between the
   status label and the **kept** stdout/stderr pane. The pane is not
   replaced — it still carries the reason line, any non-QA stdout, and stderr
   on failure. The table is a *view of the same run*, not a substitute.

2. **Columns come from the row keys, not a hardcoded list.** `csv.DictReader`
   gives every row the same keys in qa.csv's header order, which *is*
   `QARecord`'s field order (severity, category, message first). Columns that
   are **empty across every row are dropped**, so the 15-field schema stays
   readable in a narrow window: one generic rule adapts to each tool's actual
   output (an RTK-survey tool populates ~4 fields; an analytical-data importer
   populates the locator fields heavily) with zero per-tool configuration.

3. **Rows are sorted worst-severity-first, reusing `executor._SEV_ORDER`** —
   the same map the executor already uses to order its reason summary — rather
   than duplicating a second copy of the severity ordering.

4. **The severity cell is color-coded** (red for `ERROR`/`CRITICAL`, orange
   for `WARNING`, muted gray for `INFO`), with colors chosen to read on both
   light and dark Qt themes. At-a-glance triage is intrinsic to a QA table,
   not decoration.

5. **The table is hidden when a run produced no `qa_rows`** — a command with
   no `--report` option, or a crash before any check ran. Graceful: the stdout
   pane still carries whatever the command emitted, and `_on_failure` hides the
   table too.

6. **It reads structured `qa_rows`, never parses stdout** — upholding
   ADR-0053's explicit rule that stdout is "never parsed (fragile,
   human-facing)". The table is the structured view; stdout stays the
   human-text view. The two are complementary, not redundant.

7. **Two offscreen-Qt smoke tests** cover render+sort+drop-empty and
   hidden-when-empty. Real-command population was verified **manually** rather
   than in an app test: `envmon validate-rtk-survey` on a warnings CSV yields
   7 real `qa_rows` and a HALT. The widget-renders-rows test plus this real
   run together cover the chain — matching the app suite's standing convention
   of monkeypatching `run_step` (real subprocess correctness is
   `test_gui_executor.py`'s job, not the widget suite's).

## Consequences

### Positive

- Structured, sorted, color-coded QA — plus the per-record locator columns
  (`sample_id`, `analyte_name`, `source_cell`, …) that the stdout summary never
  prints — for the *whole* CLOUD/headless palette, since every QA-producing
  command already emits the same qa.csv schema the executor already parses.
- One generic drop-empty-columns rule renders every tool's QA correctly with
  no per-tool code; the table is empty/hidden for commands that produce none.
- No new dependency: `QTableWidget` ships in the `gui` extra's PySide6.
- The stdout pane is untouched, so failure/crash/usage output is unaffected.

### Negative / accepted trade-offs

- **The offscreen tests certify structure and wiring, not that it looks
  right.** A human must run `autogis-gui` and look. (An offscreen PNG was
  rendered during development: layout order, the table, column separation, and
  the color-coded severity column all confirmed; the cell *text* renders as
  missing-glyph boxes under Qt's fontless `offscreen` platform, which is a
  headless-rendering artifact, not a defect — real text renders on a real
  display, as the walking skeleton was already user-verified to do.)
- **Imports the private `_SEV_ORDER` from the sibling `executor` module.**
  Accepted: same package, nearest owner of that constant, and it avoids a
  second copy of a 4-entry map. A dedicated shared home for one small constant
  would be over-engineering (YAGNI); if a third consumer appears, promote it
  then.
- No column show/hide toggle, no search/filter, no CSV export, no
  click-a-row-to-locate-in-source. Deliberately deferred to keep the slice
  small.
- A **corrupted qa.csv with a row *longer* than the header** would raise an
  `AttributeError` inside the render slot (PySide6 prints it and continues;
  the table just fails to render). Accepted as effectively unreachable: the
  canonical `csv.DictWriter` writes fixed-width rows, and a mid-write crash
  truncates the last row *shorter* (handled by decision 2's `or ""`), never
  longer.
- Unbounded render + `resizeColumnsToContents` on the UI thread — a tool that
  emitted thousands of QA records would briefly stall the window. Walking-
  skeleton scope; marked with a `ponytail:` ceiling comment pointing at a row
  cap as the upgrade path.
- **Latent name hazard (pre-existing, not introduced here):**
  `core/common/qa.py` defines a *same-named but inverted* `_SEV_ORDER`
  (`INFO=0 … CRITICAL=3`) versus the executor's (`CRITICAL=0 … INFO=3`). This
  slice reuses the **executor's**, which is the correct one for a worst-first
  sort — but anyone later consolidating the two must not assume they are
  interchangeable.

Reviewed by an independent Fable adversarial pass (the chapter's standing
pre-merge gate): **verdict MERGE**, nothing HIGH/MEDIUM. Of five LOW findings,
three were fixed (the `None`→`"None"` render, a redundant `clearContents()`,
and a "sortable" wording overclaim corrected to "sorted"); two are the
accepted trade-offs recorded above.

## Alternatives considered

1. **Hardcode a curated column subset** (severity/category/message/action) —
   rejected: it hides exactly the locator columns an analytical-import tool
   fills. Drop-empty is generic and hides nothing real.
2. **Replace the stdout pane with the table** — rejected: stdout still carries
   non-QA output, the reason line, and stderr on crashes, and the table is
   empty for no-QA commands. Both are needed.
3. **Parse the QA out of the stdout text** — rejected: fragile, and ADR-0053
   bans it explicitly. `qa_rows` is the structured source of truth.
4. **Define a local `_SEV_ORDER` copy in `app.py`** — rejected: duplicates a
   domain constant that already lives one module over.
5. **A real-subprocess end-to-end app test** — rejected: the app suite
   monkeypatches `run_step` by convention (executor correctness has its own
   suite); real `qa_rows` population was verified manually instead, and noted
   here.

## Related decisions

- [ADR-0057](0057-gui-walking-skeleton.md) — the walking-skeleton window this
  slice extends.
- [ADR-0053](0053-gui-executor-qa-signal.md) — the executor that produces
  `StepResult.qa_rows`; also the "stdout is never parsed" principle this
  upholds and the `_SEV_ORDER` this reuses.
- [ADR-0050](0050-unified-gui-adapter-direction.md) — PySide6 GUI direction.
- Planning doc `docs/superpowers/specs/2026-07-03-unified-gui-planning.md` §2.3
  — named the generic QA-result display as the feasible MVP piece.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/app.py` (`_show_qa`,
  the `QTableWidget`, `_SEV_COLOR`, handler wiring) and
  `tests/test_gui_app.py` (two offscreen smoke tests).
