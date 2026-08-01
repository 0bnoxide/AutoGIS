# ADR-0120: Report-family input guards: accept both result vocabularies, reject malformed date filters

**Status:** Accepted
**Date:** 2026-07-29

## Context

The headless report family (`build-max-result-dataset`, `build-compliance-table`,
`build-exceedance-event`, the appendix/regulatory/QC builders, the soil-interval
selector and the trend-chart loader) consumes plain `csv.DictReader` dicts rather
than `AnalyticalResultRecord` dataclasses. Two silent-wrong-answer defects grew
out of that, both filed from survey passes:

**Issue #339 — two incompatible column vocabularies.** Those builders hard-coded
a *report* vocabulary (`ResultValue` / `ResultQualifier` / `ReportedUnits`) while
every sibling command reads and writes the *canonical* `AnalyticalResultRecord`
vocabulary (`ResultNumeric` / `Qualifier` / `Units`). Nothing in `autogis/`
actually produces a CSV in the report vocabulary — it was an internally
consistent second convention with no producer. Feeding a report command the
canonical CSV that the rest of the pipeline emits made a detected 50 µg/L benzene
result read as a **nondetect** (the mismatched lookup returns `""`, and
`_is_nondetect` treats an unparseable value as ND), and made
`build_max_result_dataset` **drop the row entirely** — zero output rows, no
error, no QA record. A silent false negative on exceedance detection in a
regulatory-compliance tool is the worst failure class this project's QA
conventions exist to prevent.

**Issue #376 — unvalidated date filters.** Six options across three commands
filtered rows by comparing the *raw option text* against the *raw `SampleDate`
text*, with no parsing at all. Because ISO dates start with a digit and ASCII
digits sort below most letters, a typo'd `--date-from` sorts before every real
date, so `"2026-07-01" >= "not-a-date"` is `False` and **every row** is filtered
out. The command then wrote a near-empty output, printed its usual summary line,
and exited 0 — indistinguishable from a legitimately empty range.

Both defects are invisible to the test suite as it stood: the existing tests
feed the report vocabulary and well-formed dates, which is exactly the input
shape that hides them.

## Decision

Add one shared, arcpy-free module, `autogis/core/envmon/report_input.py`, holding
both guards, and route the eight affected builders through it at their entry
points — the single place all callers, CLI and programmatic alike, pass through.

1. **`normalize_report_rows(rows, qa=None)`** backfills each report-vocabulary
   key from its canonical equivalent (`ResultValue` ← `ResultNumeric`,
   `ResultQualifier` ← `Qualifier`, `ReportedUnits` ← `Units`) wherever the
   report key is absent or blank. This is a **widening, not a rename**: the
   report vocabulary stays the one the builders read, rows already in it pass
   through untouched, and an explicit report value always wins over the
   canonical one. Input dicts are never mutated.

   A row set carrying *neither* vocabulary — the genuinely broken input, which
   also used to fail silently — gets a QA `WARNING`
   (`result_vocabulary_unrecognized`) rather than being coerced. A successful
   substitution records a QA `INFO` (`result_vocabulary_normalized`) so the
   provenance is visible in the report.

2. **`validate_iso_date(value, option)`** raises `ValueError` on anything that is
   not a well-formed `YYYY-MM-DD` date. The check is **round-trip equality**
   (`date.fromisoformat(text).isoformat() == text`), not merely that
   `fromisoformat` succeeded: since Python 3.11 that accepts basic forms like
   `20260701`, which parse fine but compare wrong against the hyphenated
   `SampleDate` text these filters match against lexicographically.

   The three CLI commands catch `ValueError` and re-raise it as
   `click.ClickException`, matching the `ConfigError` handling already used for
   `--screening-levels` on the same commands.

Validation lives in the **core** functions, not the click options, because the
issues' own reproduction cases call `build_max_result_dataset(...)` directly —
a `click.DateTime` type would have left every programmatic caller exposed.

## Consequences

- Feeding a report command the canonical CSV now produces correct
  detect/exceedance classification instead of a silent false negative. This is
  the fix's whole point, and it changes output for any caller who was
  unknowingly passing canonical rows.
- A malformed date filter now fails loudly with a message naming the option and
  the bad value, instead of exiting 0 on an empty result.
- The report vocabulary is no longer a dead-end convention with no producer —
  it is an accepted alias set with one documented mapping table
  (`REPORT_FIELD_ALIASES`), which is where a future rename would be made.
- The guards are cheap (one dict copy per row) and unconditional, so no caller
  has to remember to opt in — the failure mode being fixed was precisely that
  nobody knew to.
- 22 regression tests in `tests/envmon/test_report_input.py` pin both issues'
  literal reproduction cases, including that the pre-existing report-vocabulary
  input still behaves identically.

## Alternatives considered

- **Write an exporter that emits the report vocabulary.** Rejected: it adds a
  producer for a convention that has no reason to exist, and leaves every
  already-written canonical CSV still silently misread.
- **Rename the report vocabulary to the canonical one across all eight
  modules.** A larger diff touching every field read, every fixture and the
  `.pyt` label generators, and it would break any user CSV in the report
  vocabulary. The alias table gets the same correctness for a fraction of the
  blast radius; the rename stays available later.
- **Validate dates with `click.DateTime` on the options.** Rejected: it does not
  protect programmatic callers, and it converts the value to a `datetime` while
  the filters compare strings.
- **Emit a QA warning instead of raising on a malformed date.** Rejected: the
  run's entire output is already wrong by then, and `--report` is optional, so a
  warning could go unread. Exit-code failure is the honest signal.

## Related decisions

- ADR-0075 — canonical-read policy for the widened analytical grain
  (`canonical_read.py`), the sibling seam for canonical-vocabulary consumers.
- ADR-0114 — zero-rows QA guard on `import_to_gdb` (issue #220), the same
  silent-no-op failure class one stage upstream.
- Issues #339, #376.
