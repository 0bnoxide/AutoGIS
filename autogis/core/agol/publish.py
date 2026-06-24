"""Publish or overwrite a hosted AGOL feature service.

Requires the ``cloud`` extra (arcgis). All arcgis imports are lazy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_ERROR


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
    ``source_path`` must be a zip of an FGDB or a JSON FeatureSet — the
    caller is responsible for preparing it.
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
                from arcgis.features.managers import FeatureLayerManager
                mgr = FeatureLayerManager(existing.layers[0].url, gis)
                mgr.overwrite(str(src))
                qa.add(SEV_INFO, "publish_overwritten",
                       f"overwritten hosted feature service: {config.title}",
                       recommended_action="verify symbology and sharing in AGOL")
                return existing
            except Exception as exc:
                qa.add(SEV_ERROR, "publish_overwrite_failed",
                       f"overwrite failed for '{config.title}': {exc}")
                return None

        item_props = {
            "title": config.title,
            "tags": ",".join(config.tags),
            "description": config.description,
            "type": "File Geodatabase",
        }
        item = gis.content.add(item_props, data=str(src), folder=config.folder)
        published = item.publish()
        if config.share_with != "private":
            everyone = config.share_with == "everyone"
            published.share(org=True, everyone=everyone)
        qa.add(SEV_INFO, "publish_created",
               f"created hosted feature service: {config.title}",
               recommended_action="verify symbology and sharing in AGOL")
        return published

    except Exception as exc:
        qa.add(SEV_ERROR, "publish_failed",
               f"publish failed for '{config.title}': {exc}")
        return None
