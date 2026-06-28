# ExportEventDatabaseSnapshot Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** ExportEventDatabaseSnapshot (Phase 3.6 / Tool 9.0a)
**Priority:** HIGH (report reproducibility — retroactive GDB questions can't be answered without this)

---

## Problem

When a report is submitted, there is no frozen copy of the GDB state used to produce
it. Post-submission corrections (new data for a later event, retroactive unit fixes)
can silently change what the GDB would show for the submitted event period. Regulatory
and legal review sometimes requires answering "what did the database show on date X"
— currently impossible.

The tool must also satisfy a practical daily need: it produces the data package sent to
the report writer, ensuring the figures and tables are produced from the same snapshot
as the final maps.

---

## Approach

**Chosen:** LOCAL tool (arcpy) that copies tables and feature classes for a specific
site + event to a new output GDB, plus a headless path that exports CSVs. A JSON
manifest is always written alongside, recording what was captured, what was skipped
(tables missing from the GDB), schema version at snapshot time, and the checksums of
key files.

The snapshot is `[SITE_ID]_[EVENT_ID]_snapshot_[YYYYMMDD].gdb` (or `.zip` with
`--compress`). A companion `manifest.json` is written at the root of the output
directory.

**Rejected: Full GDB copy.** Copying the entire GDB (all sites, all events) produces
large, ambiguous artifacts. Per-site, per-event filtering produces smaller, labeled
snapshots that can be shared without leaking other site data.

**Rejected: ZIP-only output.** ArcGIS Pro can open `.gdb` directly; ZIP creates an
extra step. ZIP is an option, not the default.

---

## Architecture

```
autogis/
  core/envmon/
    export_snapshot.py   ← NEW
  adapters/
    cli.py               ← add export-snapshot command (guarded LOCAL)
tests/envmon/
  test_export_snapshot.py ← NEW, arcpy-free (manifest + format tests only)
```

---

## Public API (`export_snapshot.py`)

```python
@dataclass
class SnapshotManifest:
    site_id: str
    event_id: str
    exported_at: str         # ISO datetime
    schema_version: str      # from Env_SchemaVersion if present, else "unknown"
    source_gdb: str
    output_path: str
    tables_copied: list[str]
    tables_skipped: list[str]   # exist in TABLE_SCHEMAS but not in source GDB
    feature_classes_copied: list[str]
    row_counts: dict[str, int]  # table_name → row count in snapshot

def format_manifest(manifest: SnapshotManifest) -> str:
    """Human-readable report for CLI output."""

def export_event_snapshot(        # pragma: no cover — requires arcpy
    gdb_path: str,
    site_id: str,
    event_id: str,
    out_dir: str,
    compress: bool = False,
) -> SnapshotManifest:
    """
    Copy all site+event rows from source GDB tables to a new output GDB.

    Tables filtered by SiteID and EventID where those fields exist.
    Feature classes (MonitoringWells, SoilBorings, etc.) filtered by SiteID only.
    Tables without SiteID/EventID columns are copied in full (lookup tables:
    Env_SchemaVersion, Env_AnalyteDictionary, etc.).
    Writes manifest.json alongside the output GDB.
    """
```

---

## Snapshot Logic

```
for table_name in TABLE_SCHEMAS:
    path = source_gdb / table_name
    if not arcpy.Exists(path):
        manifest.tables_skipped.append(table_name)
        continue
    fields = [f.name for f in arcpy.ListFields(path)]
    has_site = "SiteID" in fields
    has_event = "EventID" in fields
    where = build_where(site_id, event_id, has_site, has_event)
    copy_rows(path, out_gdb / table_name, where)
    manifest.tables_copied.append(table_name)
    manifest.row_counts[table_name] = count_rows(out_gdb / table_name)

for fc_name in FEATURE_SCHEMAS:
    # same pattern, SiteID filter only
    ...

write manifest.json
```

`build_where(site_id, event_id, has_site, has_event) -> str`:
- both: `"SiteID = '{site_id}' AND EventID = '{event_id}'"`
- site only: `"SiteID = '{site_id}'"`
- neither: `None` (copy all rows — lookup table)

---

## Manifest JSON Structure

```json
{
  "site_id": "H281",
  "event_id": "2026Q2",
  "exported_at": "2026-06-27T14:32:00",
  "schema_version": "2.0",
  "source_gdb": "C:/GIS/H281/H281.gdb",
  "output_path": "C:/GIS/snapshots/H281_2026Q2_snapshot_20260627.gdb",
  "tables_copied": ["Env_Samples", "Env_AnalyticalResults", ...],
  "tables_skipped": ["BoringLocations"],
  "feature_classes_copied": ["MonitoringWells"],
  "row_counts": {"Env_Samples": 42, "Env_AnalyticalResults": 1204}
}
```

---

## CLI Command

```python
@envmon.command("export-snapshot")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--event", "event_id", required=True)
@click.option("--out", "out_dir", required=True, type=click.Path())
@click.option("--compress", is_flag=True, default=False)
def export_snapshot_cmd(gdb, site_id, event_id, out_dir, compress):
    """Freeze a GDB snapshot for a reporting event (ArcGIS Pro)."""
    _guard("export-snapshot")
    from autogis.core.envmon.export_snapshot import export_event_snapshot, format_manifest
    manifest = export_event_snapshot(gdb, site_id, event_id, out_dir, compress)
    click.echo(format_manifest(manifest))
```

---

## Test Strategy

`tests/envmon/test_export_snapshot.py` — arcpy-free (manifest and format functions only):

1. `format_manifest()` contains site_id, event_id, table counts
2. `format_manifest()` lists skipped tables with label `[SKIPPED]`
3. `SnapshotManifest` JSON round-trips via `json.dumps/loads`
4. `build_where()` returns correct SQL for all four combinations of has_site/has_event
5. `SnapshotManifest.tables_copied` + `tables_skipped` sum equals all TABLE_SCHEMAS keys
   (given a synthetic manifest that was built to cover everything)
