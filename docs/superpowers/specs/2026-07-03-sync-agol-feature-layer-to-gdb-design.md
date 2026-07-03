# SyncAGOLFeatureLayerToGDB Design

**Date:** 2026-07-03
**Status:** Approved — implemented in the same session (ADR-0044)
**Tool:** SyncAGOLFeatureLayerToGDB (Tool 6.2)
**Priority:** MEDIUM — the last "Not started" roadmap item outside the two phase-gated groups
**Runtime:** HYBRID — CLOUD fetch (`arcgis` REST) + LOCAL write (`--gdb`, arcpy-guarded), CLI-first per ADR-0039

---

## Problem

Field crews edit hosted feature layers in AGOL (Field Maps / Survey123): well
status, sample-collection status, access constraints, staff comments. Those
edits live only in the hosted layer; the local FGDB that the reporting and
cartography tools read stays stale until someone manually exports. Roadmap
§6.2 asks for a tool that downloads hosted-feature-layer edits into the local
FGDB.

Roadmap use cases: field-collected well status, sample collection status,
access constraints, photo attachments, staff comments.

---

## Scope decision — attachments are OUT; the harvester already owns them

Roadmap 6.2 lists "photo attachments" as a use case, but the repo already
ships a complete attachments pipeline:

- **`autogis harvest`** (`core/harvest/`): resolves the layer, queries
  features, downloads every attachment with retry/backoff, writes a CSV/JSON
  manifest, and supports incremental runs via `EditDate` + last-run state.
- **`envmon index-field-attachments`** (Tool 6.5): indexes that manifest into
  the `AttachmentIndex` table. Its module docstring already codifies the
  split: *"The AGOL download half already ships as the attachment
  harvester... This tool is purely the envmon-side half."*

**Decision: 6.2 is attribute/status sync only.** Photo attachments remain the
harvester's job: `autogis harvest` → manifest → `envmon
index-field-attachments`.

**Rejected — 6.2 calls into the harvester's download logic for attachments.**
That would create a second orchestration of the same download path — a second
manifest, a second incremental state, a second retry configuration — behind a
different CLI surface, while `HarvestConfig`'s path templating and
skip-existing logic would be either left behind or duplicated. The user need
("get field photos locally, joinable to records") is already met end-to-end
by harvest + 6.5. Two attachment authorities is exactly the duplicate-tool
class the 2026-06-28 fold-decision doc
(`2026-06-28-roadmap-duplicate-tools-fold-decision.md`) exists to prevent.

Also out of scope (documented, not silently dropped):

- **Geometry.** Features are queried `return_geometry=False`. The roadmap use
  cases are all attribute edits to features whose authoritative geometry is
  local (wells are placed by RTK survey, not by crews dragging points in
  Field Maps). A geometry-sync need, if it ever materializes, is a different
  tool.
- **Deletes.** Rows deleted in AGOL are not deleted locally. Detecting
  deletes requires diffing the full remote key set against local (not
  "edits"), and destructive local deletes driven by a field-editable layer
  are a data-loss hazard this tool should not quietly perform.

---

## Approach

One CLI command, HYBRID, mutually-exclusive output flags — the established
`survey-to-well-elevation` shape (generation-2, CLI-first per ADR-0039; no
`.pyt` entry, nothing here needs interactive map context):

- **CLOUD fetch (both paths):** `fetch_layer_edits(gis, ...)` — the lazy
  `arcgis` seam, mirroring `audit_schema.fetch_layer_schema()`: `gis` is
  injected (built by `cli.agol_from_profile`), the layer is resolved by
  `--layer-url` or `--item-id`/`--layer-index`, features are queried
  attributes-only. `--since YYYY-MM-DD` becomes an `EditDate > <epoch ms>`
  clause — the same epoch-ms convention the harvester's incremental mode uses
  (requires editor tracking on the hosted layer).
- **Headless half (`--out-csv`):** dump the fetched records to CSV. No arcpy,
  no planning — the deliverable is the downloaded edits themselves.
- **LOCAL half (`--gdb` + `--table`):** `_guard`-gated. Read existing key
  values from the target table (SearchCursor, the way
  `survey-to-well-elevation` reads well IDs inline), split records into
  updates/inserts with the pure `plan_sync()`, print the plan, then (unless
  `--dry-run`) upsert via `write_sync_to_gdb()` — UpdateCursor/InsertCursor
  keyed on `--key-field` (default `GlobalID`).

**Rejected — a last-run state file for incremental sync** (harvester-style
`read_last_run`/`write_last_run`): the harvester's state is keyed to a
download *directory*; this tool's target is a GDB table, and the upsert is
idempotent — re-fetching an overlapping window is harmless. `--since` gives
incremental behavior with zero state to corrupt. Add state only if run volume
ever makes windowed fetches too slow.

**Rejected — `envmon` CLI group.** Every §6 tool that talks to AGOL directly
(6.3, 6.4, 6.6, 6.8, 6.9, 6.10, 6.11) lives under `agol`; 6.2 does too:
`agol sync-to-gdb`.

**Rejected — `.pyt`-primary with CLI guard-and-redirect** (the pre-ADR-0039
pattern the 2026-06-28 spec batch used): superseded — generation-2 LOCAL
halves execute directly in the CLI via lazy arcpy.

---

## Architecture

```
autogis/
  core/agol/
    sync_layer.py            ← NEW: edits_where_clause() + plan_sync() (pure),
                                fetch_layer_edits() + write_sync_to_gdb() (seams)
  adapters/
    cli.py                   ← add `agol sync-to-gdb` (HYBRID; --gdb path guarded)
  runtime/
    capabilities.py          ← register "sync-to-gdb" (LOCAL, drives _guard)
tests/
  test_agol_sync_layer.py    ← NEW: pure-core + CLI tests (no arcgis/arcpy)
```

`Runtime.LOCAL` registration follows `survey-to-well-elevation` precedent:
the tool is HYBRID, but TOOLS/LOCAL is what makes `_guard()` fire on the
`--gdb` path; the headless path never calls `_guard`. No `_REGISTRY_SEED`
entry — `agol`-group commands are not part of `envmon list-tools` discovery
(same as 6.3/6.4/6.6/6.8–6.11).

---

## Public API

Arcpy-free core (`core/agol/sync_layer.py`):

```python
@dataclass
class SyncPlan:
    key_field: str
    updates: dict[str, dict]   # key value → attribute record (row exists locally)
    inserts: list[dict]        # records with no local match
    skipped_no_key: int        # records missing the key field (QA WARNING each)
    field_names: list[str]     # key_field first, then sorted attribute names

def edits_where_clause(where: str | None, since: date | None) -> str:
    """Combine a user where-clause with an `EditDate > <epoch ms>` cutoff."""

def plan_sync(records, existing_keys, *, key_field="GlobalID",
              fields=None, qa=None) -> SyncPlan:
    """Pure. Drops system fields (OBJECTID, SHAPE, Shape__*) unless `fields`
    names them explicitly; records missing the key → skipped + QA WARNING;
    key in existing_keys → update, else insert."""

def fetch_layer_edits(gis, *, layer_url=None, item_id=None, layer_index=0,
                      where="1=1") -> list[dict]:   # pragma: no cover
    """Lazy arcgis.features.FeatureLayer seam; attributes only
    (return_geometry=False)."""

def write_sync_to_gdb(gdb_path, table, plan) -> tuple[int, int]:  # pragma: no cover
    """Function-scope arcpy_env (ADR-0040). Writes only fields that exist on
    the target table; never overwrites the key column on updates. Returns
    (updated, inserted)."""
```

Caveat documented on `write_sync_to_gdb`: if the target's key column is a
GDB-*managed* GlobalID field, inserts cannot set it (the GDB generates it),
which would orphan future syncs — use a plain text key column (e.g.
`SourceGlobalID`) in that case.

---

## CLI Command

```
autogis agol sync-to-gdb
    (--layer-url URL | --item-id ID [--layer-index N])
    [--profile P] [--where SQL] [--since YYYY-MM-DD]
    [--key-field GlobalID] [--fields F1,F2,...]
    --out-csv PATH                 # headless: dump fetched edit records
  | --gdb PATH --table NAME        # LOCAL: guarded upsert into the GDB
    [--dry-run]                    # with --gdb: print the plan, write nothing
    [--report PATH] [--fail-on error|warning]
```

`--out-csv` and `--gdb` are mutually exclusive; one is required. `--gdb`
requires `--table`. The guard fires before any AGOL session is built, so a
headless `--gdb` invocation fails with the clean arcpy message, not an
arcgis import error.

---

## Test Strategy

Arcpy-free, no arcgis (`tests/test_agol_sync_layer.py`):

1. `edits_where_clause`: default `1=1`, where passthrough, since-only, both
   combined (`(where) AND EditDate > ms`).
2. `plan_sync`: update/insert split against existing keys; missing-key record
   → `skipped_no_key` + QA WARNING; system fields (OBJECTID, Shape__*)
   excluded by default; `fields` filter keeps only key + named fields;
   `field_names` ordering (key first, rest sorted).
3. CLI: `agol --help` lists `sync-to-gdb`; `--out-csv`/`--gdb` mutual
   exclusion; neither-flag error; `--gdb` without `--table` error; missing
   `--layer-url`/`--item-id` error; `--gdb` headless → clean arcpy guard
   message; `--out-csv` happy path with `agol_from_profile` +
   `fetch_layer_edits` monkeypatched → CSV written with system fields
   dropped; `--since` reaches the fetch seam as an `EditDate >` clause.
4. `fetch_layer_edits` / `write_sync_to_gdb` are `# pragma: no cover` seams
   (the `audit_schema.fetch_layer_schema` / `write_rtk_elevations_to_wells`
   precedent) — never called in headless tests.
