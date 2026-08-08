"""upgrade_schema.py — GDB schema upgrade orchestrator (Phase 1.4).

Pure-Python layer (dataclasses + format_report) is arcpy-free and fully
unit-tested. upgrade_gdb_schema() requires arcpy and is # pragma: no cover.
"""
from __future__ import annotations

import getpass
import time
from dataclasses import dataclass, field
from datetime import datetime

# 2.8 — Env_Samples gains COCNumber / SampledBy / SampleSource (#420).
SCHEMA_VERSION = "2.8"


@dataclass
class TableUpgradeStatus:
    table_name: str
    status: str        # "CREATED" | "UPDATED" | "OK"
    fields_added: int
    fields_widened: int = 0


@dataclass
class UpgradeReport:
    gdb_path: str
    previous_version: str
    new_version: str
    tables: list[TableUpgradeStatus] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def tables_created(self) -> int:
        return sum(1 for t in self.tables if t.status == "CREATED")

    @property
    def fields_added(self) -> int:
        return sum(t.fields_added for t in self.tables)

    @property
    def fields_widened(self) -> int:
        return sum(t.fields_widened for t in self.tables)


def format_report(report: UpgradeReport) -> str:
    lines = [
        f"UpgradeEnvMonitoringGDBSchema  v{report.previous_version} → v{report.new_version}",
        f"GDB: {report.gdb_path}",
        "",
    ]
    for t in report.tables:
        tag = f"[{t.status}]"
        bits = []
        if t.fields_added:
            bits.append(f"+{t.fields_added} fields")
        if t.fields_widened:
            bits.append(f"{t.fields_widened} widened")
        detail = f"({', '.join(bits)})" if bits else ""
        lines.append(f"  {tag:<11} {t.table_name:<36} {detail}".rstrip())

    updated = sum(1 for t in report.tables if t.status == "UPDATED")
    ok_count = sum(1 for t in report.tables if t.status == "OK")
    lines += [
        "",
        (f"Summary: {report.tables_created} created, "
         f"{updated} updated, {ok_count} OK  "
         f"| {report.fields_added} fields added, "
         f"{report.fields_widened} widened"),
        f"Elapsed: {report.elapsed_seconds:.1f} s",
    ]
    return "\n".join(lines)


def upgrade_gdb_schema(  # pragma: no cover
    gdb_path: str,
    spatial_reference: int = 4326,
) -> UpgradeReport:
    """Upgrade a file GDB to the current schema version.

    Calls create_or_update_gdb_schema() (additive-only) after snapshotting
    the current table/field state. Derives per-table status from the diff.
    Writes one row to Env_SchemaVersion.

    Requires arcpy (ArcGIS Pro).
    """
    import arcpy
    from pathlib import Path as _P
    from .gdb_schema import create_or_update_gdb_schema, TABLE_SCHEMAS, T

    t0 = time.monotonic()
    gdb = str(gdb_path)

    # --- read previous version -------------------------------------------
    prev_ver = "1.0"
    vsn_table = str(_P(gdb) / "Env_SchemaVersion")
    if arcpy.Exists(vsn_table):
        with arcpy.da.SearchCursor(
            vsn_table, ["SchemaVersion"],
            sql_clause=(None, "ORDER BY OBJECTID DESC")
        ) as cur:
            for row in cur:
                prev_ver = row[0] or "1.0"
                break

    # --- snapshot before -------------------------------------------------
    tables_before: set[str] = set()
    fields_before: dict[str, set[str]] = {}
    if arcpy.Exists(gdb):
        arcpy.env.workspace = gdb
        for tbl in (arcpy.ListTables() or []):
            tables_before.add(tbl)
            fields_before[tbl] = {
                f.name.upper() for f in arcpy.ListFields(str(_P(gdb) / tbl))
            }

    # --- run the existing upgrade function ------------------------------
    sr = arcpy.SpatialReference(spatial_reference)
    create_or_update_gdb_schema(gdb, spatial_reference=sr)

    # --- widen text fields whose schema length grew (ADR-0097) -----------
    # create_or_update_gdb_schema is additive-only: it never touches an
    # existing field, so a widened text column (e.g. ScreeningLevelSource
    # 64 -> 256) stays short on pre-existing GDBs and breaks inserts. On a
    # populated file GDB the only permitted AlterField change is a length
    # INCREASE (Esri "Alter Field": with data you can only increase length),
    # so raising to the schema length is always safe here — we never shrink.
    widened: dict[str, int] = {}
    for tbl_name, tbl_fields in TABLE_SCHEMAS.items():
        tpath = str(_P(gdb) / tbl_name)
        if not arcpy.Exists(tpath):
            continue
        actual = {f.name.upper(): f for f in arcpy.ListFields(tpath)}
        for fname, ftype, flen in tbl_fields:
            if ftype != T or not flen:
                continue
            af = actual.get(fname.upper())
            if af is not None and af.length and af.length < flen:
                arcpy.management.AlterField(tpath, af.name, field_length=flen)
                widened[tbl_name] = widened.get(tbl_name, 0) + 1

    # --- derive per-table status ----------------------------------------
    statuses: list[TableUpgradeStatus] = []
    for tbl_name in TABLE_SCHEMAS:
        if tbl_name not in tables_before:
            statuses.append(TableUpgradeStatus(
                tbl_name, "CREATED", len(TABLE_SCHEMAS[tbl_name])
            ))
        else:
            added = sum(
                1 for f in TABLE_SCHEMAS[tbl_name]
                if f[0].upper() not in fields_before.get(tbl_name, set())
            )
            w = widened.get(tbl_name, 0)
            statuses.append(TableUpgradeStatus(
                tbl_name, "UPDATED" if (added or w) else "OK", added, w
            ))

    # --- write version row -----------------------------------------------
    tables_created = sum(1 for s in statuses if s.status == "CREATED")
    total_fields = sum(s.fields_added for s in statuses)
    elapsed = time.monotonic() - t0

    with arcpy.da.InsertCursor(
        vsn_table,
        ["SchemaVersion", "UpgradedAt", "PreviousVersion",
         "TablesCreated", "FieldsAdded", "UpgradedBy", "Notes"]
    ) as cur:
        cur.insertRow([
            SCHEMA_VERSION,
            datetime.now(),
            prev_ver,
            tables_created,
            total_fields,
            getpass.getuser(),
            "upgrade_schema.py automated upgrade",
        ])

    return UpgradeReport(
        gdb_path=gdb,
        previous_version=prev_ver,
        new_version=SCHEMA_VERSION,
        tables=statuses,
        elapsed_seconds=elapsed,
    )
