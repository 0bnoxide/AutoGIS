# Brief: the last 4 roadmap gaps (1 Foundation-laid + 3 Not-started)

**Date:** 2026-07-02
**Status:** Orientation brief, not a design doc — hands off to Fable to plan
(spec/plan), Sonnet to implement, Fable to review, per this repo's established
workflow (see ADR-0036's Deciders line for the pattern).
**Scope:** README's *Foundation laid* + *Not started* sections, minus the two
groups CLAUDE.md keeps out of scope (§11 AI-assisted, Phase 5 geostatistical —
**do not touch those**, standing phase-gate policy). That leaves 5 named
items; one of them (`ValidateSurveyDeliverable`) turns out to need zero new
code — see below.

---

## Read this first: ADR-0039 changed the target architecture out from under two existing specs

`docs/adr/0039-cli-first-generation-2-local-tools.md` (2026-07-02, landed via
PR #128 the same day as this brief) established that **generation-2 LOCAL
tools are CLI-first**: lazy-arcpy directly inside the CLI command, run in a
cloned `arcgispro-py3` env. A `.pyt` entry is added only when a tool needs
interactive map context. ADR-0006 (`.pyt` is primary UI, CLI guards-and-redirects)
still governs tools 2-8 only, not anything built since.

Both existing specs for items below (§1 and §2) were written 2026-06-28,
**before** ADR-0039, and both explicitly choose the now-superseded pattern
("arcpy-bound ... lives in the `.pyt` toolbox ... CLI guards-and-redirects").
Follow ADR-0039, not those two specs' Architecture sections. Everything else
in them (Problem, Public API shape, Test Strategy) is still useful — just
swap "guard-and-redirect to `.pyt`" for "CLI executes directly, lazy arcpy
import, `# pragma: no cover` on the arcpy-touching function, tested with
mocked arcpy objects" (the pattern every generation-2 LOCAL tool already
uses — see `survey_to_well_elevation.py` / its CLI command for a clean
reference).

---

## 1. UpdateLayoutDynamicText (5.8) — Foundation laid

**Don't write a new module. The core logic already exists and is already in
production.** `autogis/core/envmon/layout_manager.py::update_layout_text()`
sets named layout text elements *and* resolves `{{placeholder}}` tokens with
a QA warning on anything unresolved — it's already more capable than either
existing design doc's proposal. It's called today from `toolbox.pyt` as part
of the report-figure-package pipeline (line ~498, sourcing
`site_config['default_layout_text']` + `figure_spec['layout_text']`).

The actual gap: **no standalone CLI command** lets someone run just this step
against an arbitrary APRX + a YAML values file, which is what roadmap tool
5.8 and both existing docs ask for.

Two conflicting, both-now-stale planning artifacts exist and should be
superseded rather than followed:
- `docs/superpowers/specs/2026-06-28-update-layout-dynamic-text-design.md` —
  proposes a new `layout_text.py` with `resolve_layout_text(metadata,
  field_spec, figure_number_start=...)`.
- `docs/superpowers/plans/2026-06-28-update-layout-dynamic-text.md` —
  proposes a *different* new `layout_text_updater.py` with
  `apply_substitutions()` / `load_substitutions_from_yaml()`, and a full
  TDD walkthrough already written. Neither references `layout_manager.py`.

**Recommended shape:** add `envmon update-layout-text --aprx <path> --layout
<name> --values <values.yaml>` to `cli.py`, CLI-first per ADR-0039 (lazy
arcpy, `_guard`-free since it's generation-2 — check `_guard`'s current
generic message still applies), calling the *existing*
`layout_manager.update_layout_text()` directly. The plan's
`load_substitutions_from_yaml()` (flat-mapping or list-of-dicts YAML → a
substitutions structure) is worth keeping since `layout_manager.py` doesn't
have a YAML loader yet — that's genuinely new, small, arcpy-free, and
testable. Everything else in the plan's Task 1 (the `TextSubstitution` /
`apply_substitutions` reimplementation) is redundant with
`update_layout_text()`'s existing placeholder/named-element logic and should
be dropped.

Mark both stale docs superseded-by-this-brief (or delete the plan, since its
Task 1 code would duplicate shipped functionality) before or during
implementation, so a future session doesn't resurrect the redundant module.

---

## 2. BuildFieldMapsMonitoringProject (7.1) — Not started, has a spec

Spec: `docs/superpowers/specs/2026-06-28-build-field-maps-monitoring-project-design.md`
— Approved, otherwise solid: arcpy-free `fieldmaps_plan.py` core
(`plan_fieldmaps_project(site_config) -> list[LayerPlan]`, six canonical
layers incl. MonitoringWells/SampleStatus/PhotoPoints with the editable
field set crews need), arcpy-bound layer/field provisioning as a thin shell
around it. Test strategy section is complete and arcpy-free-testable as
written.

**Only correction needed: the Architecture section's ".pyt toolbox is the
UI, CLI guards-and-redirects" is the pre-ADR-0039 pattern.** No plan doc
exists yet — write it CLI-first (`envmon build-fieldmaps --site-config
<site.yaml>` executes directly, lazy arcpy for the hosted-layer/field
provisioning half; a `.pyt` entry is optional/deferred unless someone
determines interactive layer selection is actually needed, which the spec's
Problem statement doesn't suggest).

Cross-check before implementing: the spec notes the field schema should
match what `RouteSurvey123Submission` (7.1b) and `ReconcileFieldAndLabData`
(7.3) expect — both already shipped. Diff `fieldmaps_plan.py`'s proposed
field list against those two tools' actual field names before finalizing,
not just against the spec's prose list.

---

## 3. GenerateBoringLogPDFs (8.0c) — Not started, has a spec

Spec: `docs/superpowers/specs/2026-06-28-generate-boring-log-pdfs-design.md`
— Approved, fully headless (no arcpy at all — Markdown/CSV assembly only,
PDF rendering explicitly deferred as a downstream step, matching this repo's
zero-PDF-dependency discipline). No ADR-0039 concern here since it's not a
LOCAL tool. No plan doc exists yet.

Depends on `CreateBoringLogDatabase` (8.0a), which has shipped
(`core/envmon/boring_database.py`, `envmon create-boring-log-db`). **Before
planning, read `boring_database.py`'s actual read/query API** — the spec's
`build_boring_log()` signature assumes keyword args (`location`, `lithology`,
`samples`, `construction`, `groundwater`, `photos`) as pre-fetched dicts/lists;
confirm those match what `boring_database.py` actually returns rather than
assuming the spec author already verified the shape. This is the one item
here that's ready to plan-and-build close to as-written — lowest risk of the
three "has a spec" items.

---

## 4. SyncAGOLFeatureLayerToGDB (6.2) — Not started, no spec

No spec exists — genuinely spec-less, write one fresh. Roadmap source
(`docs/envmon-feature-roadmap.md` §6.2): downloads hosted feature layer
*edits* into the local FGDB — field-collected well status, sample status,
access constraints, photo attachments, staff comments.

**Shape it as HYBRID, following the established `--source-csv`/`--gdb`
mutually-exclusive-flags-on-one-command convention** (see
`survey-to-well-elevation`'s CLI command in `cli.py` for the exact pattern:
one command, `--wells-csv` for headless, `--gdb` for the arcpy write, both
guarded/dispatched inline, CLI-first per ADR-0039 — no `.pyt` needed unless
interactive layer picking turns out to matter):

- **CLOUD half:** fetch feature-layer records via the `arcgis` REST API.
  Reuse the injected-`gis` pattern already established in `core/agol/*`
  (`gis` passed as first positional arg, lazy `arcgis` import, testable with
  a fake `gis`) — see `core/agol/audit_schema.py::fetch_layer_schema()` for
  attribute-reading and `cli.py`'s `agol_from_profile(profile)` helper for
  session construction, already used by `audit-schema`/`audit-dependencies`.
- **LOCAL half:** write the normalized records into the FGDB — arcpy,
  guarded, CLI-first.

**Check for overlap with the Attachment Harvester before designing the
photo-attachments half.** `core/harvest/` already downloads photos/
attachments from a feature layer via the AGOL REST API
(`download.py`, `gis_session.py`) — that's shipped, separate-domain
functionality (`autogis harvest`). Roadmap 6.2 lists "photo attachments" as
one of its use cases; confirm during spec-writing whether 6.2 should call
into the existing Harvester for that piece (reuse) or whether 6.2 is scoped
to attribute/status sync only and attachments stay the Harvester's job
(no overlap). Don't silently build a second attachment downloader.

---

## 5. ValidateSurveyDeliverable — Not started, but actually already resolved

**No implementation needed.** `docs/superpowers/specs/2026-06-28-roadmap-duplicate-tools-fold-decision.md`
already decided (2026-06-28) that this tool folds into `ValidateRTKSurvey`
(8.4), which has shipped (`envmon validate-rtk-survey`) and already covers
the full check list (duplicate point IDs, missing elevations, invalid codes,
coordinate outliers, wrong units, wrong CRS, missing control points) —
`ValidateSurveyDeliverable`'s checks are a strict subset.

The README's "Not started" listing is stale; it should note the fold instead
of implying open work. That's a one-line README correction, not a Fable
planning task — flagging here so it doesn't get planned by mistake, and
someone should make that correction (small enough to do in the same PR as
whichever of §1-4 ships first, or standalone).

---

## Suggested order

1. **UpdateLayoutDynamicText (5.8)** first — smallest scope, mostly wiring +
   one small YAML loader, no spec-vs-ADR-0039 rewrite needed beyond the CLI
   command shape, immediately closes the last Foundation-laid entry to zero.
2. **GenerateBoringLogPDFs (8.0c)** — spec is solid, headless, no ADR-0039
   entanglement; verify `boring_database.py`'s API first.
3. **BuildFieldMapsMonitoringProject (7.1)** — spec solid modulo the
   ADR-0039 architecture correction; cross-check field names against 7.1b/7.3
   before finalizing the plan.
4. **SyncAGOLFeatureLayerToGDB (6.2)** — needs a fresh spec; resolve the
   Harvester-overlap question during spec-writing, before Sonnet implements.
5. **ValidateSurveyDeliverable** — not a build task; fix the README line
   whenever convenient.

Each ships the usual way: ADR for the batch/tool-level decision (per
CLAUDE.md's Decision records section), README tracker update, tests run
before commit.
