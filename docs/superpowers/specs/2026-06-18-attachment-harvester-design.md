# AutoGIS — Attachment Harvester Design

**Date:** 2026-06-18
**Status:** Approved (design); pending spec review
**Scope:** First tool in the AutoGIS automation suite for ArcGIS Pro and ArcGIS Online / Survey123.

## Purpose

Bulk-download photos and other attachments from an ArcGIS Online / Survey123 hosted
feature layer, organized on disk for a field-inspection workflow. This is the first
tool in a planned suite of ArcGIS automation tools, so it also establishes the shared
core/adapter structure the rest of the suite will reuse.

## Goals

- Harvest attachments from a single feature layer, optionally filtered by a `where` clause.
- Organize downloads into attribute-grouped subfolders with configurable naming.
- Be safely re-runnable (idempotent) and resilient to per-attachment network failures.
- Produce an audit trail (CSV + JSON manifest) per run.
- Be invokable today via a CLI, and cheaply extensible to an ArcGIS Pro toolbox and a
  hosted Notebook later — without rewriting the core logic.

## Non-Goals (YAGNI for this pass)

- Spatial filtering (map-area/extent filters). Attribute `where` clause only.
- Building the Pro Python Toolbox (`.pyt`) and Notebook adapters now — they are
  *designed for* but not implemented in this pass.
- A full suite-wide framework (shared plugin/config/logging system). Build only the
  minimal scaffolding the harvester needs; revisit when a second tool exists.
- OAuth 2.0 / SSO interactive auth. Stored profile + username/password only.
- Live-AGOL automated testing with baked-in credentials.

## Architecture

**Core-plus-adapters.** All harvest logic lives in a runtime-agnostic core that
receives an already-connected `GIS` object; thin adapters produce that connection and
collect parameters per environment.

```
autogis/
  core/
    gis_session.py      # auth helpers: build a connected GIS from a profile or user/pass
    harvester.py        # query layer -> enumerate attachments -> download -> organize
    templates.py        # render {Attribute} folder/filename templates from feature attrs
    manifest.py         # accumulate per-attachment records; write CSV + JSON
    models.py           # dataclasses: HarvestConfig, AttachmentResult, RunSummary
  adapters/
    cli.py              # CLI -> build GIS, load config, call core.harvester
    # pro_toolbox.pyt and notebook adapter: planned, not built this pass
  config/
    inspection-job.example.yaml
tests/
```

**Contract:** the core never imports `arcpy` and never assumes how it was invoked. It
takes a connected `GIS` plus a `HarvestConfig`. Each adapter is responsible only for
producing the `GIS` (CLI: profile / env vars; Pro: `GIS("pro")`; Notebook: `GIS("home")`)
and a `HarvestConfig`, then calling the core.

**Delivery for this pass:** core (fully tested) + CLI adapter. Pro toolbox and Notebook
adapters are deliberately deferred but the core is designed so each is a thin add-on.

**Dependencies:** `arcgis` (ArcGIS API for Python), `PyYAML`, `click` (or argparse),
Python 3.x.

## Data Flow (one harvest run)

1. **Adapter (CLI)** loads the YAML config, applies CLI overrides, and builds a
   connected `GIS`:
   - Try the named **profile** (primary). If absent, fall back to
     **username/password from env vars** (`AGOL_USER` / `AGOL_PASS`). If neither
     works, fail with a clear message.
2. **Resolve the layer** from item ID or layer URL to a `FeatureLayer`. Verify
   attachments are enabled; error clearly if not.
3. **Query features** with the optional `where` clause (default `1=1`). If
   `--incremental` is set, AND in `EditDate > last_run_time`, read from / written to a
   small state file next to the output. Error clearly if the layer has no editor tracking.
4. **For each feature**, list its attachments (id, name, size, content type).
5. **For each attachment**, compute the target path:
   - group folder = render `group_template` against the feature's attributes (e.g. `{Status}`)
   - filename = render `filename_template` (e.g. `{InspectionID}_{OBJECTID}_{name}`)
   - sanitize for the filesystem (strip illegal chars, collapse spaces).
6. **Skip-existing check** — if the target file already exists, record `skipped`, continue.
7. **Download** with retry + backoff. On permanent failure: record `failed`, continue.
8. **Record** every attachment's outcome into the manifest accumulator.
9. **After all features:** write `manifest.csv` + `manifest.json`, update the incremental
   state file (only if the run completed), and print a summary:
   *N downloaded, N skipped, N failed*.

### Deliberate details

- **Template placeholders** reference feature attributes. If a referenced field is
  missing/null, substitute a safe token (e.g. `_unknown`) rather than crash, and note it.
- **Idempotency** comes from skip-existing plus the manifest's `failed` rows giving a
  clean re-run path (a re-run only retries skipped/failed items).
- **Filename templates** must carry a feature-level identifier (e.g. `OBJECTID`) because
  attribute-grouping places many features in one folder; this prevents collisions.

## Configuration

A reusable "harvest job" file (`inspection-job.yaml`); any field overridable via a CLI flag.
Secrets never live in the file or on the command line — only the profile name or env vars.

```yaml
connection:
  profile: my_agol_profile        # primary; env vars AGOL_USER/AGOL_PASS are the fallback
layer:
  item_id: "abcd1234..."          # or: url: "https://services.../FeatureServer/0"
  where: "Status = 'Complete'"    # optional; default 1=1
output:
  directory: "./harvest"
  group_template: "{Status}"
  filename_template: "{InspectionID}_{OBJECTID}_{name}"
options:
  incremental: false
  skip_existing: true
  retries: 3
  backoff_seconds: 2
```

## Error Handling

- **Setup errors** (bad auth, layer not found, attachments not enabled, no editor
  tracking when `--incremental`) → fail fast with a clear, actionable message *before*
  any download starts.
- **Per-attachment errors** → retry with backoff (`retries`, `backoff_seconds`), then
  record as `failed` and continue. One bad photo never kills the run. Final summary
  reports succeeded / skipped / failed counts.

## Testing

- **Unit tests (no network)** for the pure pieces: template rendering (including
  missing/null fields and illegal-char sanitization), path computation, skip-existing
  logic, manifest accumulation/serialization (CSV + JSON), config loading + override merge.
  The `arcgis` / `GIS` layer is mocked.
- **One integration-style test** with a mocked `FeatureLayer` exercising the full harvest
  loop (features → attachments → download → manifest) against fake responses, asserting
  the resilience path: a forced download failure still completes the run and is recorded
  as `failed` in the manifest.
- Real-AGOL testing stays manual/optional; no live credentials in the suite.

## Future Extensions (out of scope now)

- Pro Python Toolbox (`.pyt`) adapter and hosted Notebook adapter over the same core.
- Spatial filtering.
- Additional suite tools sharing the core/adapter scaffolding.
