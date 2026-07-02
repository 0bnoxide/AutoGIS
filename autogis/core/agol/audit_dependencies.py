"""Audit AGOL item dependency graph (HYBRID)."""
from __future__ import annotations
import dataclasses
from typing import List, Set
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


@dataclasses.dataclass
class DependencyRecord:
    source_item_id: str
    source_title: str
    dependent_item_id: str
    dependent_title: str
    dependent_type: str
    relationship: str   # always "references"


def audit_item_dependencies(
    gis,
    item_id: str,
    *,
    qa: QACollector,
    max_depth: int = 2,
) -> List[DependencyRecord]:
    """Return items that reference item_id, recursively up to max_depth."""
    source = gis.content.get(item_id)
    if source is None:
        qa.add(SEV_ERROR, "item_not_found",
               f"Item {item_id!r} not found in AGOL")
        return []

    records: List[DependencyRecord] = []
    visited: Set[str] = set()
    _walk(gis, source, records, depth=0, max_depth=max_depth,
          visited=visited, qa=qa)
    qa.add(SEV_INFO, "audit_complete",
           f"audit_item_dependencies: {len(records)} dependency record(s) "
           f"for {source.title!r} (depth={max_depth})")
    return records


def _walk(gis, source, records, depth, max_depth, visited, qa):
    if depth >= max_depth or source.id in visited:
        return
    visited.add(source.id)
    try:
        # dependent_to() lists items that reference `source` (the reverse of
        # dependent_upon(), which lists what `source` itself depends on). The
        # tool's job is decommission safety -- "what breaks if I delete this"
        # -- so it must walk the reverse direction.
        dep_info = source.dependent_to()
        dep_list = dep_info.get("list") or [] if isinstance(dep_info, dict) else []
    except Exception as exc:
        qa.add(SEV_WARNING, "dependency_walk_error",
               f"Could not fetch dependencies for {source.id}: {exc}")
        return
    for entry in dep_list:
        dep_id = entry.get("id") if isinstance(entry, dict) else getattr(entry, "id", None)
        if not dep_id:
            continue
        dep_item = gis.content.get(dep_id)
        if dep_item is None:
            qa.add(SEV_WARNING, "dependent_item_missing",
                   f"Item {source.id} is referenced by {dep_id!r}, which no "
                   f"longer resolves in AGOL (deleted?) -- dependency not recorded.")
            continue
        records.append(DependencyRecord(
            source_item_id=source.id,
            source_title=source.title or "",
            dependent_item_id=dep_item.id,
            dependent_title=dep_item.title or "",
            dependent_type=dep_item.type or "",
            relationship="references"))
        _walk(gis, dep_item, records, depth + 1, max_depth, visited, qa)
