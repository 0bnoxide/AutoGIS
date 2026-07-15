# Agent decisions — 2026-07-15 (maintenance-sweep consolidation)

Judgment calls made while consolidating three overlapping, unmerged maintenance
branches (`claude/sleepy-wozniak-qo6o8t` / `-ts261r` / `-r6eu8m`) into one clean
change on current `main`. The branches each did partial, drifting housekeeping;
this folds the verifiable, still-relevant parts and drops the rest.

## Boundary-import test: conditional skip, not unconditional
**Decision:** Adopt `ts261r`'s approach — skip `autogis.adapters.gui.*` in
`test_every_autogis_module_imports_headless` **only when PySide6 is absent** —
over `qo6o8t`/`r6eu8m`'s unconditional skip.
**Reasoning:** The test enforces the arcpy/arcgis boundary. An unconditional
skip blinds it to the GUI modules forever, even in a full-`[gui]` env where an
accidental eager `import arcpy` in a GUI module *could* be caught. The
conditional probe preserves the guarantee where the extra is installed and only
concedes where the module genuinely can't import (no PySide6). Slightly more
code, strictly more correct on the edge case — the right trade for a boundary
test.
**Revisit if:** the GUI subtree grows a legitimate reason to import arcpy.

## ADR-0023 unit-conversion refs: fix all four, not the one hyperlink
**Decision:** Change **all four** `ADR-018` references in
`0023-workgroup-2-post-import-qa-scope.md` to `ADR-022`; `qo6o8t` fixed only the
broken hyperlink (line 107).
**Reasoning:** `0022-screening-unit-conversion-invariant.md` is the
unit-conversion ADR; `0018` is the unrelated GDB-schema tool. All four refs sit
in a unit-conversion context, so all four were the same mislabel. Fixing one
symptom leaves three wrong. Root-cause over symptom.

## ADR index gap-fill: add 083 too, not just qo6o8t's 067/069/070/071
**Decision:** Add index rows for **067, 069, 070, 071, and 083**.
**Reasoning:** A full file-vs-index audit showed five missing entries. `qo6o8t`
predates ADR-0083, which PR #232 shipped without indexing. Consolidating the
"index gaps" task means closing all of them, not replaying a stale subset.

## README test-count (2129) left unchanged
**Decision:** Do **not** re-pin the README test count.
**Reasoning:** The count is extras-dependent — `--collect-only` yields 2060 in a
`[dev]`-only env vs the ~2129 baseline measured with full extras (PySide6/torch).
Re-pinning to a partial-env number understates the suite and restarts exactly
the drift that made these three branches redundant. Flagged for the maintainer
to refresh from a full-extras env, or to make the line env-qualified.
**Revisit if:** a full-extras measurement is available, or the README adopts an
env-qualified phrasing.

## Orphaned decision logs on ts261r / r6eu8m not imported
**Decision:** Do not fold the `2026-07-11` / `-07-12` / `-07-13`
agent-decision logs from the other two branches into this change.
**Reasoning:** They audit autonomous calls from other unmerged sessions that I
cannot verify. Importing another session's audit record as if it were mine
misrepresents authorship. Left for the maintainer to decide whether that work
still matters.
