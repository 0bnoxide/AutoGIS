"""Compile a YAML dashboard spec into AGOL Dashboard item JSON.

Pure, arcgis-free -- takes/returns plain dicts so it is fully unit-testable
without arcgis installed or any mocking. ``dashboard_publish.py`` is the only
module that touches a live ``gis``.

Spec shape (all keys optional except ``title``)::

    title: str
    description: str
    tags: [str, ...]
    webmap_item_id: str            # AGOL Web Map item id the dashboard embeds
    theme: "light" | "dark"        # default "light"
    refresh_interval_seconds: int  # default 0 (no auto-refresh)
    item_id: str                   # existing Dashboard item id, for update matching
    folder: str                    # AGOL content folder for create
    cards:                         # indicator cards
      - title: str
        layer: str                # Dash_* data-mart layer name
        stat: "count" | "sum" | "avg" | ...   # default "count"
        field: str                # field to aggregate (optional for "count")
    charts:                        # serial charts
      - title: str
        layer: str
        category_field: str
        value_fields: [str, ...]
    selectors:
      - type: "category" | "date"
        layer: str
        field: str
        label: str
    lists:
      - title: str
        layer: str
        fields: [str, ...]
    embeds:                        # embedded report/content links
      - title: str
        url: str
    filters:
      - layer: str
        field: str
        operator: str              # default "equals"
        value: any
"""
from __future__ import annotations

from typing import Any, Dict, List

_SELECTOR_WIDGET_TYPES = {
    "category": "categorySelectorWidget",
    "date": "dateSelectorWidget",
}


def _compile_card(index: int, card: dict) -> dict:
    return {
        "type": "indicatorWidget",
        "id": f"indicator-{index}",
        "name": card["title"],
        "datasets": [{
            "type": "serviceDataset",
            "layer": card["layer"],
            "statisticDefinition": {
                "onStatisticField": card.get("field", ""),
                "outStatisticFieldName": "value",
                "statisticType": card.get("stat", "count"),
            },
        }],
    }


def _compile_chart(index: int, chart: dict) -> dict:
    return {
        "type": "serialChartWidget",
        "id": f"chart-{index}",
        "name": chart["title"],
        "datasets": [{
            "type": "serviceDataset",
            "layer": chart["layer"],
            "groupByFields": [chart.get("category_field", "")],
            "valueFields": chart.get("value_fields", []),
        }],
    }


def _compile_list(index: int, lst: dict) -> dict:
    return {
        "type": "listWidget",
        "id": f"list-{index}",
        "name": lst["title"],
        "datasets": [{
            "type": "serviceDataset",
            "layer": lst["layer"],
            "fields": lst.get("fields", []),
        }],
    }


def _compile_embed(index: int, embed: dict) -> dict:
    return {
        "type": "embeddedContentWidget",
        "id": f"embed-{index}",
        "name": embed["title"],
        "url": embed["url"],
    }


def _compile_selector(index: int, selector: dict) -> dict:
    kind = selector.get("type")
    widget_type = _SELECTOR_WIDGET_TYPES.get(kind)
    if widget_type is None:
        raise ValueError(
            f"unknown selector type {kind!r}; expected one of "
            f"{sorted(_SELECTOR_WIDGET_TYPES)}"
        )
    return {
        "type": widget_type,
        "id": f"selector-{index}",
        "name": selector.get("label", selector.get("field", "")),
        "datasets": [{
            "type": "serviceDataset",
            "layer": selector["layer"],
            "field": selector["field"],
        }],
    }


def _compile_filter(flt: dict) -> dict:
    return {
        "layer": flt["layer"],
        "field": flt["field"],
        "operator": flt.get("operator", "equals"),
        "value": flt.get("value"),
    }


def compile_dashboard_json(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a dashboard spec dict into AGOL Dashboard item JSON."""
    if not spec.get("title"):
        raise ValueError("dashboard spec missing required 'title'")

    widgets: List[dict] = []
    widgets += [_compile_card(i, c) for i, c in enumerate(spec.get("cards", []))]
    widgets += [_compile_chart(i, c) for i, c in enumerate(spec.get("charts", []))]
    widgets += [_compile_list(i, l) for i, l in enumerate(spec.get("lists", []))]
    widgets += [_compile_embed(i, e) for i, e in enumerate(spec.get("embeds", []))]

    return {
        "version": "2.3",
        "header": {
            "title": spec["title"],
            "webmapItemId": spec.get("webmap_item_id", ""),
        },
        "theme": spec.get("theme", "light"),
        "settings": {
            "refreshIntervalSeconds": spec.get("refresh_interval_seconds", 0),
        },
        "widgets": widgets,
        "selectors": [_compile_selector(i, s) for i, s in enumerate(spec.get("selectors", []))],
        "filters": [_compile_filter(f) for f in spec.get("filters", [])],
    }
