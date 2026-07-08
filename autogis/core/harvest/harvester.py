import os
import time

from .models import AttachmentResult, RunSummary, summary_counts
from ..common.config import ConfigError
from .manifest import Manifest
from .templates import render_path_component, sanitize
from .download import download_one
from .state import read_last_run, write_last_run

try:  # arcgis is optional at import time (tests inject the layer)
    from arcgis.features import FeatureLayer
except Exception:  # pragma: no cover - exercised only without arcgis installed
    FeatureLayer = None


def _prop(props, key, default=None):
    if isinstance(props, dict):
        return props.get(key, default)
    return getattr(props, key, default)


def resolve_layer(gis, config):
    if config.url:
        if FeatureLayer is None:
            raise RuntimeError("arcgis is required to resolve a layer by URL")
        layer = FeatureLayer(config.url, gis)
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


def _harvest_layer(layer, config, manifest, base_dir, source_table, sleep):
    """Query ONE layer/table and accumulate its attachments into the shared
    manifest, rooting destination paths at ``base_dir``."""
    where = _effective_where(config, layer)
    result = layer.query(where=where, out_fields="*", return_geometry=False)
    for feature in result.features:
        attrs = feature.attributes
        objectid = attrs.get("OBJECTID")
        for att in layer.attachments.get_list(oid=objectid):
            att_id, name, size = att["id"], att["name"], att.get("size")
            group = render_path_component(config.group_template, attrs)
            fname = render_path_component(
                config.filename_template, {**attrs, "name": name})
            dest = os.path.join(base_dir, group, fname)

            if config.skip_existing and os.path.exists(dest):
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "skipped",
                    disposition="skipped", source_table=source_table))
                continue
            try:
                download_one(layer, objectid, att_id, dest,
                             config.retries, config.backoff_seconds, sleep=sleep)
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "downloaded",
                    disposition="downloaded", source_table=source_table))
            except Exception as exc:  # resilience: never kill the run
                manifest.add(AttachmentResult(
                    objectid, att_id, name, None, size, "failed", str(exc),
                    disposition="failed", source_table=source_table))


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
        base_dir = (os.path.join(config.directory, sanitize(name))
                    if config.all_sublayers else config.directory)
        _harvest_layer(sub, config, manifest, base_dir, name, sleep)

    manifest.write(config.directory)
    counts = summary_counts(manifest.results)
    summary = RunSummary.from_counts(counts)
    summary.results = list(manifest.results)
    if config.incremental and summary.failed == 0:
        resolved_now = now_ms if now_ms is not None else int(time.time() * 1000)
        write_last_run(config.directory, resolved_now)
    return summary
