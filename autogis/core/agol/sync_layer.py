"""SyncAGOLFeatureLayerToGDB — attribute-edit sync core (Tool 6.2).

``edits_where_clause()`` and ``plan_sync()`` are arcpy-free and importable
without arcgis installed.  ``fetch_layer_edits()`` lazy-imports
``arcgis.features.FeatureLayer`` and ``write_sync_to_gdb()`` reaches arcpy
through the function-scope ``arcpy_env`` seam (ADR-0040) — both are
``# pragma: no cover`` seams between the headless core and the live stacks.

Scope (ADR-0044 / the 2026-07-03 design spec): this tool syncs *attribute*
edits only.  Photo attachments stay with the shipped harvester pipeline
(``autogis harvest`` → manifest → ``envmon index-field-attachments``),
geometry is not synced (features are queried ``return_geometry=False``), and
AGOL-side deletes are not propagated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Dict, Iterable, List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ._sublayers import resolve_sublayer

_SYSTEM_FIELD_NAMES = {"OBJECTID", "SHAPE"}


def _is_system_field(name: str) -> bool:
    """OBJECTID / SHAPE / Shape__* — local-meaningless AGOL system fields."""
    return name.upper() in _SYSTEM_FIELD_NAMES or name.startswith("Shape__")


def edits_where_clause(where: Optional[str] = None,
                       since: Optional[date] = None,
                       *, edit_field: str = "EditDate") -> str:
    """Combine a user where-clause with an edit-date cutoff.

    ``since`` (a date, midnight UTC) becomes ``<edit_field> > <epoch ms>`` —
    the same epoch-ms convention the attachment harvester's incremental mode
    uses.  ``edit_field`` defaults to ``EditDate`` (the AGOL hosted default);
    callers with a layer whose ``editFieldsInfo.editDateField`` differs pass
    it explicitly (Tool 7.5 does).  The hosted layer needs editor tracking
    for the field to exist.
    """
    base = where or "1=1"
    if since is None:
        return base
    ms = int(datetime.combine(since, time(), tzinfo=timezone.utc)
             .timestamp() * 1000)
    clause = f"{edit_field} > {ms}"
    return clause if base == "1=1" else f"({base}) AND {clause}"


@dataclass
class SyncPlan:
    """Headless output of plan_sync().

    updates:        key value → attribute record; a matching local row exists.
    inserts:        records with no local match (new field-collected rows).
    skipped_no_key: count of records missing the key field (QA WARNING each).
    field_names:    key_field first, then the sorted union of kept attribute
                    names — the CSV header / GDB write-field order.
    """
    key_field: str
    updates: Dict[str, dict]
    inserts: List[dict]
    skipped_no_key: int
    field_names: List[str]


def plan_sync(
    records: Iterable[dict],
    existing_keys: set,
    *,
    key_field: str = "GlobalID",
    fields: Optional[List[str]] = None,
    qa: Optional[QACollector] = None,
) -> SyncPlan:
    """Split fetched attribute records into updates/inserts (pure, arcpy-free).

    Records without a value in ``key_field`` cannot be matched to a local row
    and are skipped (QA WARNING each).  ``fields`` limits the synced
    attributes (the key field is always kept); by default every non-system
    field is kept and OBJECTID / SHAPE / Shape__* are dropped.
    """
    allowed = set(fields) if fields else None
    updates: Dict[str, dict] = {}
    inserts: List[dict] = []
    skipped = 0
    names: set = set()

    for rec in records:
        key = rec.get(key_field)
        if key in (None, ""):
            skipped += 1
            if qa is not None:
                qa.add(SEV_WARNING, "missing_key_field",
                       f"record without {key_field} skipped — cannot match "
                       f"to a local row")
            continue
        kept = {
            k: v for k, v in rec.items()
            if k == key_field
            or (allowed is not None and k in allowed)
            or (allowed is None and not _is_system_field(k))
        }
        names.update(kept)
        if str(key) in existing_keys:
            updates[str(key)] = kept
        else:
            inserts.append(kept)

    if qa is not None:
        qa.add(SEV_INFO, "sync_plan_complete",
               f"sync plan: {len(updates)} update(s), {len(inserts)} "
               f"insert(s), {skipped} skipped (no {key_field})")

    names.discard(key_field)
    return SyncPlan(key_field=key_field, updates=updates, inserts=inserts,
                    skipped_no_key=skipped,
                    field_names=[key_field] + sorted(names))


# -- AGOL fetch seam -----------------------------------------------------------

def fetch_layer_edits(  # pragma: no cover
    gis,
    *,
    layer_url: Optional[str] = None,
    item_id: Optional[str] = None,
    layer_index: int = 0,
    where: str = "1=1",
) -> List[dict]:
    """Fetch attribute records from a hosted feature layer via the arcgis SDK.

    Exactly one of ``layer_url`` or ``item_id`` must be provided.  Attributes
    only (``return_geometry=False``) — 6.2 is an attribute sync; attachments
    are the harvester's job (see module docstring).

    ``layer_index`` is AGOL's REST sublayer id, matched across the item's
    layers AND tables via ``resolve_sublayer`` (see ``_sublayers.py``) — not
    a positional index into ``item.layers``.

    Lazy: ``arcgis.features`` is imported only here — this module stays
    importable without the arcgis package installed.  Called by the CLI
    command; the live arcgis query is never exercised in headless tests
    (sublayer resolution itself is covered via fakes in ``_sublayers``).
    """
    from arcgis.features import FeatureLayer  # type: ignore[import]

    if item_id and not layer_url:
        item = gis.content.get(item_id)
        if item is None:
            raise ValueError(f"AGOL item {item_id!r} not found in this GIS")
        layer_url = resolve_sublayer(item, layer_index, item_id).url
    if not layer_url:
        raise ValueError("Provide layer_url or item_id")
    layer = FeatureLayer(layer_url, gis)
    result = layer.query(where=where, out_fields="*", return_geometry=False)
    return [dict(f.attributes) for f in result.features]


# -- GDB write seam ------------------------------------------------------------

def write_sync_to_gdb(  # pragma: no cover
    gdb_path,
    table: str,
    plan: SyncPlan,
) -> tuple:
    """Upsert a SyncPlan into a GDB table / feature class (ArcGIS Pro).

    Only fields that exist on the target table are written (a fetched field
    with no local column is silently skipped); the key column is matched on
    but never overwritten during updates.  Returns ``(updated, inserted)``.

    Caveat: if the target's key column is a GDB-*managed* GlobalID field,
    inserts cannot set it (the GDB generates its own value), which would
    orphan those rows for future syncs — use a plain text key column
    (e.g. ``SourceGlobalID``) in that case.
    """
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    target = str(_P(str(gdb_path)) / table)
    table_fields = {f.name for f in _ax.ListFields(target)}
    write_fields = [f for f in plan.field_names if f in table_fields]
    key = plan.key_field
    if key not in write_fields:
        raise ValueError(
            f"key field {key!r} not found on target table {target!r}")

    updated = inserted = 0
    if plan.updates:
        key_idx = write_fields.index(key)
        with _ax.da.UpdateCursor(target, write_fields) as cur:
            for row in cur:
                rec = plan.updates.get(str(row[key_idx]))
                if rec is None:
                    continue
                cur.updateRow([
                    row[i] if f == key else rec.get(f, row[i])
                    for i, f in enumerate(write_fields)
                ])
                updated += 1
    if plan.inserts:
        with _ax.da.InsertCursor(target, write_fields) as cur:
            for rec in plan.inserts:
                cur.insertRow([rec.get(f) for f in write_fields])
                inserted += 1
    return updated, inserted
