# ADR-0044: SyncAGOLFeatureLayerToGDB (6.2) — attribute-only sync; attachments stay with the harvester

**Status:** Accepted

**Date:** 2026-07-03

## Context

Roadmap tool 6.2 (`SyncAGOLFeatureLayerToGDB`) downloads hosted-feature-layer
edits into the local FGDB — field-collected well status, sample status, access
constraints, photo attachments, staff comments. It was the last "Not started"
roadmap item outside the two phase-gated groups (§11 AI, Phase 5
geostatistical) and had no spec.

Two prior decisions constrain the shape:

- **ADR-0039:** generation-2 LOCAL tools are CLI-first (lazy arcpy in the CLI
  command, no `.pyt` entry unless interactive map context is needed).
- The repo already ships a complete **attachments** pipeline: the Attachment
  Harvester (`core/harvest/`, `autogis harvest`) downloads attachments with
  retry/backoff, a manifest, and incremental `EditDate` state; Tool 6.5
  (`envmon index-field-attachments`) indexes that manifest into the
  `AttachmentIndex` table. 6.5's docstring already records the split: "The
  AGOL download half already ships as the attachment harvester."

Design spec: `docs/superpowers/specs/2026-07-03-sync-agol-feature-layer-to-gdb-design.md`.

## Decision

**6.2 is an attribute/status sync only — attachments are explicitly out of
scope.** The photo-attachments use case named in the roadmap is served by the
existing pipeline (`autogis harvest` → manifest →
`envmon index-field-attachments`), not by new download code in 6.2.

**Shape: one HYBRID CLI command, `agol sync-to-gdb`,** on the
`survey-to-well-elevation` mutually-exclusive-flags pattern:

- CLOUD fetch for both paths: `core/agol/sync_layer.py::fetch_layer_edits()`,
  the injected-`gis` lazy-`arcgis` seam (`audit_schema.fetch_layer_schema`
  precedent), attributes only (`return_geometry=False`). `--since` becomes an
  `EditDate > <epoch ms>` clause (the harvester's incremental convention).
- `--out-csv`: headless dump of the fetched edit records.
- `--gdb --table`: `_guard`-gated upsert keyed on `--key-field` (default
  `GlobalID`) — pure `plan_sync()` splits updates/inserts, arcpy-touching
  `write_sync_to_gdb()` is a `# pragma: no cover` seam using function-scope
  `arcpy_env` (ADR-0040). Registered `Runtime.LOCAL` in `capabilities.TOOLS`
  (drives the guard; the headless path never guards), no `_REGISTRY_SEED`
  entry (agol-group commands are outside `envmon list-tools`, same as
  6.3/6.4/6.6/6.8–6.11).

**Also scoped out, documented in the spec:** geometry (authoritative locally;
fetched `return_geometry=False`) and AGOL-side deletes (destructive local
deletes from a field-editable layer are a data-loss hazard; detecting them
needs a full-key-set diff, not an edits fetch).

## Consequences

### Positive consequences

- No second attachment downloader: one download authority (harvester), one
  index (6.5), and 6.2 stays a small attribute-sync tool.
- The pure planner (`plan_sync`) and where-clause builder are fully
  unit-tested without arcgis/arcpy; the two seams follow the repo's
  established `# pragma: no cover` pattern.
- Closes the roadmap's last non-phase-gated "Not started" item; §6 is now
  fully implemented (6.1–6.11).

### Negative consequences

- A user wanting attributes *and* photos runs two commands (`agol
  sync-to-gdb` + `autogis harvest`). Accepted: the alternative is duplicated
  orchestration and state.
- No delete propagation means locally-orphaned rows accumulate if crews
  delete hosted features. Accepted as the safe default; a `--report`-visible
  delete *detector* (not deleter) is a possible future enhancement.
- Upserts keyed on a GDB-managed GlobalID column cannot set the key on
  inserts (GDB generates it), which would orphan those rows for future syncs.
  Documented on `write_sync_to_gdb`; use a plain text key column in that case.

## Alternatives considered

1. **6.2 calls into the harvester's `download_one()` for the attachments use
   case:** rejected — it would re-orchestrate the harvester's manifest,
   incremental state, and retry configuration behind a second CLI surface,
   creating two attachment authorities (the duplicate-tool class the
   2026-06-28 fold-decision doc exists to prevent) for a need harvest + 6.5
   already meet end-to-end.
2. **`.pyt`-primary with CLI guard-and-redirect** (ADR-0006 pattern):
   rejected — superseded by ADR-0039 for generation-2 tools; nothing in 6.2
   needs interactive map context.
3. **`envmon` CLI group:** rejected — every §6 tool that talks to AGOL
   directly lives under `agol`; 6.2 follows.
4. **Harvester-style last-run state file for incremental sync:** rejected —
   the upsert is idempotent and `--since` gives incremental behavior with no
   state to corrupt; the harvester's state is keyed to a download directory,
   which this tool doesn't have.

## Related decisions

- [ADR-0039: Generation-2 LOCAL tools are CLI-first](0039-cli-first-generation-2-local-tools.md)
- [ADR-0040: Canonical arcpy-access style](0040-canonical-arcpy-access-style.md)
- [ADR-0033: CreateBoringLogDatabase + SyncFieldAttachments](0033-boring-log-db-and-attachment-index.md)
  — established the harvester-owns-downloads / envmon-owns-index split this
  ADR extends to 6.2.
- `docs/superpowers/specs/2026-07-03-sync-agol-feature-layer-to-gdb-design.md`
  — the full design.
- `docs/superpowers/specs/2026-06-28-roadmap-duplicate-tools-fold-decision.md`
  — the duplicate-tool discipline applied here.
