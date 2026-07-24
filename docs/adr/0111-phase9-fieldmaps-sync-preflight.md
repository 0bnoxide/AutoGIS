# ADR-0111: Phase 9 slice 1 — headless Field Maps sync preflight (Tool 7.5)

**Status:** Accepted

**Date:** 2026-07-24

## Context

Roadmap Phase 9 (`docs/production-roadmap.md:133-141`) wants a **read-only
report** covering pending local and hosted edits, replica/offline-area age,
schema drift, missing/stale attachments, duplicate identities, and potential
conflicts before synchronization — conflict *resolution* stays under human
control. Its production gate needs a non-production hosted service with
intentionally created conflicts; that service does not exist yet and is
owner-gated (issue #307). The 2026-07-23 autonomous session stopped here on
the belief there was "no headless slice" — conflating *arcpy-free/unit-testable*
(what "headless" means for every other `agol` tool) with *gate-provable
without a live service*.

Owner decisions (2026-07-24) shaping this slice:

- **Packaging: CLI-first per ADR-0039/0043; the Pro-notebook option was
  considered and struck.** No `.pyt` entry (no interactive map context), no
  notebook deliverable — the plain-Jupyter Phase 4 pattern (ADR-0105) remains
  available later if a review surface is wanted.
- **Sandbox prerequisite tracked as #307**, not blocking code work.

## Decision

Ship Phase 9 slice 1 fully headless, on the established `core/agol` seams:

- **`core/agol/fieldmaps_preflight.py`** — pure `check_*` functions
  (sync-config, pending hosted edits, replica age, duplicate identities,
  conflict candidates, attachment staleness, plus a `SchemaDriftReport`
  adapter reusing `audit_schema.diff_schema`) and three lazy-arcgis
  `# pragma: no cover` fetch seams (`fetch_service_state`, `fetch_replicas`,
  `fetch_attachments`). Every seam call is a read (properties/query/list) —
  the module enforces the gate's "without changing either side" by
  construction.
- **CLI `agol fieldmaps-preflight`** (Tool 7.5, CLOUD, `field` domain):
  text/JSON report, `--fail-on-findings` exit-1 (audit-schema precedent).
  The **local side is a CSV snapshot** (`--local-csv`, e.g. from
  `sync-to-gdb --out-csv`; `--manifest` = harvester manifest.csv for
  attachments) — "pending local edits" read live from a Field Maps offline
  FGDB is the *only* arcpy-bound leg and is **deferred to slice 2** (will
  follow `sync-to-gdb`'s guard-only-when-`--gdb` hybrid pattern).
- **Shared fix:** `sync_layer.edits_where_clause` gains a backward-compatible
  `edit_field` keyword (was hardcoded `EditDate`); the preflight resolves the
  real field from `editFieldsInfo.editDateField` with an `EditDate` fallback.
- **Gate status:** the slice is suite-verified with fakes; the production
  gate run happens against the #307 sandbox once it exists (same shipped-code
  / owner-gated-validation split as Phase 8's WQX validator leg, ADR-0109).

arcgis/REST surfaces doc-verified this session (ADR-0077 spirit; arcgis, not
arcpy): `flc.replicas.get_list()/.get(id)`, `AttachmentManager.search()`,
`FeatureLayerCollection.fromitem` —
<https://developers.arcgis.com/python/latest/api-reference/arcgis.features.managers.html>;
`syncEnabled`/`syncCapabilities`/`editorTrackingInfo`/`capabilities` —
<https://developers.arcgis.com/rest/services-reference/enterprise/feature-service/>;
replica `creationDate`/`lastSyncDate` (epoch ms) —
<https://developers.arcgis.com/rest/services-reference/enterprise/replica-info/>;
`globalIdField`/`hasAttachments` —
<https://developers.arcgis.com/rest/services-reference/enterprise/feature-layer/>.

## Alternatives considered

- **Pro notebook surface** — struck by owner decision; plain Jupyter gets
  most benefits via the Phase 4 pattern and this repo's precedent for
  read-only report tools is CLI-first.
- **`.pyt` toolbox tool** — rejected: no interactive-map need (ADR-0039), ~5
  hand-enumerated registration surfaces, ADR-0077 parameter doc-burden,
  invisible to the GUI, inherits open #231 run-history QA debt.
- **Headless FGDB reader (GDAL/pyogrio) for the local leg** — rejected: a
  heavy new dependency to avoid an already-established guarded-arcpy seam.

## Consequences

- Phase 9 has shipped, tested preflight logic before the sandbox exists;
  the gate run (#307) exercises seams, not logic.
- Conflict detection is a naive string-compare on CSV snapshots (marked
  `ponytail:` in code) — type-coercion false positives are possible and will
  be tightened at the live gate if observed.
- Attachment-search key casing varies across service versions; the seams use
  tolerant lookups that the #307 gate run must confirm.
- Slice 2 (arcpy FGDB pending-local-edits leg) and the gate run remain open
  Phase 9 work; Phase 10 still gates behind the Phase 9 exit.
