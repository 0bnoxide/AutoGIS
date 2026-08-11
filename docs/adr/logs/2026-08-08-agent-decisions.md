# Agent decisions — 2026-08-08

Session: scheduled autonomous run ("fix open issues by significance; check README
staleness; survey for gaps"). Branch `claude/awesome-cray-3n8uib`.
Design decisions are in **ADR-0126**; this log records the autonomous *judgment
calls* that ADR does not, per `docs/adr/logs/README.md`.

## Scope calls

**Skipped the nine issues PR #453 already fixes** (#431, #441, #443–#448, #452)
rather than re-fixing them. Read the PR body first; its batch and this one
overlap in no file.

**Did not touch #449 / #450** (inert analyte-dictionary formatting keys; nine
unused `SITE_REQUIRED` keys + the unwired `Reporter`). Both ask for a *choice*
— "wire it or delete it" — and deleting shipped config keys or relaxing load
validation is an owner call, not a bug fix. Left open, reported.

**Did not touch the owner-gated QA batches** (#195, #231, #238, #272, #307,
#312) — they need a human at an ArcGIS Pro or AGOL console. #388 (slow Windows
CI) and #436 (latent `compute_rpd`, explicitly no production caller) were
ranked below the batch and left.

## Judgment calls inside the fixes

**#420 — shipped both offered options, not one.** The issue framed "add the
columns" and "warn on unknown keys" as alternatives (a)/(b). They are
complements: warning alone still loses every COC number, and columns alone fix
this instance and leave the next one silent. Shipped both. The generic guard is
what found #457 twenty minutes later.

**#420 guard severity: WARNING, not ERROR.** The rows still land, and a producer
carrying legitimate scratch keys should not be blocked from importing. Silence
was the defect, not permissiveness.

**#457 — fixed the normalizer, not the schema, for the three renamed keys.** The
schema names (`EventDate` / `DepthToWater_ft` / `GroundwaterElevation_ft`) are
canonical: `WaterLevelRecord` and the EDD importer both use them, and the
normalizer was the sole outlier. Adding `DTW_ft` etc. as columns would have
ratified the drift. `MeasuredBy` / `MeasurementMethod` did get columns, because
unlike the other three they have no canonical equivalent and they are the exact
analogue of the `SampledBy` / `SampleSource` #420 adds next door.

**#457 — updated two tests that agreed with the bug.**
`test_minimal_payload_returns_water_level` asserted `wl[0]["DTW_ft"] == 12.5`
and `test_survey_sync.py:213` asserted the same. Both pinned a field name that
no table has, so they passed *because* they restated the defect. Rewriting them
to the schema names is a fix, not a weakening — the replacement also asserts
`EventDate is not None`, which is the half that collapsed the unique key.

**#412 — widened which record is found, never what counts as success.** The
fallback fires only when the site-scoped lookup finds nothing *and* a site was
actually asked for; a failed site-less run still fails, and a site-scoped tool
still matches strictly. Three negative-control tests pin exactly that, and they
pass both before and after the fix by design — they guard against
over-broadening rather than pinning the defect.

**#454 — chose the two-line stderr warning over the sentinel-return option the
issue sketched.** Threading `None` through `_scan_max` changes every caller's
arithmetic to carry a flag; printing at the point of degradation reaches every
caller, in-process and via subprocess, for two lines. Rejected the MCP-fallback
option outright as YAGNI — the issue itself says option 1 alone would have
prevented the live instance.

**#425 — max of both trees, not "the caller's tree instead".** Scanning only the
caller's worktree just moves which tree can be stale.

## Found and filed rather than fixed

**#457** (new, fixed here) and **#458** (new, mostly not fixed) were filed
during the work per the standing found-bug rule.

For #458 (six tools carrying another tool's catalog `Tool N.N` number) only the
seventh case was corrected: `DroneGCPCheckpointQA` claimed `Tool 11.1`, which
belongs to **AIDraftParserProfile** — a tool CLAUDE.md records as deferred and
unstarted. A shipped tool wearing a deferred tool's number contradicts the
tracker's own headline claim, and the row's `Roadmap #` column already said the
right answer (8.7). The other six are genuinely ambiguous — the README's own
column disagrees with its description — so guessing would have been worse than
filing.

## Fixed en route, outside any issue

**`.claude/hooks/session-start.sh` installed a hand-maintained dep list behind
`--no-deps`.** That list had drifted behind `pyproject`'s `dependencies` (never
gained `numpy` or `xlrd`), so this very session collected **4
`ModuleNotFoundError: numpy` errors before a single test ran** — every fresh
cloud session starts on a red suite. Replaced the list with `pip install pytest
-e "$PROJECT_DIR"`, letting pip resolve `dependencies` itself so the class
cannot recur; the heavy extras stay out because they are extras, not deps. Its
stale "113-test suite" comment (the suite is ~2980) went with it.

Also switched that hook's `bash "$SYNC"` to `"${BASH:-bash}" "$SYNC"` — the
hook-side half of #455, where bare `bash` can re-resolve to an interpreter that
cannot read the path the outer shell just tested.

## Not done

No live-Pro verification: this is a cloud session with no arcpy. The schema bump
to 2.8 and the `.pyt`-adjacent behavior are pinned by headless tests and the
additive `upgrade-schema` path only; a Pro run is still owed before the 2.8
schema is trusted in the field.
