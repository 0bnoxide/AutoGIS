import hashlib
import json
import logging
import math
import os
import time
from datetime import datetime, timezone

from .models import AttachmentResult, RunSummary, summary_counts
from ..common.config import ConfigError
from .manifest import Manifest
from .templates import render_path_component, sanitize
from .download import download_one
from .state import read_last_run, write_last_run

logger = logging.getLogger(__name__)

def _feature_layer_cls():
    """Import ``arcgis.features.FeatureLayer`` on demand, or return None.

    Deliberately lazy (issue #371): a module-scope import pulled ``arcgis``
    into ``sys.modules`` on any clean ``import autogis`` wherever the optional
    package happened to be installed, breaking the documented invariant that
    ``core/`` and ``adapters/`` import with neither arcpy nor arcgis present.
    Only the URL branch of ``resolve_layer`` ever needs the class.
    """
    try:
        from arcgis.features import FeatureLayer
    except Exception:  # pragma: no cover - only without arcgis installed
        return None
    return FeatureLayer


def _prop(props, key, default=None):
    if isinstance(props, dict):
        return props.get(key, default)
    return getattr(props, key, default)


def resolve_layer(gis, config):
    if config.url:
        feature_layer_cls = _feature_layer_cls()
        if feature_layer_cls is None:
            raise RuntimeError("arcgis is required to resolve a layer by URL")
        layer = feature_layer_cls(config.url, gis)
    else:
        item = gis.content.get(config.item_id)
        # config.layer_index is AGOL's REST/portal sublayer id (the
        # continuous ?sublayer=N numbering across layers+tables combined),
        # NOT a positional index into the arcgis API's separate .layers[]/
        # .tables[] arrays -- those arrays aren't guaranteed sorted by id or
        # laid out layers-then-tables, so we match on each sublayer's own
        # .properties.id rather than concatenating-and-indexing positionally.
        sublayers = list(item.layers or []) + list(item.tables or [])
        by_id = {_prop(s.properties, "id"): s for s in sublayers}
        if config.layer_index not in by_id:
            raise ConfigError(
                f"layer_index {config.layer_index} does not match any "
                f"sublayer id for item {config.item_id}: available ids are "
                f"{sorted(i for i in by_id if i is not None)}")
        layer = by_id[config.layer_index]
    if not _prop(layer.properties, "hasAttachments"):
        raise ValueError(
            f"Layer {config.layer_ref()} does not have attachments enabled")
    return layer


def resolve_all_layers(gis, config):
    """Every attachment-bearing layer/table of the item, combined-list order."""
    item = gis.content.get(config.item_id)
    sublayers = list(item.layers or []) + list(item.tables or [])
    with_attachments = [
        s for s in sublayers if _prop(s.properties, "hasAttachments")]
    if not with_attachments:
        raise ValueError(
            f"Item {config.item_id} has no layers or tables with "
            f"attachments enabled")
    return with_attachments


def _sublayer_name(layer) -> str:
    name = _prop(layer.properties, "name")
    return name if name else f"sublayer_{_prop(layer.properties, 'id')}"


def _sublayer_folder(layer, name) -> str:
    # REST sublayer ids are unique per item (they're the ?sublayer=N
    # numbering) -- suffixing with it guarantees distinct subfolders even
    # when two sublayers' names sanitize to the same string (e.g. "Photos
    # (A)" and "Photos [A]" both -> "Photos_A"), which would otherwise
    # silently reintroduce the cross-sublayer OBJECTID collision this
    # per-sublayer split exists to prevent.
    return f"{sanitize(name)}_{_prop(layer.properties, 'id')}"


def _effective_where(config, layer):
    where = config.where
    if not config.incremental:
        return where
    if not _prop(layer.properties, "editorTrackingInfo"):
        raise ValueError(
            "Incremental run requires editor tracking, which this layer lacks")
    last = read_last_run(config.directory)
    if last is not None:
        clause = f"EditDate > {last}"
        where = clause if where in ("1=1", "", None) else f"({where}) AND {clause}"
    return where


_WEB_MERCATOR_WKIDS = {3857, 102100}
_R = 6378137.0


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _vertices(geom):
    if geom.get("x") is not None and geom.get("y") is not None:
        return [(geom["x"], geom["y"])]
    parts = geom.get("paths") or geom.get("rings") or []
    return [(x, y) for part in parts for x, y, *_ in part]


def _rep_point_wgs84(geom, result):
    """Representative point of an Esri geometry dict as (lat, lon) WGS84.

    Returns None for absent/empty geometry (silent — normal for tables) or
    the sentinel string "unsupported" when geometry exists but its spatial
    reference is missing or not convertible (caller warns once per layer).
    ponytail: 4326 + web-mercator only; extend when another SR shows up.
    """
    if not isinstance(geom, dict):
        return None
    verts = _vertices(geom)
    if not verts:
        return None
    x = sum(v[0] for v in verts) / len(verts)
    y = sum(v[1] for v in verts) / len(verts)
    sr = geom.get("spatialReference") or getattr(
        result, "spatial_reference", None) or {}
    wkid = (sr.get("latestWkid") or sr.get("wkid")) if isinstance(sr, dict) \
        else None
    if wkid == 4326:
        return (y, x)
    if wkid in _WEB_MERCATOR_WKIDS:
        lon = math.degrees(x / _R)
        lat = math.degrees(2 * math.atan(math.exp(y / _R)) - math.pi / 2)
        return (lat, lon)
    return "unsupported"


def _edit_date_field(layer):
    info = _prop(layer.properties, "editFieldsInfo")
    return _prop(info, "editDateField") if info else None


def _iso_utc(ms):
    try:
        return datetime.fromtimestamp(
            int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _harvest_layer(layer, config, manifest, base_dir, source_table, sleep):
    """Query ONE layer/table and accumulate its attachments into the shared
    manifest, rooting destination paths at ``base_dir``."""
    where = _effective_where(config, layer)
    result = layer.query(where=where, out_fields="*", return_geometry=True)
    edit_field = _edit_date_field(layer)
    unsupported_sr = 0
    for feature in result.features:
        attrs = feature.attributes
        objectid = attrs.get("OBJECTID")
        rep = _rep_point_wgs84(getattr(feature, "geometry", None), result)
        if rep == "unsupported":
            unsupported_sr += 1
            rep = None
        geometry_json = (json.dumps(
            {"lat": round(rep[0], 7), "lon": round(rep[1], 7)})
            if rep else None)
        edited_at = _iso_utc(attrs.get(edit_field)) if edit_field else None
        for att in layer.attachments.get_list(oid=objectid):
            att_id, name, size = att["id"], att["name"], att.get("size")
            group = render_path_component(config.group_template, attrs)
            fname = render_path_component(
                config.filename_template, {**attrs, "name": name})
            dest = os.path.join(base_dir, group, fname)

            if config.skip_existing and os.path.exists(dest):
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "skipped",
                    disposition="skipped", source_table=source_table,
                    checksum=_sha256(dest), algorithm="sha256",
                    geometry=geometry_json, feature_edited_at=edited_at))
                continue
            try:
                download_one(layer, objectid, att_id, dest,
                             config.retries, config.backoff_seconds, sleep=sleep)
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "downloaded",
                    disposition="downloaded", source_table=source_table,
                    checksum=_sha256(dest), algorithm="sha256",
                    geometry=geometry_json, feature_edited_at=edited_at))
            except Exception as exc:  # resilience: never kill the run
                manifest.add(AttachmentResult(
                    objectid, att_id, name, None, size, "failed", str(exc),
                    disposition="failed", source_table=source_table,
                    geometry=geometry_json, feature_edited_at=edited_at))
    if unsupported_sr:
        logger.warning(
            "%s: %d feature(s) in an unsupported spatial reference — "
            "manifest geometry left null (supported: WGS84, Web Mercator)",
            source_table, unsupported_sr)


def harvest(gis, config, *, layer=None, now_ms=None, sleep=time.sleep):
    if layer is not None:
        layers = [layer]
    elif config.all_sublayers:
        layers = resolve_all_layers(gis, config)
    else:
        layers = [resolve_layer(gis, config)]

    manifest = Manifest()
    for sub in layers:
        name = _sublayer_name(sub)
        # In all-sublayers mode each sublayer gets its own subfolder: two
        # sublayers of one item can share OBJECTID values, so a flat shared
        # directory could silently overwrite one sublayer's downloads with
        # another's. Single-sublayer paths stay byte-identical to before.
        base_dir = (os.path.join(config.directory, _sublayer_folder(sub, name))
                    if config.all_sublayers else config.directory)
        try:
            _harvest_layer(sub, config, manifest, base_dir, name, sleep)
        except Exception as exc:
            # Only in all-sublayers mode: a fatal error resolving/querying
            # ONE sublayer (bad where-clause for its schema, transient
            # network error, ...) must not discard already-recorded results
            # for the sublayers processed before it, nor skip the ones
            # after -- same "never kill the run" resilience as per-attachment
            # failures in _harvest_layer, one level up. Single-sublayer mode
            # keeps its pre-existing behavior of propagating the exception.
            if not config.all_sublayers:
                raise
            manifest.add(AttachmentResult(
                None, None, name, None, None, "failed", str(exc),
                disposition="failed", source_table=name))

    manifest.write(config.directory)
    counts = summary_counts(manifest.results)
    summary = RunSummary.from_counts(counts)
    summary.results = list(manifest.results)
    if config.incremental and summary.failed == 0:
        resolved_now = now_ms if now_ms is not None else int(time.time() * 1000)
        write_last_run(config.directory, resolved_now)
    return summary
