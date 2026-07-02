"""Create/update audience-specific hosted views of a hosted feature layer.

Tool 6.11. ``gis`` is injected; the single arcgis touch (FeatureLayerCollection
for view creation) is lazy inside the create path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


@dataclass
class ViewSpec:
    name: str
    source_layer: str
    allow_fields: Optional[List[str]] = None
    deny_fields: Optional[List[str]] = None
    definition_query: Optional[str] = None
    sensitive_fields: List[str] = field(default_factory=list)


@dataclass
class ViewResult:
    name: str
    created: bool = False
    exposed_fields: List[str] = field(default_factory=list)
    leaked_fields: List[str] = field(default_factory=list)
    qa: QACollector = field(default_factory=QACollector)


def resolve_fields(source_fields: List[str], spec: ViewSpec) -> List[str]:
    """Resolve the exposed field list for a view; allow/deny are mutually exclusive.

    An explicit ``allow_fields=[]`` means "expose nothing" (fail-closed), not
    "no allow-list" -- checked via ``is not None``, not truthiness.
    """
    if spec.allow_fields is not None and spec.deny_fields is not None:
        raise ValueError(
            f"view '{spec.name}': allow_fields and deny_fields are mutually exclusive")
    if spec.allow_fields is not None:
        allow = set(spec.allow_fields)
        return [f for f in source_fields if f in allow]
    if spec.deny_fields is not None:
        deny = set(spec.deny_fields)
        return [f for f in source_fields if f not in deny]
    return list(source_fields)


def load_view_specs(data: dict) -> List[ViewSpec]:
    """Parse {"views": [{name, source_layer, allow_fields|deny_fields, ...}]}."""
    if not isinstance(data, dict):
        raise ValueError(
            f"view spec file must be a YAML mapping with a 'views' key, "
            f"got {type(data).__name__}")
    specs = []
    for entry in data.get("views", []):
        name = entry.get("name")
        source_layer = entry.get("source_layer")
        if not name or not source_layer:
            raise ValueError(
                f"view spec missing 'name' or 'source_layer': {entry}")
        if entry.get("allow_fields") is not None and entry.get("deny_fields") is not None:
            raise ValueError(
                f"view '{name}': allow_fields and deny_fields are mutually exclusive")
        specs.append(ViewSpec(
            name=name, source_layer=source_layer,
            allow_fields=entry.get("allow_fields"), deny_fields=entry.get("deny_fields"),
            definition_query=entry.get("definition_query"),
            sensitive_fields=entry.get("sensitive_fields") or []))
    return specs


def _find_item(gis, title: str):
    """Raises on search failure -- callers must distinguish that from "not found"."""
    matches = gis.content.search(f'title:"{title}"', item_type="Feature Service")
    return next((m for m in matches if m.title == title), None)


def create_stakeholder_view(gis, spec: ViewSpec) -> ViewResult:
    """Create or update one audience-specific hosted view; verify no sensitive-field leak."""
    qa = QACollector()

    try:
        source = _find_item(gis, spec.source_layer)
    except Exception as exc:
        qa.add(SEV_ERROR, "view_source_search_failed",
               f"search failed for source layer '{spec.source_layer}': {exc}")
        return ViewResult(name=spec.name, qa=qa)
    if source is None:
        qa.add(SEV_ERROR, "view_source_missing",
               f"source layer not found: {spec.source_layer}")
        return ViewResult(name=spec.name, qa=qa)

    try:
        source_fields = [f["name"] for f in source.layers[0].properties["fields"]]
    except (IndexError, KeyError, TypeError) as exc:
        qa.add(SEV_ERROR, "view_source_unreadable",
               f"could not read fields from source layer '{spec.source_layer}': {exc}")
        return ViewResult(name=spec.name, qa=qa)

    extra_layers = len(source.layers) - 1
    extra_tables = len(getattr(source, "tables", None) or [])
    if extra_layers > 0 or extra_tables > 0:
        qa.add(SEV_WARNING, "view_unverified_layers",
               f"source service '{spec.source_layer}' has {extra_layers} additional "
               f"layer(s) and {extra_tables} table(s) beyond layers[0] that this tool "
               f"does not filter or verify -- confirm they carry no sensitive data.")

    exposed_intent = resolve_fields(source_fields, spec)

    try:
        existing = _find_item(gis, spec.name)
    except Exception as exc:
        qa.add(SEV_ERROR, "view_existing_search_failed",
               f"search failed while checking for existing view '{spec.name}': {exc}; "
               f"aborting to avoid creating a duplicate view during an outage")
        return ViewResult(name=spec.name, qa=qa)
    if existing is None:
        from arcgis.features import FeatureLayerCollection
        try:
            view_item = FeatureLayerCollection.fromitem(source).manager.create_view(
                name=spec.name)
        except Exception as exc:
            qa.add(SEV_ERROR, "view_create_failed",
                   f"create failed for view '{spec.name}': {exc}")
            return ViewResult(name=spec.name, qa=qa)
        created = True
        qa.add(SEV_INFO, "view_created", f"created hosted view: {spec.name}")
    else:
        view_item = existing
        created = False
        qa.add(SEV_INFO, "view_updated", f"updating existing hosted view: {spec.name}")

    exposed_set = set(exposed_intent)
    definition = {"fields": [{"name": f, "visible": f in exposed_set}
                             for f in source_fields]}
    if spec.definition_query:
        definition["viewDefinitionQuery"] = spec.definition_query
    try:
        view_item.layers[0].manager.update_definition(definition)
    except Exception as exc:
        qa.add(SEV_ERROR, "view_definition_failed",
               f"definition update failed for view '{spec.name}': {exc}")
        return ViewResult(name=spec.name, created=created, qa=qa)

    realized = [f["name"] for f in view_item.layers[0].properties["fields"]
               if f.get("visible", True)]
    leaked = [s for s in spec.sensitive_fields if s in realized]
    if leaked:
        qa.add(SEV_ERROR, "view_sensitive_leak",
               f"view '{spec.name}' still exposes sensitive field(s): {leaked}",
               recommended_action="delete or fix the view in AGOL before sharing")
    else:
        qa.add(SEV_INFO, "view_verified",
               f"view '{spec.name}' verified: no sensitive fields exposed")

    return ViewResult(name=spec.name, created=created, exposed_fields=realized,
                      leaked_fields=leaked, qa=qa)
