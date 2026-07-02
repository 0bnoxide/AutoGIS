"""Apply a figure spec's display config to an AGOL web map. Tool 6.3.

``gis`` is injected (same discipline as ``publish.py``); this module never
imports arcgis -- the web-map read/write goes through injected item methods
(``item.get_data()`` / ``item.update()``).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


@dataclass
class WebMapUpdateResult:
    item_id: str
    layers_updated: int = 0
    layers_missing: list = field(default_factory=list)
    qa: QACollector = field(default_factory=QACollector)
    webmap_json: dict = field(default_factory=dict)


def apply_spec_to_webmap_json(webmap_json: dict, figure_spec: dict, qa: QACollector,
                              *, event_date: str = ""):
    """Pure. Returns (new_json, layers_updated, layers_missing).

    Only visibility and definition-query fields are applied -- the canonical
    FigureSpec carries no popup/label/symbology config.
    """
    new_json = copy.deepcopy(webmap_json)
    layers = new_json.get("operationalLayers") or []
    by_title = {(lyr.get("title") or "").lower(): lyr for lyr in layers}

    fmt = dict(site_id=figure_spec.get("site_id", ""), event_date=event_date,
               figure_spec_id=figure_spec.get("figure_spec_id", ""),
               map_type=figure_spec.get("map_type", ""))

    changed = set()
    missing = set()

    for name in figure_spec.get("visible_layers") or []:
        lyr = by_title.get(name.lower())
        if lyr is None:
            missing.add(name)
            continue
        if lyr.get("visibility") is not True:
            lyr["visibility"] = True
            changed.add(name)
            qa.add(SEV_INFO, "webmap_change", f"layer '{name}': visibility -> True")

    for name in figure_spec.get("hidden_layers") or []:
        lyr = by_title.get(name.lower())
        if lyr is None:
            missing.add(name)
            continue
        if lyr.get("visibility") is not False:
            lyr["visibility"] = False
            changed.add(name)
            qa.add(SEV_INFO, "webmap_change", f"layer '{name}': visibility -> False")

    for name, template in (figure_spec.get("layer_definition_queries") or {}).items():
        lyr = by_title.get(name.lower())
        if lyr is None:
            missing.add(name)
            continue
        try:
            rendered = template.format(**fmt)
        except (KeyError, IndexError, ValueError, AttributeError) as exc:
            # AttributeError: a present-but-null template (YAML `Layer:` with
            # no value) has no .format -- degrade, don't crash.
            qa.add(SEV_WARNING, "defquery_render_failed",
                   f"layer '{name}': could not render definition query template: {exc}")
            continue
        current = lyr.get("layerDefinition", {}).get("definitionExpression")
        if current != rendered:
            lyr.setdefault("layerDefinition", {})["definitionExpression"] = rendered
            changed.add(name)
            qa.add(SEV_INFO, "webmap_change",
                   f"layer '{name}': definitionExpression -> {rendered!r}")

    for name in sorted(missing):
        qa.add(SEV_WARNING, "webmap_layer_missing",
               f"figure spec names layer '{name}' but it is not in the web map.",
               recommended_action="Add the layer to the web map or fix the figure spec.")

    return new_json, len(changed), sorted(missing)


def update_webmap_from_spec(gis, *, webmap_item_id: str, figure_spec: dict,
                            event_date: str = "", dry_run: bool = False) -> WebMapUpdateResult:
    """Push a figure spec's display config into an AGOL web map's JSON."""
    qa = QACollector()
    try:
        item = gis.content.get(webmap_item_id)
    except Exception as exc:
        qa.add(SEV_ERROR, "webmap_item_fetch_failed",
               f"fetch failed for web map item '{webmap_item_id}': {exc}")
        return WebMapUpdateResult(item_id=webmap_item_id, qa=qa)
    if item is None:
        qa.add(SEV_ERROR, "webmap_item_missing",
               f"web map item not found: {webmap_item_id}")
        return WebMapUpdateResult(item_id=webmap_item_id, qa=qa)

    try:
        data = item.get_data() or {}
    except Exception as exc:
        qa.add(SEV_ERROR, "webmap_data_unreadable",
               f"could not read web map JSON for '{webmap_item_id}': {exc}")
        return WebMapUpdateResult(item_id=webmap_item_id, qa=qa)

    new_json, layers_updated, layers_missing = apply_spec_to_webmap_json(
        data, figure_spec, qa, event_date=event_date)

    if dry_run:
        qa.add(SEV_INFO, "webmap_dry_run",
               f"dry run: computed {layers_updated} layer change(s) for '{webmap_item_id}', "
               f"no update call made")
        return WebMapUpdateResult(item_id=webmap_item_id, layers_updated=layers_updated,
                                  layers_missing=layers_missing, qa=qa, webmap_json=new_json)

    if layers_updated == 0:
        qa.add(SEV_INFO, "webmap_no_changes",
               f"web map '{webmap_item_id}' already matches the figure spec; nothing to update")
        return WebMapUpdateResult(item_id=webmap_item_id, layers_updated=0,
                                  layers_missing=layers_missing, qa=qa, webmap_json=new_json)

    try:
        item.update(item_properties={"text": json.dumps(new_json)})
        qa.add(SEV_INFO, "webmap_updated",
               f"updated web map '{webmap_item_id}': {layers_updated} layer(s) changed",
               recommended_action="verify layer rendering in AGOL")
    except Exception as exc:
        qa.add(SEV_ERROR, "webmap_update_failed",
               f"update failed for web map '{webmap_item_id}': {exc}")

    return WebMapUpdateResult(item_id=webmap_item_id, layers_updated=layers_updated,
                              layers_missing=layers_missing, qa=qa, webmap_json=new_json)
