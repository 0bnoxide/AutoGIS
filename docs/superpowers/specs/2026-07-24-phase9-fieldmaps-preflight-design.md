# Phase 9 slice 1 — Field Maps sync preflight (Tool 7.5) design

Date: 2026-07-24 · ADR-0111 · Roadmap: `docs/production-roadmap.md:133-141`

## Shape

CLI-first (ADR-0039/0043; owner struck the notebook option 2026-07-24), no
`.pyt`, no GUI entry. One core module + one CLI command:

```
autogis agol fieldmaps-preflight --item-id <id> [--layer-index N]
    [--profile P] [--spec schema.yaml] [--local-csv snapshot.csv]
    [--manifest manifest.csv] [--since YYYY-MM-DD] [--key-field GlobalID]
    [--max-replica-age-days 7.0] [--format text|json] [--output path]
    [--fail-on-findings]
```

## Checks (roadmap scope → implementation)

| Roadmap item | Check | Inputs | Always run? |
|---|---|---|---|
| (prerequisites) | `check_sync_config` — syncEnabled, capabilities string, editor tracking, globalIdField, hasAttachments | service+layer props | yes |
| pending hosted edits | `check_pending_hosted_edits` — records under `edits_where_clause(..., edit_field=editFieldsInfo.editDateField)` | `--since` watermark | yes (INFO-only without `--since`) |
| replica / offline-area age | `check_replica_age` — lastSyncDate/creationDate (epoch ms) vs `--max-replica-age-days` | replicas via SDK | yes |
| schema drift | reuse `audit_schema.diff_schema` on already-fetched layer props | `--spec` | if `--spec` |
| duplicate identities | `check_duplicate_identities` — dup/blank `--key-field` values | fetched records | yes |
| potential conflicts | `check_conflict_candidates` — matched keys whose shared non-system fields differ (string-normalized) | `--local-csv` snapshot | if `--local-csv` |
| missing/stale attachments | `check_attachments` — `AttachmentManager.search()` vs usable downloaded/skipped harvester rows for the selected `source_table` (keyed objectid+attachment_id; stale = size differs) | `--manifest` | if `--manifest` and hasAttachments |

Checks not run render as `SKIPPED (input not provided)` — the report never
silently narrows (roadmap: "complete preflight report").

## Read-only guarantee

Seams (`fetch_service_state`, `fetch_replicas`, `fetch_attachments`, plus
reused `sync_layer.fetch_layer_edits`) issue only properties/query/list
reads. Nothing writes to either side; the #307 sandbox gate run verifies
that end-to-end.

## Slice boundaries (deferred)

- **Slice 2 — pending *local* edits from a Field Maps offline FGDB:** arcpy
  cursor read behind `_guard`, `sync-to-gdb` hybrid pattern. Only leg that
  needs arcpy.
- **Gate run** against the #307 non-prod sandbox (intentionally created
  conflicts; before/after no-change proof).
- Watermark inference from replica `lastSyncDate` (today: explicit `--since`).
- Multi-layer sweep (today: one `--layer-index` per invocation).

## Testing

`tests/test_fieldmaps_preflight.py` — 31 pure-check tests incl. an
ASCII-only formatter assertion (cp1252 console lesson, PR #296). Seams are
`# pragma: no cover` per repo convention; suite green 2456.
