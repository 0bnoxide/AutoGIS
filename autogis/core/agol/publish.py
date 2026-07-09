"""Publish or overwrite a hosted AGOL feature service.

Requires the ``cloud`` extra (arcgis). All arcgis imports are lazy.
"""
from __future__ import annotations

import re
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_ERROR


# ponytail: .json/.geojson are both uploaded as GeoJson; sniffing Esri-JSON
# FeatureSets apart from GeoJSON can be added if anyone actually publishes one.
_JSON_ITEM_TYPES = {".json": "GeoJson", ".geojson": "GeoJson"}


def _source_item_type(src: Path, qa: QACollector) -> Optional[str]:
    """Map the source file to its AGOL item type; None + QA error if unsupported."""
    suffix = src.suffix.lower()
    if suffix != ".zip":
        item_type = _JSON_ITEM_TYPES.get(suffix)
        if item_type is None:
            qa.add(SEV_ERROR, "publish_source_unsupported",
                   f"unsupported source type '{suffix}' for {src}; expected a .zip "
                   "of a file geodatabase or shapefiles, or a .json/.geojson")
        return item_type
    try:
        with zipfile.ZipFile(src) as zf:
            names = [n.lower() for n in zf.namelist()]
    except zipfile.BadZipFile:
        qa.add(SEV_ERROR, "publish_source_unsupported",
               f"source is not a valid zip archive: {src}")
        return None
    names = [n.replace("\\", "/") for n in names]
    if any(".gdb/" in n for n in names):
        return "File Geodatabase"
    if any(n.endswith(".shp") for n in names):
        return "Shapefile"
    qa.add(SEV_ERROR, "publish_source_unsupported",
           f"zip contains neither a file geodatabase nor shapefiles: {src}")
    return None


@dataclass
class PublishConfig:
    title: str
    tags: List[str]
    description: str = ""
    folder: Optional[str] = None
    share_with: str = "org"    # "private" | "org" | "everyone"
    overwrite: bool = True


def publish_or_overwrite_layer(
    gis,
    config: PublishConfig,
    source_path: str,
    qa: Optional[QACollector] = None,
) -> Optional[object]:
    """Publish or overwrite a hosted feature service.

    Returns the published Item on success, None on failure (error in qa).
    ``source_path`` must be a zip of an FGDB or of shapefiles, or a
    GeoJSON file — the caller is responsible for preparing it.
    """
    qa = qa or QACollector()
    src = Path(source_path)
    if not src.exists():
        qa.add(SEV_ERROR, "publish_source_missing",
               f"source file does not exist: {src}")
        return None

    try:
        matches = gis.content.search(f'title:"{config.title}"',
                                     item_type="Feature Service")
        existing = next((m for m in matches if m.title == config.title), None)

        if existing and config.overwrite:
            try:
                # ponytail: no _source_item_type() precheck here -- an overwrite
                # must match the existing service's type regardless, and
                # mgr.overwrite's failure now carries a full traceback (#180).
                from arcgis.features.managers import FeatureLayerManager
                mgr = FeatureLayerManager(existing.layers[0].url, gis)
                mgr.overwrite(str(src))
                qa.add(SEV_INFO, "publish_overwritten",
                       f"overwritten hosted feature service: {config.title}",
                       recommended_action="verify symbology and sharing in AGOL")
                return existing
            except Exception as exc:
                qa.add(SEV_ERROR, "publish_overwrite_failed",
                       f"overwrite failed for '{config.title}': {exc!r}\n"
                       f"{traceback.format_exc()}")
                return None

        item_type = _source_item_type(src, qa)
        if item_type is None:
            return None

        # Pre-check the derived hosted service name: arcgis 2.4.3 crashes with an
        # opaque `str + None` TypeError when AGOL synchronously rejects a publish
        # whose name is taken (including soft-deleted "ghost" services still
        # reserving the name in the Recycle Bin). See issue #180.
        service_name = re.sub(r"[\W_]+", "_", config.title).strip("_")
        if not service_name:
            qa.add(SEV_ERROR, "publish_name_invalid",
                   f"title '{config.title}' sanitizes to an empty service name; "
                   "choose a title with at least one alphanumeric character")
            return None
        if not gis.content.is_service_name_available(service_name, "featureService"):
            qa.add(SEV_ERROR, "publish_name_taken",
                   f"hosted service name '{service_name}' is already taken in this "
                   "org (possibly a soft-deleted service in the Recycle Bin); "
                   "permanently delete it or choose a different title")
            return None

        item_props = {
            "title": config.title,
            "tags": ",".join(config.tags),
            "description": config.description,
            "type": item_type,
        }
        item = gis.content.add(item_props, data=str(src), folder=config.folder)
        published = item.publish(publish_parameters={"name": service_name})
        if config.share_with != "private":
            everyone = config.share_with == "everyone"
            published.share(org=True, everyone=everyone)
        qa.add(SEV_INFO, "publish_created",
               f"created hosted feature service: {config.title}",
               recommended_action="verify symbology and sharing in AGOL")
        return published

    except Exception as exc:
        # Keep the frames: a bare message like "can only concatenate str (not
        # NoneType) to str" is undiagnosable without them. See issue #180.
        qa.add(SEV_ERROR, "publish_failed",
               f"publish failed for '{config.title}': {exc!r}\n"
               f"{traceback.format_exc()}")
        return None
