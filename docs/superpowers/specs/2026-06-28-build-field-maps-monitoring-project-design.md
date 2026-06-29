# BuildFieldMapsMonitoringProject Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildFieldMapsMonitoringProject (Tool 7.1)
**Priority:** MEDIUM — provisions the layers/fields field crews collect against
**Runtime:** LOCAL (arcpy) — routes through the `.pyt` toolbox (ADR-0006)

---

## Problem

Field crews need a Field Maps project with the right layers (monitoring wells, sample
status, water-level measurements, access notes, photo points, issue flags) and the right
editable fields (`Sampled`, `SampleDate`, `Sampler`, `DTW`, `PurgeVolume`, `AccessIssue`,
`WellCondition`, `PhotoRequired`, `Notes`). Today these are built by hand and drift from
the site's well network and the schema other tools expect.

---

## Approach

**Chosen:** arcpy-bound project builder on the Tools 2–8 pattern. Creating/refreshing
hosted layers and applying the editable-field schema is arcpy/`arcgis` work in the `.pyt`
toolbox. The **layer-and-field plan** — deriving which layers and field definitions are
required from the site config + the canonical field list — is pure and lives in an
arcpy-free core helper that the toolbox and tests share. This keeps the field schema in
one place so `RouteSurvey123Submission` (7.1b) and `ReconcileFieldAndLabData` (7.3) agree
with what the crew collects.

ADR-0002 keeps core arcpy-free; ADR-0006 keeps the `.pyt` toolbox as the UI; the CLI
guards-and-redirects.

**Rejected: hard-coding the field list in the toolbox.** The canonical field set lives in
core so every downstream tool reads the same definition.

**Rejected: a headless build.** Hosted-layer provisioning needs the Pro/arcgis stack; only
the plan is extracted.

---

## Architecture

```
autogis/
  core/envmon/
    fieldmaps_plan.py         ← NEW (arcpy-free: required layers + field defs)
  adapters/
    toolbox.pyt               ← add BuildFieldMapsMonitoringProject tool class
    cli.py                    ← add build-fieldmaps command: _guard + redirect
  runtime/
    capabilities.py           ← register "build-fieldmaps" (requires arcpy)
tests/envmon/
  test_fieldmaps_plan.py      ← NEW (arcpy-free)
  test_cli_guards.py          ← extend: build-fieldmaps guard fires headless
```

---

## Public API

Arcpy-free core (`fieldmaps_plan.py`):

```python
@dataclass
class FieldDef:
    name: str
    field_type: str           # text | date | double | short
    domain: str | None
    editable: bool

@dataclass
class LayerPlan:
    name: str                 # MonitoringWells, SampleStatus, ...
    geometry: str             # point | polyline | none
    fields: list[FieldDef]

def plan_fieldmaps_project(site_config: dict) -> list[LayerPlan]:
    """Derive the required Field Maps layers + editable field schema from site config."""
```

CLI: `_guard("build-fieldmaps")` then a `ClickException` directing to the `.pyt` toolbox.

---

## CLI Command

```
autogis envmon build-fieldmaps --site-config <site.yaml>
# headless: clean guard error -> use the .pyt toolbox tool inside ArcGIS Pro
```

---

## Test Strategy

Arcpy-free:

1. `plan_fieldmaps_project` returns the six canonical layers.
2. MonitoringWells layer carries the editable field set (`Sampled`, `DTW`, ...).
3. Field types/domains match the schema other tools expect.
4. Photo points layer has `point` geometry; sample status table has `none`.
5. Site config with a custom analyte group adds the expected status fields.
6. `build-fieldmaps` CLI raises a clean guard error when arcpy is absent.
