"""export_snapshot.py — freeze a GDB snapshot for a reporting event.

Pure-Python layer (SnapshotManifest, format_manifest, build_where) is arcpy-free.
export_event_snapshot() requires arcpy — # pragma: no cover.
"""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows-illegal filename characters plus control chars; site_id/event_id
# get interpolated straight into a GDB folder name (issue #219).
_ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_snapshot_id(value: str, label: str) -> None:
    """Raise ValueError if ``value`` cannot be used as part of a filename.

    Applies to ``site_id``/``event_id`` before they are interpolated into
    the output GDB folder name -- catches illegal characters early with a
    clear message instead of letting CreateFileGDB fail as an opaque
    ERROR 999999.
    """
    if not value or not value.strip():
        raise ValueError(f"{label} must not be empty")
    if value != value.strip():
        raise ValueError(f"{label} {value!r} has leading/trailing whitespace")
    m = _ILLEGAL_NAME_CHARS.search(value)
    if m:
        raise ValueError(
            f"{label} {value!r} contains a character not allowed in a "
            f"filename: {m.group()!r}")


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
    compressed_path: Optional[str] = None


def format_manifest(manifest: SnapshotManifest) -> str:
    lines = [
        f"EventDatabaseSnapshot  {manifest.site_id} / {manifest.event_id}",
        f"Exported: {manifest.exported_at}  Schema: v{manifest.schema_version}",
        f"Source: {manifest.source_gdb}",
        f"Output: {manifest.output_path}",
    ]
    if manifest.compressed_path:
        lines.append(f"Compressed: {manifest.compressed_path}")
    lines += [
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


def _escape_sql_literal(value: str) -> str:
    """Escape a value for embedding in a single-quoted SQL string literal by
    doubling embedded single quotes (issue #366 -- site_id/event_id are
    config-sourced, not remote-untrusted, but an unescaped quote still
    produces a malformed or attacker-shaped predicate)."""
    return value.replace("'", "''")


def compress_snapshot_gdb(out_gdb: str) -> str:
    """ZIP a file GDB directory into a sibling ``<out_gdb>.zip``. Arcpy-free
    (a file GDB is an ordinary directory on disk) -- returns the archive path.
    """
    gdb_path = Path(out_gdb)
    return shutil.make_archive(str(gdb_path), "zip",
                               root_dir=str(gdb_path.parent), base_dir=gdb_path.name)


def build_where(
    site_id: str,
    event_id: str,
    has_site: bool,
    has_event: bool,
) -> Optional[str]:
    """Build WHERE clause for a site/event filter. Returns None for lookup tables."""
    parts = []
    if has_site:
        parts.append(f"SiteID = '{_escape_sql_literal(site_id)}'")
    if has_event:
        parts.append(f"EventID = '{_escape_sql_literal(event_id)}'")
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
    from .gdb_schema import TABLE_SCHEMAS, FEATURE_SCHEMAS
    from .upgrade_schema import SCHEMA_VERSION

    validate_snapshot_id(site_id, "site_id")
    validate_snapshot_id(event_id, "event_id")

    gdb = str(gdb_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    out_name = f"{site_id}_{event_id}_snapshot_{ts}.gdb"
    out_gdb = str(out / out_name)
    if Path(out_gdb).exists():
        raise FileExistsError(
            f"Snapshot target already exists: {out_gdb} "
            "-- delete it or export to a different --out folder")

    arcpy.management.CreateFileGDB(str(out), out_name)

    schema_ver = SCHEMA_VERSION
    vsn_path = str(Path(gdb) / "Env_SchemaVersion")
    if arcpy.Exists(vsn_path):
        with arcpy.da.SearchCursor(vsn_path, ["SchemaVersion"],
                                   sql_clause=(None, "ORDER BY OBJECTID DESC")) as cur:
            for row in cur:
                schema_ver = row[0] or SCHEMA_VERSION
                break

    copied, skipped, fc_copied = [], [], []
    row_counts: dict[str, int] = {}

    for tbl_name in TABLE_SCHEMAS:
        src = str(Path(gdb) / tbl_name)
        if not arcpy.Exists(src):
            skipped.append(tbl_name)
            continue
        fields = [f.name for f in arcpy.ListFields(src)]
        has_site = "SiteID" in fields
        has_event = "EventID" in fields
        where = build_where(site_id, event_id, has_site, has_event)
        dst = str(Path(out_gdb) / tbl_name)
        if where:
            arcpy.conversion.ExportTable(src, dst, where)
        else:
            arcpy.management.Copy(src, dst)
        copied.append(tbl_name)
        row_counts[tbl_name] = int(arcpy.management.GetCount(dst).getOutput(0))

    for fc_name in FEATURE_SCHEMAS:
        src = str(Path(gdb) / fc_name)
        if not arcpy.Exists(src):
            continue
        fields = [f.name for f in arcpy.ListFields(src)]
        has_site = "SiteID" in fields
        where = build_where(site_id, "", has_site, False)
        dst = str(Path(out_gdb) / fc_name)
        if where:
            arcpy.conversion.ExportFeatures(src, dst, where)
        else:
            arcpy.management.Copy(src, dst)
        fc_copied.append(fc_name)
        row_counts[fc_name] = int(arcpy.management.GetCount(dst).getOutput(0))

    # Issue #342: --compress was accepted and documented ("ZIP the output
    # GDB") but silently did nothing. Archive as a sibling .zip rather than
    # deleting the GDB out from under a caller that might still hold it open.
    compressed_path = compress_snapshot_gdb(out_gdb) if compress else None

    manifest = SnapshotManifest(
        site_id=site_id, event_id=event_id,
        exported_at=datetime.now().isoformat(timespec="seconds"),
        schema_version=schema_ver,
        source_gdb=str(gdb_path),
        output_path=str(out / out_name),
        tables_copied=copied, tables_skipped=skipped,
        feature_classes_copied=fc_copied,
        row_counts=row_counts,
        compressed_path=compressed_path,
    )
    # Named after the GDB, not a bare "manifest.json": the manifest lands in
    # the shared --out folder, so a fixed name is clobbered by the next export
    # into that folder -- including one on a different day, which the
    # FileExistsError guard above never sees because it only checks the GDB.
    manifest_path = out / f"{out_name}.manifest.json"
    manifest_path.write_text(json.dumps(dataclasses.asdict(manifest), indent=2),
                             encoding="utf-8")
    return manifest
