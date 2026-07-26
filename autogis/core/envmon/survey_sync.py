"""survey_sync.py — Survey123 Phase 2: incremental submission synchronization.

Home of the **canonical submission envelope** (relocated here from Phase 0 by
ADR-0113 — this puller is its first real consumer) plus the pure sync
planning, checkpoint I/O, and staging writers behind ``envmon sync-survey123``.

Arcgis-free: importing this module touches neither ``arcgis`` nor ``arcpy``.
``fetch_item_pulls()`` is the one live seam and lazy-imports through the
``gis`` object it is handed (``runtime.sessions.agol_from_profile``), mirroring
``core/agol/sync_layer.py``.

Sync semantics (ADR-0116):

* Per-layer watermark = the max edit timestamp (epoch ms, the hosted-layer
  ``EditDate`` convention shared with the harvester's incremental mode).
  Fetch uses a strictly-greater where-clause, so a repeated run after a clean
  one pulls nothing — no duplicates.
* The checkpoint is written only AFTER the staging artifacts are durably on
  disk. An interrupted run leaves the old checkpoint, and the next run
  re-pulls the same window; downstream import stays idempotent
  (``append_records_idempotent``).
* Deletions are detected by a full GlobalID sweep diffed against the
  checkpoint's known-ID set. A row added and deleted entirely between two
  runs is never observed — by design, not silently: the envelope stream is a
  change feed, not an audit log.
* ``--since`` replay re-pulls a bounded window and never advances the
  checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

CHECKPOINT_FILENAME = ".survey123_sync_state.json"

OP_ADD = "add"
OP_UPDATE = "update"
OP_DELETE = "delete"


@dataclass
class SubmissionEnvelope:
    """The canonical Survey123 submission envelope (ADR-0113/ADR-0116).

    One record per observed change on one layer/table of a survey's feature
    service. ``repeat_path`` is ``""`` for the parent submission layer and the
    repeat table's name for repeat records (nested repeats surface as their
    own tables; ``parent_global_id`` links a repeat record to its parent).
    ``payload_hash`` is a sha256 over the canonical JSON of
    ``{"attributes": ..., "geometry": ...}`` — ``""`` for deletes, which have
    no payload. ``source`` is pull provenance (profile, pulled_at_ms, mode,
    the layer's effective since watermark).
    """
    item_id: str
    layer_id: int
    layer_name: str
    global_id: str
    operation: str                      # add | update | delete
    edit_time_ms: Optional[int]
    repeat_path: str = ""
    parent_global_id: str = ""
    attributes: dict = field(default_factory=dict)
    geometry: Optional[dict] = None
    attachments: List[dict] = field(default_factory=list)
    payload_hash: str = ""
    source: dict = field(default_factory=dict)


@dataclass
class LayerPull:
    """One layer/table's raw pull — the fetch seam's output, the planner's input.

    ``features`` are the in-window adds/edits (``{"attributes": {...},
    "geometry": {...}|None}``); ``all_global_ids`` is the full current-ID
    sweep used for deletion detection; ``attachments`` maps a GlobalID to its
    attachment-metadata dicts. ``date_fields`` lists esriFieldTypeDate field
    names so the CSV staging writer can render epoch ms readably.
    """
    layer_id: int
    name: str
    is_table: bool = False
    global_id_field: str = "globalid"
    edit_field: str = "EditDate"
    create_field: str = "CreationDate"
    parent_global_id_field: str = ""
    features: List[dict] = field(default_factory=list)
    all_global_ids: List[str] = field(default_factory=list)
    attachments: dict = field(default_factory=dict)
    date_fields: List[str] = field(default_factory=list)


def payload_hash(attributes: dict, geometry: Optional[dict]) -> str:
    """Canonical sha256 of a submission payload — key-order independent."""
    canon = json.dumps({"attributes": attributes, "geometry": geometry},
                       sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _as_int_ms(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def plan_layer_envelopes(
    pull: LayerPull,
    *,
    item_id: str,
    watermark_ms: Optional[int],
    known_global_ids: Iterable[str],
    source: dict,
    qa: QACollector,
) -> tuple[List[SubmissionEnvelope], dict]:
    """Turn one layer's pull into envelopes + its new checkpoint state (pure).

    add vs update: with no watermark (first pull) every feature is an ``add``;
    afterwards a feature whose creation time is inside the window is an
    ``add``, anything else an ``update``. Deletes = known IDs no longer in
    the current sweep.
    """
    known = {str(k) for k in known_global_ids}
    current = {str(g) for g in pull.all_global_ids}
    envelopes: List[SubmissionEnvelope] = []
    max_edit = watermark_ms

    for feat in pull.features:
        attrs = dict(feat.get("attributes") or {})
        geom = feat.get("geometry")
        gid = attrs.get(pull.global_id_field)
        if gid in (None, ""):
            qa.add(SEV_WARNING, "missing_global_id",
                   f"{pull.name}: feature without {pull.global_id_field!r} "
                   f"skipped — no stable identity to sync by. Once the "
                   f"watermark passes its edit time this record will NEVER "
                   f"sync; fix the layer's GlobalID and replay with --since")
            continue
        gid = str(gid)
        edit_ms = _as_int_ms(attrs.get(pull.edit_field))
        create_ms = _as_int_ms(attrs.get(pull.create_field))
        if edit_ms is not None:
            max_edit = edit_ms if max_edit is None else max(max_edit, edit_ms)
        op = (OP_ADD if watermark_ms is None
              or (create_ms is not None and create_ms > watermark_ms)
              else OP_UPDATE)
        parent = attrs.get(pull.parent_global_id_field, "") if \
            pull.parent_global_id_field else ""
        envelopes.append(SubmissionEnvelope(
            item_id=item_id, layer_id=pull.layer_id, layer_name=pull.name,
            global_id=gid, operation=op, edit_time_ms=edit_ms,
            repeat_path=pull.name if pull.is_table else "",
            parent_global_id=str(parent or ""),
            attributes=attrs, geometry=geom,
            attachments=list(pull.attachments.get(gid, [])),
            payload_hash=payload_hash(attrs, geom), source=dict(source)))

    for gid in sorted(known - current):
        envelopes.append(SubmissionEnvelope(
            item_id=item_id, layer_id=pull.layer_id, layer_name=pull.name,
            global_id=gid, operation=OP_DELETE, edit_time_ms=None,
            repeat_path=pull.name if pull.is_table else "",
            source=dict(source)))

    qa.add(SEV_INFO, "sync_layer_summary",
           f"{pull.name}: {sum(1 for e in envelopes if e.operation == OP_ADD)}"
           f" add(s), "
           f"{sum(1 for e in envelopes if e.operation == OP_UPDATE)} "
           f"update(s), {len(known - current)} delete(s)")
    new_state = {"name": pull.name, "last_edit_ms": max_edit,
                 "known_global_ids": sorted(current)}
    return envelopes, new_state


def sync_item(
    pulls: List[LayerPull],
    checkpoint: Optional[dict],
    *,
    item_id: str,
    pulled_at_ms: int,
    mode: str = "sync",
    profile: str = "",
    replay_since_ms: Optional[int] = None,
    qa: QACollector,
) -> tuple[List[SubmissionEnvelope], dict]:
    """Plan every layer's envelopes; return them + the successor checkpoint.

    ``replay_since_ms`` overrides each layer's watermark for add/update
    classification (bounded replay); the returned checkpoint is the normal
    successor either way — the CLI simply does not write it in replay mode.
    """
    layers_state = dict((checkpoint or {}).get("layers") or {})
    envelopes: List[SubmissionEnvelope] = []
    new_layers: dict = {}
    for pull in pulls:
        state = layers_state.get(str(pull.layer_id)) or {}
        watermark = (replay_since_ms if replay_since_ms is not None
                     else state.get("last_edit_ms"))
        source = {"profile": profile, "pulled_at_ms": pulled_at_ms,
                  "mode": mode, "since_ms": watermark}
        layer_env, new_state = plan_layer_envelopes(
            pull, item_id=item_id, watermark_ms=watermark,
            known_global_ids=state.get("known_global_ids") or [],
            source=source, qa=qa)
        if replay_since_ms is not None:
            # replay must not regress a real watermark the layer already has
            prior = state.get("last_edit_ms")
            if prior is not None:
                new_state["last_edit_ms"] = max(
                    prior, new_state["last_edit_ms"] or prior)
        envelopes.extend(layer_env)
        new_layers[str(pull.layer_id)] = new_state
    return envelopes, {"version": 1, "item_id": item_id, "layers": new_layers}


# -- checkpoint I/O ------------------------------------------------------------

def read_checkpoint(directory: Path) -> Optional[dict]:
    path = Path(directory) / CHECKPOINT_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # newline="" — the CSV writer already emits \r\n; platform newline
    # translation would double it to \r\r\n (blank rows on Windows).
    try:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def write_checkpoint(directory: Path, checkpoint: dict) -> Path:
    """Atomically persist the checkpoint. Call only AFTER staging writes."""
    return _atomic_write_text(Path(directory) / CHECKPOINT_FILENAME,
                              json.dumps(checkpoint, indent=2))


# -- staging writers -----------------------------------------------------------

def write_envelopes_jsonl(envelopes: List[SubmissionEnvelope],
                          path: Path) -> Path:
    lines = "".join(json.dumps(asdict(e), sort_keys=True, default=str) + "\n"
                    for e in envelopes)
    return _atomic_write_text(Path(path), lines)


def _date_ms_to_text(ms) -> str:
    """Render an epoch-ms date field for the submissions CSV.

    Midnight UTC renders date-only (what ``normalize_survey123`` parses); a
    real time-of-day keeps its full timestamp — the normalizer then raises a
    visible invalid_date QA ERROR rather than this writer silently guessing
    a timezone and shifting the sampling date.
    """
    as_int = _as_int_ms(ms)
    if as_int is None:
        return "" if ms is None else str(ms)
    dt = datetime.fromtimestamp(as_int / 1000, tz=timezone.utc)
    if (dt.hour, dt.minute, dt.second) == (0, 0, 0):
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def write_submissions_csv(
    envelopes: List[SubmissionEnvelope],
    path: Path,
    *,
    date_fields: Iterable[str] = (),
) -> int:
    """Write parent-layer add/update attributes as the flat submissions CSV.

    This is the artifact ``envmon route-survey123 --format csv`` (and so
    ``load_survey123_csv_submissions`` / the existing normalizer) consumes.
    Repeat-table and delete envelopes are envelope-stream-only. Returns the
    row count (0 writes a header-less empty file so a no-op sync leaves no
    misleading artifact).
    """
    import csv
    import io

    dates = set(date_fields)
    rows = [e for e in envelopes
            if e.repeat_path == "" and e.operation in (OP_ADD, OP_UPDATE)]
    if not rows:
        _atomic_write_text(Path(path), "")
        return 0
    cols: List[str] = []
    for e in rows:                       # first-seen order, stable across runs
        for k in e.attributes:
            if k not in cols:
                cols.append(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, restval="")
    writer.writeheader()
    for e in rows:
        writer.writerow({
            k: (_date_ms_to_text(v) if k in dates else v)
            for k, v in e.attributes.items()})
    _atomic_write_text(Path(path), buf.getvalue())
    return len(rows)


# -- live fetch seam (arcgis) --------------------------------------------------

def fetch_item_pulls(  # pragma: no cover — live seam, headless tests use fakes
    gis,
    item_id: str,
    *,
    checkpoint: Optional[dict] = None,
    replay_since_ms: Optional[int] = None,
    include_attachments: bool = True,
) -> List[LayerPull]:
    """Pull every layer + repeat table of a survey's feature-service item.

    Read-only. Each layer is queried with a strictly-greater edit-timestamp
    where-clause from its checkpoint watermark (or ``replay_since_ms``), plus
    a full GlobalID sweep for deletion detection. Editor tracking is required
    — without an edit timestamp incremental sync cannot be trusted (same rule
    as the harvester's incremental mode). Attachment metadata is fetched only
    for in-window features (the harvester owns attachment downloads).
    """
    item = gis.content.get(item_id)
    if item is None:
        raise ValueError(f"AGOL item {item_id!r} not found in this GIS")
    layers_state = dict((checkpoint or {}).get("layers") or {})

    pulls: List[LayerPull] = []
    for lyr, is_table in ([(l, False) for l in (item.layers or [])]
                          + [(t, True) for t in (item.tables or [])]):
        props = dict(lyr.properties)   # hedge PropertyMap quirks (audit_schema pattern)
        layer_id = int(props["id"])
        name = props.get("name") or f"sublayer_{layer_id}"
        efi = props.get("editFieldsInfo") or {}
        edit_field = efi.get("editDateField")
        create_field = efi.get("creationDateField") or "CreationDate"
        if not edit_field:
            raise ValueError(
                f"Layer {name!r} lacks editor tracking — incremental sync "
                f"needs an edit timestamp. Enable editor tracking on the "
                f"hosted feature layer.")
        gid_field = props.get("globalIdField") or "globalid"
        fields = list(props.get("fields") or [])
        date_fields = [f["name"] for f in fields
                       if f.get("type") == "esriFieldTypeDate"]
        parent_field = next(
            (f["name"] for f in fields
             if f["name"].lower() == "parentglobalid"), "") if is_table else ""

        since = (replay_since_ms if replay_since_ms is not None else
                 (layers_state.get(str(layer_id)) or {}).get("last_edit_ms"))
        where = "1=1" if since is None else f"{edit_field} > {int(since)}"
        result = lyr.query(where=where, out_fields="*",
                           return_geometry=not is_table)
        features = [{"attributes": dict(f.attributes),
                     "geometry": (dict(f.geometry) if f.geometry else None)}
                    for f in result.features]

        sweep = lyr.query(where="1=1", out_fields=gid_field,
                          return_geometry=False)
        all_gids = [str(f.attributes.get(gid_field))
                    for f in sweep.features
                    if f.attributes.get(gid_field) not in (None, "")]

        attachments: dict = {}
        if include_attachments and props.get("hasAttachments"):
            oid_field = props.get("objectIdField") or "objectid"
            for feat in features:
                gid = feat["attributes"].get(gid_field)
                oid = feat["attributes"].get(oid_field)
                if gid in (None, "") or oid is None:
                    continue
                attachments[str(gid)] = [
                    {"id": a.get("id"), "name": a.get("name"),
                     "size": a.get("size"),
                     "content_type": a.get("contentType")}
                    for a in lyr.attachments.get_list(oid=oid)]

        pulls.append(LayerPull(
            layer_id=layer_id, name=name, is_table=is_table,
            global_id_field=gid_field, edit_field=edit_field,
            create_field=create_field, parent_global_id_field=parent_field,
            features=features, all_global_ids=all_gids,
            attachments=attachments, date_fields=date_fields))
    return pulls
