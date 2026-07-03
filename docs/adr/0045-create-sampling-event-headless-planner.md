# ADR-0045: CreateSurvey123SamplingEvent (2.7) — headless pre-field planner; plan's SampleID format over the spec's

**Status:** Accepted

**Date:** 2026-07-03

## Context

Roadmap tool 2.7 (`CreateSurvey123SamplingEvent`) generates the pre-field
planning artifact for a sampling event: expected-sample table, crew
assignment, and a chain-of-custody draft, as a three-sheet XLSX workbook. It
was the first of the last four "Planned" roadmap tools, built from the
reconciled brief
`docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md`.

Two design docs existed and disagreed:

- spec `docs/superpowers/specs/2026-06-28-create-survey123-sampling-event-design.md`
  — SampleID `{site_id}-{location_no_dashes}-{YYYYMMDD}-{matrix}`, plus a
  `QACollector`/`--report` output and `--coc-template` support.
- plan `docs/superpowers/plans/2026-06-28-create-survey123-sampling-event.md`
  — SampleID `{WellID}-{YYYYMMDD}-{Matrix}`, TDD-complete, no QA report or
  COC template.

## Decision

**Build from the plan, not the spec.** Decisive reason: the plan's SampleID
format (`{WellID}-{YYYYMMDD}-{Matrix}`, `-FD` suffix for field duplicates)
matches the live Survey123 form builder's calculation exactly
(`survey123_form_builder.py`, `concat(${WellID}, "-",
format-date(${SamplingDate}, "%Y%m%d"), "-", ${Matrix})`), so
`ReconcileSurvey123AndLabResults` (2.6) can reconcile planned vs. collected
samples by ID. The spec's format would silently break that reconciliation.

Shape:

- `core/envmon/create_sampling_event.py` — pure-stdlib planner
  (dataclasses, round-robin crew assignment, field-dup injection at
  `dup_frequency`, per-well COC numbering). `run_id`/`event_date` are
  injected parameters, never generated internally, for deterministic tests.
- `core/envmon/sampling_event_writer.py` — openpyxl three-sheet writer
  (`Expected_Samples`, `Crew_Assignment`, `COC_Draft`).
- CLI `envmon create-sampling-event` (headless/CLOUD, no `_guard`), plus a
  `_REGISTRY_SEED` entry in `runtime/capabilities.py` (CI-enforced by
  `test_every_envmon_command_registered_for_discovery`). No `TOOLS` dict
  entry — that map drives the arcpy guard, which this tool never calls.
- `event_config["analyte_groups"]` stays `{group: [analyte_names]}` — the
  exact structure `survey123_form_builder.build_xlsform()` consumes, so one
  event config feeds both 7.1a and 2.7. Container/preservative/hold-time
  metadata lives in a separate additive `group_sampling` section.

**Accepted v1 scope cuts (from the "Approved" spec, per the brief):** no
`QACollector`/`--report` output, no `--coc-template`; trip/equipment blanks
are a non-goal (the COC sheet has a free-text `ExtraBottles` column for
crews). Analyte names are validated against the analyte dictionary at plan
time, so misspellings fail before the crew reaches the field.

## Consequences

### Positive consequences

- Planned samples reconcile 1:1 with Survey123 submissions and lab EDDs by
  SampleID; no translation layer needed for 2.6.
- Planner is arcpy-free and openpyxl-free (writer isolates the openpyxl
  dependency); all 34 new tests run headless.
- Shared event-config contract with the form builder — one YAML per event.

### Negative consequences

- No QA-report surface on this tool for now; if field-planning QA is needed
  it must be re-added deliberately (the spec's design is still on file).
- Trip/equipment blanks are manual (free-text column), not modeled rows.
- One workbook naming convention (`{site_id}_{event_name}_sampling_plan.xlsx`)
  assumes filesystem-safe `event_name` values (e.g. "2026-Q2").

## Alternatives considered

1. **Build from the spec as written:** rejected — its SampleID format breaks
   reconciliation with the shipped 7.1a form builder, and its QA/COC-template
   surface is unneeded for v1 (YAGNI).
2. **Enrich `analyte_groups` with container/preservative metadata:** rejected
   — would silently break shared event configs passed to
   `build_xlsform()`; a separate `group_sampling` section is additive.
3. **Conflate with `create-sampling-plan` (7.2):** rejected — 7.2 is the
   GIS-backed sampling *plan* tool; 2.7 is the Survey123-aligned pre-field
   *event* workbook. Distinct tools by roadmap definition.

## Related decisions

- [ADR-0021: Survey123 XLSForm builder — headless openpyxl](0021-survey123-xlsform-builder-headless-openpyxl.md)
  — the form-builder contract this tool's SampleID format and
  `analyte_groups` structure align with.
- `docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md` — the
  reconciled implementation brief (registration checklist, plan-over-spec
  resolution).
- `docs/superpowers/plans/2026-06-28-create-survey123-sampling-event.md` —
  the implementation plan followed.
