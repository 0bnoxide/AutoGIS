"""Create or update an AGOL Dashboard item from a compiled spec.

Requires the ``cloud`` extra (arcgis) at call time, but ``gis`` is injected
(same discipline as ``publish.py``) so this module never imports arcgis
itself and is safe to import without the cloud extra installed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .dashboard_spec import compile_dashboard_json
from ..common.qa import QACollector, SEV_INFO, SEV_ERROR


@dataclass
class PublishDashboardResult:
    item_id: str
    created: bool                # True if new, False if updated
    qa: QACollector = field(default_factory=QACollector)
    dashboard_json: dict = field(default_factory=dict)  # compiled JSON (always populated)


def _find_existing(gis, spec: dict, title: str):
    item_id = spec.get("item_id")
    if item_id:
        try:
            item = gis.content.get(item_id)
        except Exception:
            item = None
        if item is not None:
            return item
    matches = gis.content.search(f'title:"{title}"', item_type="Dashboard")
    return next((m for m in matches if m.title == title), None)


def publish_dashboard(
    gis,
    spec: dict,
    *,
    dry_run: bool = False,
) -> PublishDashboardResult:
    """Create or update a dashboard item from its compiled spec JSON."""
    qa = QACollector()
    title = spec["title"]
    dashboard_json = compile_dashboard_json(spec)

    if dry_run:
        qa.add(SEV_INFO, "dashboard_dry_run",
               f"dry run: compiled dashboard JSON for '{title}', no publish call made")
        return PublishDashboardResult(item_id="", created=False, qa=qa,
                                       dashboard_json=dashboard_json)

    existing = _find_existing(gis, spec, title)
    item_props = {
        "title": title,
        "type": "Dashboard",
        "tags": ",".join(spec.get("tags", [])),
        "description": spec.get("description", ""),
        "text": json.dumps(dashboard_json),
    }

    if existing is not None:
        try:
            existing.update(item_properties=item_props)
            qa.add(SEV_INFO, "dashboard_updated",
                   f"updated dashboard item: {title}",
                   recommended_action="verify widget bindings in AGOL")
            return PublishDashboardResult(item_id=existing.id, created=False, qa=qa,
                                           dashboard_json=dashboard_json)
        except Exception as exc:
            qa.add(SEV_ERROR, "dashboard_update_failed",
                   f"update failed for '{title}': {exc}")
            return PublishDashboardResult(item_id=existing.id, created=False, qa=qa,
                                           dashboard_json=dashboard_json)

    try:
        item = gis.content.add(item_props, folder=spec.get("folder"))
        qa.add(SEV_INFO, "dashboard_created",
               f"created dashboard item: {title}",
               recommended_action="verify widget bindings in AGOL")
        return PublishDashboardResult(item_id=item.id, created=True, qa=qa,
                                       dashboard_json=dashboard_json)
    except Exception as exc:
        qa.add(SEV_ERROR, "dashboard_create_failed",
               f"create failed for '{title}': {exc}")
        return PublishDashboardResult(item_id="", created=False, qa=qa,
                                       dashboard_json=dashboard_json)
