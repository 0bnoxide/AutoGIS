# Agent decisions — 2026-07-10 (EDD Step 3 slice 1, branch spec/edd-step3-equis-wmrd)

Supplement to ADR-0082, not a substitute. Autonomous judgment calls made while building the
EQuIS WMRD reader + `Env_QCResults`.

1. **Reversed the D5 dup-as-columns pivot mid-build, on real-file evidence.** The paper mapping
   sketched synthesizing a second QC record from each row's `qc_dup_*` columns (an implied MSD/
   LCSD pivot). Loading the real `B25030623` WMRD export showed MSD/LCSD are already their own
   samples with their own result rows, and `qc_dup_*` on those rows just echoes the row's own
   values (`qc_spike_recovery == qc_dup_spike_recovery` on every populated pair). Implementing
   the sketched pivot as spec'd would have double-counted every MSD/LCSD in the real file — caught
   before it shipped, not after. Replaced with a per-field primary-then-`qc_dup_*`-fallback rule
   and recorded the dup-as-columns question as re-opened at the sxsamp/mining slice, since a
   format that genuinely reports the dup only in columns is still plausible there.

2. **Reused the existing `sample_sheet`/`result_sheet` profile keys plus one new `batch_sheet`
   key**, instead of adding a new `equis:` profile section as the dictionary research initially
   suggested. The `two_tab_xlsx` format already had the two-sheet-name precedent; a third
   sheet-name field is a one-line addition versus a new nested section that every future EQuIS
   profile would have to learn.

3. **Did not write a new writer for `Env_QCResults`.** The existing table-generic
   `append_records_idempotent(gdb, table_name, records, ...)` seam already keys dedup off
   `UNIQUE_KEYS[table_name]`; adding the `Env_QCResults` entry to that dict was sufficient. A
   dedicated `write_qc_results` function would have duplicated logic that already generalizes
   correctly — flagged by ponytail's reuse-before-writing bias.

4. **Chose `f"{value:g}"` formatting only when an actual unit conversion happened, raw text
   passthrough otherwise**, rather than always formatting through `%g`. An early draft always
   applied `:g`, which silently reformatted `"1.0"` to `"1"` on same-unit rows with no conversion
   — caught by the test asserting exact passthrough of `"0.5"`/`"0.1"`/`"1.0"`. Restructured
   `_convert_limit` to track a `converted` flag and only format when it's true.

5. **Scoped the `test_type` casefold fix to the one column the real file evidenced**, rather than
   casefolding the entire Batch_v1 join key defensively. The real export showed
   `test_type` disagreeing in case between Sample_v1/TestResultQC_v1 and Batch_v1; the other four
   join components (method, fraction, column_number, sample id) matched exactly in the real data.
   Broadening the casefold to the whole key on no evidence would risk silently merging batches
   that are legitimately distinct by case in some other lab's export — deferred until a real file
   demonstrates the need.

6. **Appended new `_DATE_FORMATS` entries last, not first.** The real WMRD file's
   `"%m/%d/%Y %H:%M"` / `"%m/%d/%Y %H:%M:%S"` timestamps needed new format strings; appending them
   after the existing entries (rather than prepending, which would change try-order for every
   existing format) means no previously-parsing row can be reparsed into a different value —
   purely additive, ordering-safe.

7. **Deferred the key-collision findings (242/243 analytical, 328/332 QC distinct) as a recorded
   limitation instead of patching the frozen key in-slice.** Consulted the advisor on whether a
   MethodID/run-instance key extension belonged in this slice; confirmed rationale: `UNIQUE_KEYS`
   for `Env_AnalyticalResults` is a cross-format, ADR-0075-frozen key — widening it here would be
   an under-scoped fix decided from one file's evidence, with reimport/dedup consequences for
   every existing format, not just WMRD. Recorded in ADR-0082 as a known limitation and follow-up
   rather than silently absorbed.
