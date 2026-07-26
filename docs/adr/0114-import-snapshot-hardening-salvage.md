# ADR-0114: Import/snapshot hardening salvage — snapshot ID validation and zero-rows QA guard

**Status:** Accepted

**Date:** 2026-07-26

## Context

Two defects in the workbook-import and GDB-snapshot paths were fixed on 2026-07-10 in commit
`62bb92c` on branch `claude/sleepy-wozniak-u2t1xn`. That branch was **never merged**, but its
commit message carried `Closes #219, #220, #221`, so GitHub auto-closed all three issues the
moment the commit was pushed. The fixes never reached `main`, and the branch was subsequently
recommended for deletion three times (housekeeping audits #328 and #349, and PR #338's body) on
the basis that "its one useful commit is superseded" — a conclusion drawn from the branch tip
alone, missing `62bb92c` one commit below it. #219 was noticed and reopened on 2026-07-25;
#220 and #221 remained closed with no fix in the repository.

This ADR records the salvage. The original batch had four parts; only two survive review:

1. **Issue #219 — salvaged.** `export_event_snapshot()` interpolates raw `site_id`/`event_id`
   straight into a GDB folder name with no validation. A value containing `<`, `>`, or any other
   Windows-illegal filename character makes `arcpy.management.CreateFileGDB` fail with an opaque
   `ERROR 999999`, and re-running the same site/event on the same day fails with an equally
   opaque `ERROR 000258: Output ... already exists` (nothing sets `arcpy.env.overwriteOutput`
   on this path, so the collision is loud but unhelpful — not silent, as an earlier draft of
   this ADR claimed). Verified absent from `main`:
   `git grep validate_snapshot_id origin/main` returns nothing.

2. **Issue #220 — salvaged.** `run_import()` reports `qa_status: PASS` when every sheet parses
   zero rows, making a profile/workbook mismatch indistinguishable from a healthy import with no
   findings. Verified absent from `main` behaviorally, not by symbol name: `counts` is computed
   and placed in the summary, but nothing inspects it, so `qa.status()` returns PASS.

3. **Issue #221 — dropped, already fixed on `main` by a different implementation.** The original
   commit added a `normalize_gw_analytical_table` mirror in `table_normalizer.py`. `main` instead
   dispatches `GW_ANALYTICAL` inside `normalize_groundwater.py:164`
   (`sheets_of_type("GW_ANALYTICAL")`), called from `import_to_gdb.py:282`. The capability exists;
   only the artifact name differs. #221 is correctly closed and nothing is salvaged for it.

4. **The `"SOIL"` → `"SOIL_ANALYTICAL"` dispatch change — dropped, now actively wrong.** The
   original commit changed `normalize_soil_table` to filter `sheets_of_type("SOIL_ANALYTICAL")`
   on the premise that `SOIL_ANALYTICAL` was the only valid sheet `data_type`. The repository
   resolved that mismatch in the **opposite** direction: PR #337 (merged 2026-07-25, "KNOWN_SHEET_DATA_TYPES
   uses SOIL, not SOIL_ANALYTICAL") made `"SOIL"` the canonical value, which is what
   `config_validation.KNOWN_SHEET_DATA_TYPES` and `table_normalizer.py:297` both use today.
   Applying the original hunk would point the dispatch at a value no profile declares and no
   validator accepts — re-creating the exact silent zero-rows bug it claimed to fix.

## Decision

Salvage items 1 and 2 only, as a minimal diff onto current `main`:

- Add `validate_snapshot_id(value, label)` to `export_snapshot.py`, rejecting empty values,
  leading/trailing whitespace, and the Windows-illegal set `<>:"/\|?*` plus control characters,
  with a message naming the offending field and character. Call it on `site_id` and `event_id`
  before either is interpolated into the output name. Add a pre-check that raises
  `FileExistsError` when the target snapshot GDB already exists.
- Emit a `zero_rows_parsed` QA `WARNING` from `run_import()` when `counts` is all-zero, naming
  the likely causes (wrong sheet names, unwired `data_type`, workbook/profile mismatch).

Do not salvage items 3 and 4. Leave #221 closed. #220 is reopened and **stays open**: this
closes the "indistinguishable from a healthy run" half, not the "reports PASS/Succeeded" half
(see Consequences).

## Consequences

- `export-snapshot` fails fast with an actionable message naming the offending value or path,
  instead of arcpy's `ERROR 999999` / `ERROR 000258`. The CLI wraps both as `ClickException`
  so the Pro tool dialog shows the message rather than a traceback. The manifest is named after
  its GDB (`<gdb-name>.manifest.json`), so exports sharing an `--out` folder no longer overwrite
  each other's manifest — the `FileExistsError` guard only ever covered the GDB itself.
- A workbook/profile mismatch surfaces as a `zero_rows_parsed` QA WARNING. **`qa_status` remains
  `PASS`** — `QACollector.status` defaults `allow_warnings=True`, so a WARNING never flips it, and
  the `.pyt` still reports Succeeded. The run becomes *distinguishable* (a row lands in the QA
  CSV/JSON/MD) but is not rejected: non-blocking is deliberate, because a genuinely empty workbook
  and a matrix filter that matches no sheet are both legitimate inputs. Issue #220's headline
  ("zero rows parsed reports PASS/Succeeded") is therefore only **partially** closed; making it
  blocking would break `--matrix-filter SOIL`, which no shipped profile can satisfy yet the `.pyt`
  offers in its dropdown. The warning names the active matrix filter so the operator can tell the
  two causes apart.
- **A `replace_batch` / `replace_site_event` run that parses zero rows no longer deletes.** Because
  the warning is non-blocking, control previously reached `_delete_for_replace`, which removed the
  prior event's rows before inserting nothing — a profile/workbook mismatch silently *erased* data
  instead of replacing it. The replace is now skipped with a `replace_skipped_zero_rows` WARNING and
  existing data is left untouched.
- `validate_snapshot_id` is importable and unit-tested; `export_event_snapshot` itself stays
  `pragma: no cover` (arcpy seam), so the validation lives outside the untestable boundary.
- Coverage for `run_import()` in `validate_only` mode is new
  (`tests/envmon/test_import_to_gdb.py`) — that mode never touches arcpy, so it runs in CI with
  the rest of `core/`.

## Notes

ADR number: the original commit shipped this as `ADR-0079`, a slot since taken by
`0079-close-canonical-read-merge-gate.md`. Renumbered to 0114 on salvage.

The auto-close-from-an-unmerged-branch failure mode is the second recorded instance in this
repository (see the 2026-07-24 stale-branch audit). The durable lesson is that a `Closes #N`
trailer fires on push, not on merge, so an abandoned branch silently closes its issues.
