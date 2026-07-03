# ADR-0043: BuildFieldMapsMonitoringProject (7.1) — CLI-first plan/provision split; 7.1b field names over the spec's prose

**Status:** Accepted

**Date:** 2026-07-02

## Context

Roadmap tool 7.1 provisions the Field Maps layers field crews collect
against (monitoring wells, sample status, water levels, access notes, photo
points, issue flags) with the editable fields other tools expect. The
approved spec
(`docs/superpowers/specs/2026-06-28-build-field-maps-monitoring-project-design.md`)
predates ADR-0039 in two ways:

1. **Architecture:** it routes the tool through the `.pyt` toolbox with a
   guard-and-redirect CLI — the pre-ADR-0039 generation-1 pattern.
2. **Field names:** its prose lists `Sampled, SampleDate, Sampler, DTW,
   PurgeVolume, AccessIssue, WellCondition, PhotoRequired, Notes`, but the
   two shipped tools the spec itself says must agree with this schema use
   different names. `RouteSurvey123Submission` (7.1b,
   `normalize_survey123.Survey123Field` defaults) reads collection payloads
   via `WellID` / `SamplingDate` / `SampledBy` / `COCNumber` / `Matrix` /
   `DepthToWater_ft` — not `SampleDate` / `Sampler` / `DTW`.
   `ReconcileFieldAndLabData` (7.3) consumes CSVs keyed on
   `sample_id`/`location_id`/`collection_date`/`matrix`, fed downstream of
   7.1b's normalization, so 7.1b's names are the binding contract.

## Decision

**CLI-first per ADR-0039.** `envmon build-fieldmaps --site-config <site.yaml>
[--event-config <event.yaml>] --gdb <path> | --dry-run` executes directly: no
`.pyt` entry (the Problem statement needs no interactive map context), guard
via `_guard("build-fieldmaps")` only on the `--gdb` write path; `--dry-run`
prints the plan headlessly.

**Plan/provision split.** `core/envmon/fieldmaps_plan.py` holds both halves:

- `plan_fieldmaps_project(site_config) -> list[LayerPlan]` — arcpy-free.
  Six canonical layers; the wells layer name comes from the site config's
  `monitoring_wells_fc`; `analyte_groups` (merged in from an event config by
  the CLI — site configs don't carry it, event configs do) adds one
  `Status_<group>` text field per group on SampleStatus.
- `provision_fieldmaps_layers(gdb, plans, qa, *, spatial_reference=None)` —
  the thin arcpy shell (function-scope `arcpy_env`, ADR-0040 style B).
  Additive refresh: creates missing tables/feature classes/coded-value
  domains, adds missing fields, never drops or rewrites existing ones.
  Tested with mocked arcpy (same pattern as `test_layout_manager.py`).

**Field names follow shipped code, not the spec's prose.** The editable set
is `Sampled, SamplingDate, SampledBy, COCNumber, Matrix, DepthToWater_ft,
PurgeVolume, AccessIssue, WellCondition, PhotoRequired, Notes` —
`SamplingDate`/`SampledBy`/`DepthToWater_ft` replace the spec's
`SampleDate`/`Sampler`/`DTW`, and `COCNumber`/`Matrix` are added because
7.1b's default field map reads them. A Field Maps export therefore feeds
`route-survey123` with zero field-map overrides.

**Provision a file GDB; reuse 6.1 for hosting.** The shell writes layer/field
schema into a file GDB. Creating *hosted* layers is deliberately not built
here: `agol publish-layer` (PublishEnvironmentalLayersToAGOL, 6.1) already
publishes a GDB to AGOL, and duplicating that would create a second
publishing authority. `FieldDef.editable` is plan metadata — a file GDB
cannot enforce per-field editability; it is applied when configuring the
Field Maps form on the published layer.

## Consequences

### Positive consequences

- The field schema lives in one arcpy-free place; 7.1b agrees with what
  crews collect by construction, not by convention.
- Fully testable without Pro: plan derivation is pure, provisioning is
  mocked-arcpy, and the CLI has a headless `--dry-run` path plus a clean
  guard test.
- No second attachment/publishing pathway; Field Maps hosting reuses 6.1.

### Negative consequences

- The spec's six test-strategy items are honored but two shift meaning:
  "site config with a custom analyte group" is satisfied by the CLI merging
  `--event-config` into the site dict (site configs don't carry
  `analyte_groups`).
- `editable=False` is advisory until the layer is published and the Field
  Maps form is configured — the GDB itself cannot enforce it.

## Alternatives considered

1. **Guard-and-redirect to a new `.pyt` tool class (as the spec's
   Architecture section says):** rejected per ADR-0039 — generation-2 LOCAL
   tools are CLI-first; no interactive map context is needed.
2. **Use the spec's prose field names (`Sampler`/`DTW`/`SampleDate`):**
   rejected — 7.1b is shipped, load-bearing production code; renaming its
   defaults to match a spec's prose would break existing Survey123 forms,
   while matching 7.1b costs nothing.
3. **Create hosted feature layers directly via the `arcgis` API:** rejected —
   duplicates `agol publish-layer` (6.1) and adds a large untestable surface
   for a workflow Pro already covers (publish the provisioned GDB).

## Related decisions

- [ADR-0039: Generation-2 LOCAL tools are CLI-first](0039-cli-first-generation-2-local-tools.md)
  — governs the command shape; the spec predates it.
- [ADR-0040: Canonical arcpy-access style](0040-canonical-arcpy-access-style.md)
  — the provisioning shell uses style B.
- [ADR-0002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) —
  `fieldmaps_plan.py` imports without arcpy; the shell is lazy.
- `docs/superpowers/specs/2026-06-28-build-field-maps-monitoring-project-design.md`
  — implemented spec, marked partially superseded as built.
- `docs/superpowers/specs/2026-07-02-remaining-roadmap-items-brief.md` §2 —
  flagged both the ADR-0039 correction and the field-name cross-check.
