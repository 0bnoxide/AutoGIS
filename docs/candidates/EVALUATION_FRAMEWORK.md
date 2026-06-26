# Candidate Roadmap Evaluation Framework

## Purpose

Evaluate whether proposed tools/features from candidate roadmaps fit the AutoGIS hybrid harness architecture before integrating them into the primary `envmon-feature-roadmap.md`.

---

## Evaluation Criteria

For each tool proposed in a candidate roadmap, assess whether it meets ALL three execution modes:

### 1. Local Mode (ArcGIS Pro Toolbox)
- Can the tool run as an ArcGIS Pro Python toolbox?
- Does it need arcpy or is it arcpy-free compatible?
- Can it read/write to local geodatabases and files?

### 2. CLI Mode (Command-Line Harness)
- Can the tool run via command-line for batch processing?
- Is it repeatable and scriptable?
- Can it produce consistent outputs across runs?
- Does it support exit codes and QA status reporting?

### 3. AGOL/Cloud Mode (Webhook/Trigger)
- Can the tool run via AGOL webhooks or cloud triggers?
- Can it read from hosted feature layers?
- Can it write back to AGOL or post results to dashboards?
- Does it handle asynchronous execution?

### 4. Shared Infrastructure
- Does it leverage the shared config layer (site configs, screening levels, analyte dictionaries)?
- Does it write to the common QA/logging framework?
- Does it consume from or produce normalized tables in the schema?
- Does it use shared utilities (unit validation, schema checks, batch manifests)?

---

## Decision Gate

**Integrate into main roadmap if:**
- Tool can run in all three modes (local + CLI + AGOL/cloud)
- Tool leverages/extends shared infrastructure (config, QA, logging)
- Tool feeds into or consumes from normalized environmental schema
- Tool aligns with existing execution patterns

**Keep as separate-repo candidate if:**
- Tool is specialized to one execution mode only (e.g., local GUI only)
- Tool requires external dependencies (Civil 3D, proprietary geotechnical software)
- Tool covers domain outside immediate environmental monitoring scope
- Tool doesn't integrate cleanly with current architecture

---

## Candidate Roadmaps

### Survey123, AGOL, Dashboard, Geostatistical Pipeline
**File:** `survey123-agol-dashboard-geostatistical-roadmap.md`

**Status:** Pending evaluation

**High-value tools to assess:**
- `RunFieldToGroundwaterModelPipeline` (all three modes?)
- `BuildDashboardDataMart` (data flow alignment?)
- `ReconcileSurvey123AndLabResults` (schema fit?)
- `RouteSurvey123Submission` (webhook architecture?)

---

### Boring, Survey, Drone, Level Automation
**File:** `boring-survey-drone-level-automation-roadmap.md`

**Status:** Pending evaluation

**High-value tools to assess:**
- `ProcessLevelLoop` (CLI + harness fit?)
- `ImportFieldBoringLogs` (schema extension needed?)
- `GenerateBoringLogPDFs` (local + CLI modes?)
- `SurveyToWellElevationUpdate` (integration with GWE calculations?)

---

## Next Steps

1. Review tools in each roadmap against evaluation criteria
2. Flag tools that fit all three modes + shared infrastructure
3. Create impact assessment for tools that require schema extension
4. Decide which tools to fast-track vs. defer to separate repo
5. Document decision rationale in ADR if major architectural changes needed

---

## Last Updated
2026-06-25
