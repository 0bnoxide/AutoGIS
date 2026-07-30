# ADR-0121: Groundwater model approval review surfaces

**Status:** Proposed

**Date:** 2026-07-29

## Context

ADR-0085 made `GW_ModelRun.ApprovedModel` and
`GW_ModelRun.ReviewStatus` the durable hydrogeologist decision, with
`approve_gw_model` enforcing that the selected model actually executed. The
only exposed approval path was the `approve-gw-model` CLI. Live ArcGIS Pro QA
in issue #384 showed that a reviewer could inspect the draft contours and
cross-validation results in Pro but then had to discover and assemble a
separate command.

The generic desktop GUI can render the CLI's static options, but it cannot
query a selected geodatabase for DRAFT runs, show per-run ranked statistics,
or refresh the resulting status. The Python toolbox can query the geodatabase
directly but previously exposed no approval tool. Reviewer identity was also
optional at the backend, permitting an unauditable "unspecified" note.

## Decision

1. Add one `read_gw_model_reviews` ArcPy seam that joins `GW_ModelRun` rows to
   their ranked `GW_ModelCrossValidation` rows. Both user interfaces consume
   this shape; neither duplicates model eligibility or approval rules.
2. Add a dedicated desktop **Approve Groundwater Model** dialog. It runs the
   review reader through the configured ArcGIS Pro Python interpreter, lists
   DRAFT runs, displays every executed model plus available ranked statistics,
   requires reviewer identity and explicit confirmation, invokes the existing
   `approve-gw-model` CLI/backend, then refreshes `ApprovedModel` and
   `ReviewStatus`.
3. Add an adjacent Python toolbox **Approve Groundwater Model** tool with the
   same DRAFT-run, executed-model, ranked-statistics, reviewer, confirmation,
   and refreshed-status workflow.
4. Make reviewer name or initials mandatory in `approve_gw_model` itself and
   in the CLI option. The backend remains the source of truth for reviewer
   presence and executed-model eligibility.
5. Do not change the geodatabase schema in this fix. Reviewer and timestamp
   remain appended to `GW_ModelRun.Notes`; structured reviewer/date fields
   require a separate schema decision and migration.

## Consequences

### Positive consequences

- Reviewers can complete inspection and approval without constructing a CLI
  command.
- GUI and toolbox users see the same executed-model universe and ranked
  statistics.
- A model with no cross-validation row remains selectable when it executed,
  preserving ADR-0085's rule that hydrogeologic judgment can diverge from rank.
- Blank reviewer identity is rejected consistently across every caller.
- The existing approval backend and run-history recording remain in use.

### Negative consequences

- The desktop dialog needs a short ArcGIS Pro child process to read the
  geodatabase because the GUI process remains arcpy-free.
- Approval of legacy automation that omitted `--reviewer` becomes a deliberate
  breaking validation change.
- Reviewer and review time remain free text until a later schema migration.

## Alternatives considered

- **Keep only the generic GUI form for `approve-gw-model`** — rejected because
  static Click introspection cannot list DRAFT runs or show ranked statistics,
  and it offers no explicit confirmation/refresh workflow.
- **Duplicate approval updates in GUI/toolbox code** — rejected because it
  would create multiple eligibility and audit-rule implementations.
- **Add structured `Reviewer`/`ReviewDate` fields now** — deferred because it
  changes the published geodatabase schema and needs its own compatibility and
  migration decision.
- **Approve only rank 1** — rejected by ADR-0085; rank is a suggestion, while
  the hydrogeologist may select any model that executed.

## Related decisions

- [ADR-0085: Phase-5 geostatistical architecture review](0085-phase5-geostatistical-architecture-review.md)
- [ADR-0093: Event status and staleness checker](0093-event-status-staleness-checker.md)
- [Issue #384: Expose groundwater-model approval in the GUI and require reviewer identity](https://github.com/0bnoxide/AutoGIS/issues/384)
