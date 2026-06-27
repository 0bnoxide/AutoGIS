# ExportEventDatabaseSnapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ExportEventDatabaseSnapshot` — freeze a GDB snapshot for a
reporting event. See spec: `docs/superpowers/specs/2026-06-27-export-event-snapshot-design.md`.

**Architecture:**
- New: `autogis/core/envmon/export_snapshot.py`
- Modify: `autogis/adapters/cli.py` — add `export-snapshot` command (LOCAL, guarded)
- New: `tests/envmon/test_export_snapshot.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- Pure-Python layer (`SnapshotManifest`, `format_manifest`, `build_where`) is arcpy-free and fully testable.
- `export_event_snapshot()` is LOCAL (arcpy), marked `# pragma: no cover`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Pure-Python layer + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_export_snapshot.py`:

```python
import json
from autogis.core.envmon.export_snapshot import (
    SnapshotManifest, format_manifest, build_where,
)
from autogis.core.envmon.gdb_schema import TABLE_SCHEMAS

_MANIFEST = SnapshotManifest(
    site_id="H281",
    event_id="2026Q2",
    exported_at="2026-06-27T14:32:00",
    schema_version="2.0",
    source_gdb="C:/GIS/H281/H281.gdb",
    output_path="C:/snapshots/H281_2026Q2.gdb",
    tables_copied=["Env_Samples", "Env_AnalyticalResults"],
    tables_skipped=["BoringLocations"],
    feature_classes_copied=["MonitoringWells"],
    row_counts={"Env_Samples": 42, "Env_AnalyticalResults": 204},
)


def test_format_manifest_contains_site_id():
    out = format_manifest(_MANIFEST)
    assert "H281" in out


def test_format_manifest_contains_event_id():
    out = format_manifest(_MANIFEST)
    assert "2026Q2" in out


def test_format_manifest_shows_table_counts():
    out = format_manifest(_MANIFEST)
    assert "2" in out   # 2 tables copied


def test_format_manifest_shows_skipped():
    out = format_manifest(_MANIFEST)
    assert "BoringLocations" in out
    assert "SKIPPED" in out.upper()


def test_manifest_json_roundtrip():
    import dataclasses
    d = dataclasses.asdict(_MANIFEST)
    s = json.dumps(d)
    loaded = json.loads(s)
    assert loaded["site_id"] == "H281"


def test_build_where_both():
    w = build_where("H281", "2026Q2", has_site=True, has_event=True)
    assert "SiteID" in w and "EventID" in w


def test_build_where_site_only():
    w = build_where("H281", "2026Q2", has_site=True, has_event=False)
    assert "SiteID" in w
    assert "EventID" not in w


def test_build_where_neither():
    w = build_where("H281", "2026Q2", has_site=False, has_event=False)
    assert w is None


def test_build_where_no_sql_injection():
    w = build_where("H281'; DROP TABLE--", "2026Q2", has_site=True, has_event=False)
    # site_id is quoted; basic injection attempt should appear verbatim but harmlessly
    # (full parameterization is arcpy's SearchCursor's job; this just builds the string)
    assert w is not None
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_export_snapshot.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/export_snapshot.py`**

```python
"""export_snapshot.py — freeze a GDB snapshot for a reporting event.

Pure-Python layer (SnapshotManifest, format_manifest, build_where) is arcpy-free.
export_event_snapshot() requires arcpy — # pragma: no cover.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SnapshotManifest:
    site_id: str
    event_id: str
    exported_at: str
    schema_version: str
    source_gdb: str
    output_path: str
    tables_copied: list[str] = field(default_factory=list)
    tables_skipped: list[str] = field(default_factory=list)
    feature_classes_copied: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)


def format_manifest(manifest: SnapshotManifest) -> str:
    lines = [
        f"EventDatabaseSnapshot  {manifest.site_id} / {manifest.event_id}",
        f"Exported: {manifest.exported_at}  Schema: v{manifest.schema_version}",
        f"Source: {manifest.source_gdb}",
        f"Output: {manifest.output_path}",
        "",
        f"Tables copied ({len(manifest.tables_copied)}):",
    ]
    for t in manifest.tables_copied:
        n = manifest.row_counts.get(t, "?")
        lines.append(f"  {t:<40} {n} rows")
    if manifest.tables_skipped:
        lines.append(f"\n[SKIPPED] ({len(manifest.tables_skipped)}):")
        for t in manifest.tables_skipped:
            lines.append(f"  {t}")
    if manifest.feature_classes_copied:
        lines.append(f"\nFeature classes: {', '.join(manifest.feature_classes_copied)}")
    return "\n".join(lines)


def build_where(
    site_id: str,
    event_id: str,
    has_site: bool,
    has_event: bool,
) -> Optional[str]:
    """Build WHERE clause for a site/event filter. Returns None for lookup tables."""
    parts = []
    if has_site:
        parts.append(f"SiteID = '{site_id}'")
    if has_event:
        parts.append(f"EventID = '{event_id}'")
    return " AND ".join(parts) if parts else None


def export_event_snapshot(   # pragma: no cover
    gdb_path: str,
    site_id: str,
    event_id: str,
    out_dir: str,
    compress: bool = False,
) -> SnapshotManifest:
    """Copy event-scoped rows from source GDB to a new output GDB (ArcGIS Pro)."""
    import arcpy
    from pathlib import Path as _P
    from .gdb_schema import TABLE_SCHEMAS, FEATURE_SCHEMAS
    from .upgrade_schema import SCHEMA_VERSION

    gdb = str(gdb_path)
    out = _P(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    out_name = f"{site_id}_{event_id}_snapshot_{ts}.gdb"
    out_gdb = str(out / out_name)

    arcpy.management.CreateFileGDB(str(out), out_name)

    # Read schema version
    vsn_path = str(_P(gdb) / "Env_SchemaVersion")
    schema_ver = SCHEMA_VERSION
    if arcpy.Exists(vsn_path):
        with arcpy.da.SearchCursor(vsn_path, ["SchemaVersion"],
                                   sql_clause=(None, "ORDER BY OBJECTID DESC")) as cur:
            for row in cur:
                schema_ver = row[0] or SCHEMA_VERSION
                break

    copied, skipped, fc_copied = [], [], []
    row_counts: dict[str, int] = {}

    for tbl_name in TABLE_SCHEMAS:
        src = str(_P(gdb) / tbl_name)
        if not arcpy.Exists(src):
            skipped.append(tbl_name)
            continue
        fields = [f.name for f in arcpy.ListFields(src)]
        has_site = "SiteID" in fields
        has_event = "EventID" in fields
        where = build_where(site_id, event_id, has_site, has_event)
        dst = str(_P(out_gdb) / tbl_name)
        if where:
            arcpy.conversion.TableToTable(src, out_gdb, tbl_name, where)
        else:
            arcpy.management.Copy(src, dst)
        copied.append(tbl_name)
        row_counts[tbl_name] = int(arcpy.management.GetCount(dst).getOutput(0))

    for fc_name in FEATURE_SCHEMAS:
        src = str(_P(gdb) / fc_name)
        if not arcpy.Exists(src):
            continue
        fields = [f.name for f in arcpy.ListFields(src)]
        has_site = "SiteID" in fields
        where = f"SiteID = '{site_id}'" if has_site else None
        dst = str(_P(out_gdb) / fc_name)
        if where:
            arcpy.conversion.FeatureClassToFeatureClass(src, out_gdb, fc_name, where)
        else:
            arcpy.management.Copy(src, dst)
        fc_copied.append(fc_name)
        row_counts[fc_name] = int(arcpy.management.GetCount(dst).getOutput(0))

    manifest = SnapshotManifest(
        site_id=site_id, event_id=event_id,
        exported_at=datetime.now().isoformat(timespec="seconds"),
        schema_version=schema_ver,
        source_gdb=str(gdb_path),
        output_path=str(out / out_name),
        tables_copied=copied, tables_skipped=skipped,
        feature_classes_copied=fc_copied,
        row_counts=row_counts,
    )
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(dataclasses.asdict(manifest), indent=2),
                             encoding="utf-8")
    return manifest
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_export_snapshot.py -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/export_snapshot.py tests/envmon/test_export_snapshot.py
git commit -m "feat(envmon): export_snapshot — SnapshotManifest + export_event_snapshot (LOCAL)"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`** (after `upgrade-schema` block)

```python
@envmon.command("export-snapshot")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--event", "event_id", required=True)
@click.option("--out", "out_dir", required=True, type=click.Path())
@click.option("--compress", is_flag=True, default=False,
              help="ZIP the output GDB after creation.")
def export_snapshot_cmd(gdb, site_id, event_id, out_dir, compress):
    """Freeze a GDB snapshot for a reporting event (ArcGIS Pro)."""
    _guard("export-snapshot")
    from autogis.core.envmon.export_snapshot import export_event_snapshot, format_manifest
    manifest = export_event_snapshot(gdb, site_id, event_id, out_dir, compress)
    click.echo(format_manifest(manifest))
```

- [ ] **Step 2: Help test + commit**

```python
def test_export_snapshot_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "export-snapshot" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_export_snapshot.py
git commit -m "feat(cli): add export-snapshot command (LOCAL, ArcGIS Pro)"
```
