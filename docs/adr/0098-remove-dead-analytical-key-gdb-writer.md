# ADR-0098: Remove the orphaned Env_AnalyticalKey GDB writer (dead code)

**Status:** Accepted

**Date:** 2026-07-21

## Context

Finding **F3** from the live arcpy execute-body campaign (ADR-0096, issue #272):
`build_analytical_key.write_analytical_key_gdb_table()` opened
`arcpy.da.InsertCursor` on an `Env_AnalyticalKey` table and failed with
`cannot open …\Env_AnalyticalKey` — because that table is **not declared in
`gdb_schema.py`** (neither `TABLE_SCHEMAS` nor `FEATURE_SCHEMAS`).

Reachability check (read-only) before deciding:

- **No caller.** `git grep write_analytical_key_gdb_table` across `autogis/` and
  `tests/` returns only the definition and a docstring mention. It is not in the
  `.pyt` toolbox, the CLI (`build-analytical-key` imports only `build_analytical_key`,
  `format_key_markdown`, `write_key_csv`, `write_key_xlsx`), or any dynamic dispatch.
- **`Env_AnalyticalKey` exists only in design docs.** The 2026-06-27/28 plans/specs
  for Tool 5.5 intended a GDB feature-class output (add the table to `TABLE_SCHEMAS`,
  add a `--gdb` CLI option). Those tasks were never implemented — only the
  CSV / XLSX / Markdown path shipped. The GDB writer is the abandoned remnant.

So the function is dead code that has never been able to run: no caller, no
target table, no test.

## Decision

Delete `write_analytical_key_gdb_table` and correct the module docstring. Keep
the shipped, tested CSV / XLSX / Markdown writers unchanged.

No regression pin is added: this is a pure deletion (removing logic, not adding
it); the existing `test_build_analytical_key` suite covers the remaining writers.
The general "a writer targets a table absent from the schema" guard is issue
#272 Option 2's job (executing tool bodies against a scratch GDB — which is how
F3 was found).

## Consequences

- The latent trap (a function that raises if ever called) is gone; `python -m
  pytest -q` still passes (2330).
- If a GDB output for the analytical key is wanted later, implement it fully —
  add `Env_AnalyticalKey` to the schema, wire the CLI/`.pyt` option, and test the
  write path — rather than resurrecting an untested stub.

## Alternatives considered

- **Complete the feature** (add the table + CLI wiring + tests): rejected as
  scope creep — nothing requests the GDB output today (YAGNI), and F3 is a
  correctness finding, not a feature request.
- **Leave it with a TODO:** rejected — it is unreachable and non-functional;
  keeping it is the exact false-comfort #272 warns about.

## Related

Issue #272 (automated arcpy testing umbrella), ADR-0096 (F2) + ADR-0097 (F1) —
the other two campaign findings.
