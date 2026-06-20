import os
import time

from .models import AttachmentResult, RunSummary, summary_counts
from .manifest import Manifest
from .templates import render_path_component
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
        layer = item.layers[0]
    if not _prop(layer.properties, "hasAttachments"):
        raise ValueError(
            f"Layer {config.layer_ref()} does not have attachments enabled")
    return layer


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


def harvest(gis, config, *, layer=None, now_ms=None, sleep=time.sleep):
    if layer is None:
        layer = resolve_layer(gis, config)

    where = _effective_where(config, layer)
    manifest = Manifest()

    result = layer.query(where=where, out_fields="*", return_geometry=False)
    for feature in result.features:
        attrs = feature.attributes
        objectid = attrs.get("OBJECTID")
        for att in layer.attachments.get_list(oid=objectid):
            att_id, name, size = att["id"], att["name"], att.get("size")
            group = render_path_component(config.group_template, attrs)
            fname = render_path_component(
                config.filename_template, {**attrs, "name": name})
            dest = os.path.join(config.directory, group, fname)

            if config.skip_existing and os.path.exists(dest):
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "skipped",
                    disposition="skipped"))
                continue
            try:
                download_one(layer, objectid, att_id, dest,
                             config.retries, config.backoff_seconds, sleep=sleep)
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "downloaded",
                    disposition="downloaded"))
            except Exception as exc:  # resilience: never kill the run
                manifest.add(AttachmentResult(
                    objectid, att_id, name, None, size, "failed", str(exc),
                    disposition="failed"))

    manifest.write(config.directory)
    counts = summary_counts(manifest.results)
    summary = RunSummary.from_counts(counts)
    if config.incremental and summary.failed == 0:
        resolved_now = now_ms if now_ms is not None else int(time.time() * 1000)
        write_last_run(config.directory, resolved_now)
    return summary
