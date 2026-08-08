# ADR-0126: Unmatchable records and unguarded numbers (2026-08-08) — make the degraded answer tell you it is degraded

**Status:** Proposed

**Date:** 2026-08-08

## Context

Five open issues, filed across three separate sessions, share one failure class
that ADR-0124's batch did not cover. ADR-0124 was about *doing something
plausible instead of saying you could not do the right thing*. This batch is
narrower and nastier: **a lookup or scan that structurally cannot succeed, and
returns a confident answer anyway.** Nothing raises. Nothing is logged. The
caller cannot distinguish the degraded answer from the guarded one, so it acts
on it.

- **#420** — the Survey123 normalizer emits `COCNumber`, `SampledBy` and
  `SampleSource` on every sample. `Env_Samples` had no such columns. The insert
  path projects each record onto the schema (`[d.get(f) for f in field_names]`),
  so all three were discarded with no exception and no QA record. The operator's
  chain-of-custody number was collected in the field, normalized, and vanished —
  the GDB has no record of which COC a sample belongs to, nor who collected it.
  This is the only *data-loss* member of the batch.
- **#457** — found *while fixing #420*, by running the new guard against the
  other producer on the same call path. The same normalizer emits its
  water-level dict with `MeasurementDate` / `DTW_ft` / `GWE_ft`, none of which
  exist on `Env_WaterLevels` (the schema and `WaterLevelRecord` both say
  `EventDate` / `DepthToWater_ft` / `GroundwaterElevation_ft`). Five of eight
  keys were dropped, so every routed water level landed with **no date and no
  measurement** — and because `EventDate` is part of
  `UNIQUE_KEYS["Env_WaterLevels"]`, it was NULL on every record, so all events
  for a well collapsed onto one key and each one after the first was skipped as
  a duplicate at INFO severity. A season of gauging imports as one empty row per
  well and reports success. This is the more severe defect of the two, and it
  had been filed by nobody.
- **#412** — `RunHistory.latest(tool, site_id)` matches `site_id` by strict
  equality, but site-less tools (`validate-db` and every `.pyt` tool decorated
  `site_config_param=None`) record `site_id=""` on **both** execution paths. A
  site-scoped readiness check could therefore never be satisfied, and its
  `recommended_action` told the operator to run the tool again — which writes
  another `site_id=""` record and fails identically. An unsatisfiable check
  paired with advice that cannot satisfy it.
- **#454** — `_open_pr_max()` is the only thing stopping a new ADR from
  colliding with one an open PR already claimed. It shells out to `gh`.
  Cloud/web sessions have no `gh` at all, `FileNotFoundError` was swallowed, and
  `reserve-adr` printed a number guarded by *half* the scan while looking
  identical to a fully guarded one. It handed out 0124 while open PR #440 was
  already adding `docs/adr/0124-*.md`.
- **#425** — the same scan resolved `docs/adr` from `coord_cli.py.__file__`.
  Pinned/worktree sessions invoke the *shared main-tree* script, so when main
  was behind the branch being reserved for, the scan read stale files and
  returned a number the caller's own worktree had already used.
- **#455** — `test_sync_ponytail_skills`'s skip-guard probed `bash -c "exit 0"`,
  which any machine with a working WSL distro passes. The tests then invoke the
  script by its **Windows** path, which WSL bash cannot resolve. The guard
  passed, the script silently no-op'd, and 5 tests failed red on every
  WSL-equipped dev box — training readers to ignore a red suite.

## Decision

**Where a producer and a consumer disagree, fix the disagreement at the seam
that can see both — and where a check cannot run at all, say so out loud rather
than returning the unguarded answer silently.**

| Issue | Fix |
|---|---|
| #420 | `Env_Samples` gains `COCNumber` / `SampledBy` / `SampleSource` (`SCHEMA_VERSION` → **2.8**, additive, picked up by `upgrade-schema`). Separately, `append_records_idempotent` now emits one `record_fields_not_in_schema` WARNING naming every key it will not store — the projection is shared by every caller, so one guard covers the whole class rather than this one instance |
| #457 | The normalizer emits the **schema's** names (`EventDate`, `DepthToWater_ft`, `GroundwaterElevation_ft`); `Env_WaterLevels` gains `MeasuredBy` / `MeasurementMethod` in the same 2.8 bump, as the water-level analogue of #420's provenance columns. Two tests that had pinned the invented names were updated — they agreed with the bug |
| #412 | A shared `latest_run()` widens to the site-less (`site_id=""`) series when a site-scoped lookup finds nothing — but **only for tools on the explicit `SITE_LESS_TOOLS` allowlist** — and records a `tool_run_not_site_scoped` INFO saying it did. `portfolio_metrics` calls the same helper |
| #454 | `_open_pr_max()` warns on **stderr** when the scan could not run, naming the exception class. The number still prints on stdout, so callers that parse it are unaffected |
| #425 | The ADR scan floor is now the max over **both** trees — coord_cli's own checkout and the caller's worktree (`git rev-parse --show-toplevel`) — because either can be ahead of the other |
| #455 | The guard probes the property the tests actually depend on: that this `bash` can see the script *at its Windows path* (`test -f '<posix path>'`), not merely that it exits 0 |

Two judgment calls worth recording:

**#420 — the site config's schema wins, and the guard is a WARNING not an ERROR.**
The three keys describe field-collection provenance, which is sample-level data,
so `Env_Samples` is where they belong; `COCNumber` mirrors the `BoringSamples`
width so the two agree. The new unmapped-key guard is a WARNING because the rows
still land and a producer carrying legitimate scratch keys should not be blocked
from importing — but it must not be *silent*, which is the entire defect.

**#412 — an allowlist, not "any record whose site_id is empty".**
The issue offered both. The first draft of this batch took the loose branch and
the cold review proved it unsafe: `_record_site_id` returns `""` not only for
structurally site-less commands but for the ~80 per-site commands identified by
`--gdb`/`--results` rather than `--site-id`, *and* for any command whose site
config merely failed to load. Under the loose rule a `generate-qc-summary` run
against **site B's data** made site A's delivery gate report PASS — a false
green on the readiness check, which is worse than the unsatisfiable check it
replaced. `SITE_LESS_TOOLS` now names the six tools that cannot carry a site on
either path, and `test_site_less_tools_match_the_pyt_decorations` derives that
set from `toolbox.pyt` so the allowlist cannot drift from reality.

The widening also had to be shared. `portfolio_metrics` deliberately recomputes
its `missing` list independently of `evaluate_readiness` (ADR-0032) and flags
disagreement — so widening only one of them emitted a delivered row reading
`ready=True` beside `missing_tools=validate-db`. Both now call one `latest_run()`.

**#412 — widen which record is found, never what counts as success.**
The fallback fires only when the site-scoped lookup finds nothing *and* a site
was actually asked for *and* the tool is on the allowlist. A failed site-less run
still fails the check, and a site-scoped tool keeps matching strictly. All pinned
by tests.

## Consequences

### Positive consequences

- The COC number an operator enters in the field now reaches the GDB, and the
  FIELD→COC attribute join the Phase 3 event reconciler needs becomes possible.
- The silent-projection class is closed at the shared seam, not per-producer: any
  future normalizer that emits a key the target table lacks is reported at import
  rather than discovered as missing data in a delivered deliverable.
- `required_tools` can name `validate-db` — arguably the tool a readiness check
  most wants — instead of guaranteeing a permanent FAIL.
- `reserve-adr` in a cloud/web session is now checkable. It proved itself in the
  session that wrote this ADR: it warned, the open PRs were checked, 0125 was
  found taken by PR #453, and 0126 was taken instead.
- Five false-red tests stop firing on WSL-equipped dev machines.

### Negative consequences

- **Schema bump.** A GDB written before 2.8 gains the new columns on the next
  run of any path that self-heals the schema (`run_import`, the EDD importer,
  and now `route-survey123`) or an explicit `envmon upgrade-schema`. Additive-
  only, so no data migrates. `route-survey123` did **not** self-heal before this
  batch, which the 2.8 bump would have turned into a mid-write raise *after* its
  `IN_PROGRESS` batch row was inserted — orphan batch, no `finalize_batch`, no
  QA. It now calls `create_or_update_gdb_schema` first, like its siblings.
- **New WARNING on existing imports.** Any producer already emitting a key the
  target table lacks starts reporting it. That is the point, but it can surface
  on the first run after upgrade in a pipeline that read as clean.
- **#412's fallback is a widening,** even bounded by the allowlist. A site-less
  run is weaker evidence than a site-scoped one; the INFO record is what keeps
  that visible rather than laundering it into a plain PASS. `SITE_LESS_TOOLS` is
  a hand-maintained list — the drift test makes that cheap, not free.
- **stderr noise.** Every `reserve-adr` in a cloud session now prints a warning.
  Correct, but it is unconditional in the environment where it always applies.

## Alternatives considered

- **#420 (b)-only — QA warning, no schema change.** The issue offered "add the
  columns" or "warn on unknown keys" as alternatives. Warning alone surfaces the
  class but still loses the COC number on every import; adding columns alone
  fixes this instance and leaves the next one silent. They are complements, not
  alternatives, so both shipped.
- **#412 direction 2 — derive site identity from the `gdb` path at record time.**
  Rejected as fragile: a path is not a site_id, and it would put a guess into the
  audit trail. Direction 3 (document that `required_tools` may only name
  site-scoped tools) rejects `validate-db`, which is the wrong end to give up.
- **#454 option 2 — an MCP/API fallback for sessions without `gh`.** More useful
  and more work, and it needs a way to reach MCP from a plain subprocess context.
  Option 1 alone would have prevented the live instance; the fallback stays
  available if warnings prove insufficient.
- **#454 sentinel return (`None` instead of `0`) plumbed through to callers.**
  Rejected: it changes `_scan_max`'s signature and every caller's arithmetic to
  carry a flag, when printing at the point of degradation reaches every caller —
  in-process and via subprocess — for two lines.
- **#425 — scan the caller's worktree *instead of* coord_cli's tree.** Rejected:
  it only moves which tree can be stale. The floor is the max of both.

## Related decisions

- [ADR-0124: Silent-failure fix batch (2026-08-03)](0124-silent-failure-fix-batch-2026-08-03.md) — the adjacent class; this batch is the "cannot succeed, answers anyway" variant
- [ADR-0110](0110-ci-and-agent-tooling-batch.md) — introduced `reserve-adr` to close the pre-PR ADR collision window that #454/#425 reopened
- ADR-0068 item 4 / ADR-0054 — the `site_id=""` convention for site-less commands that #412 sits downstream of
- ADR-0076 — fixed the same matching class one level lower, at record time
- [ADR-0112](0112-survey123-optional-add-on-roadmap.md) / [ADR-0123](0123-survey123-phase3-event-reconciliation.md) — the Survey123 track whose Phase 3 reconciler #420 was blocking
- Issues [#412](https://github.com/0bnoxide/AutoGIS/issues/412), [#420](https://github.com/0bnoxide/AutoGIS/issues/420), [#425](https://github.com/0bnoxide/AutoGIS/issues/425), [#454](https://github.com/0bnoxide/AutoGIS/issues/454), [#455](https://github.com/0bnoxide/AutoGIS/issues/455), [#457](https://github.com/0bnoxide/AutoGIS/issues/457)
