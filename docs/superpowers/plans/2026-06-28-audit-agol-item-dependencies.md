# AuditAGOLItemDependencies (HYBRID) — Implementation Plan

**Goal:** Add `agol audit-dependencies` CLI command that, given an AGOL item ID, finds
all items that reference or depend on it (web maps using a feature service, apps using a
web map, etc.). Outputs a dependency tree to CSV or JSON. Enables safe decommission /
rename workflows — teams can see what breaks before making changes.

**Architecture:** New module `autogis/core/agol/audit_dependencies.py` using the
`arcgis` SDK (`GIS`, `Item.dependent_upon()`). HYBRID runtime (needs arcgis but not
arcpy). Walks dependencies up to a configurable depth. All core logic is arcpy-free.

**Tech stack:** Python 3.14, click, arcgis SDK, stdlib csv/json/dataclasses, pytest.
Reuses: `agol_from_profile` (`runtime/sessions.py`), `QACollector` (`common/qa.py`).

## Global constraints

- `autogis/core/agol/` imports without arcpy. arcgis SDK may or may not be present
  at import time — guard with try/except ImportError at function call site (not at
  module level) to keep the module importable.
- Command name exactly `audit-dependencies` under `agol` group.
  Register as `Runtime.HYBRID`.
- `DependencyRecord` dataclass: `source_item_id`, `source_title`, `dependent_item_id`,
  `dependent_title`, `dependent_type`, `relationship` ("references").
- Depth-first walk, max_depth configurable (default 2). Visited set prevents cycles.
- A failed item.dependent_upon() call emits SEV_WARNING and continues.

---

### Task 1: Core module `audit_dependencies.py` + unit tests

**Files:**
- Create: `autogis/core/agol/audit_dependencies.py`
- Create: `tests/test_audit_dependencies.py`

**Complete code — `audit_dependencies.py`:**

```python
"""Audit AGOL item dependency graph (HYBRID)."""
from __future__ import annotations
import dataclasses
from typing import List, Optional, Set
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
        dep_info = source.dependent_upon()
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
            continue
        records.append(DependencyRecord(
            source_item_id=source.id,
            source_title=source.title or "",
            dependent_item_id=dep_item.id,
            dependent_title=dep_item.title or "",
            dependent_type=dep_item.type or "",
            relationship="references"))
        _walk(gis, dep_item, records, depth + 1, max_depth, visited, qa)
```

**Complete code — `tests/test_audit_dependencies.py`:**

```python
"""Unit tests for audit_item_dependencies using mock GIS."""
from autogis.core.common.qa import QACollector
from autogis.core.agol.audit_dependencies import (
    audit_item_dependencies, DependencyRecord)


class _MockItem:
    def __init__(self, item_id, title, item_type="Feature Service", deps=None):
        self.id = item_id
        self.title = title
        self.type = item_type
        self._deps = deps or []

    def dependent_upon(self):
        return {"list": [{"id": d.id} for d in self._deps]}


class _MockGIS:
    def __init__(self, items):
        self._items = {i.id: i for i in items}

    class _content:
        pass

    def __init__(self, items):
        self._items = {i.id: i for i in items}
        self.content = type("Content", (), {"get": lambda self_, iid: items_dict.get(iid)})()
        items_dict = self._items
        self.content.get = lambda iid: self._items.get(iid)


def _gis(*items):
    items_dict = {i.id: i for i in items}
    class FakeContent:
        def get(self, iid):
            return items_dict.get(iid)
    class FakeGIS:
        content = FakeContent()
    return FakeGIS()


def test_no_dependencies():
    svc = _MockItem("SVC1", "Service A")
    gis = _gis(svc)
    qa = QACollector()
    records = audit_item_dependencies(gis, "SVC1", qa=qa, max_depth=2)
    assert records == []
    assert any(r.category == "audit_complete" for r in qa.records)


def test_item_not_found():
    gis = _gis()
    qa = QACollector()
    records = audit_item_dependencies(gis, "MISSING", qa=qa)
    assert records == []
    assert any(r.category == "item_not_found" for r in qa.records)


def test_single_dependency():
    svc = _MockItem("SVC1", "Service A")
    wm = _MockItem("WM1", "Web Map", "Web Map", deps=[svc])
    gis = _gis(svc, wm)
    qa = QACollector()
    records = audit_item_dependencies(gis, "WM1", qa=qa, max_depth=2)
    assert len(records) == 1
    assert records[0].dependent_item_id == "SVC1"
    assert records[0].relationship == "references"


def test_max_depth_respected():
    a = _MockItem("A", "A")
    b = _MockItem("B", "B", deps=[a])
    c = _MockItem("C", "C", deps=[b])
    gis = _gis(a, b, c)
    qa = QACollector()
    # depth=1: only C->B, not C->B->A
    records = audit_item_dependencies(gis, "C", qa=qa, max_depth=1)
    assert len(records) == 1
    assert records[0].dependent_item_id == "B"


def test_dependency_record_fields():
    svc = _MockItem("SVC1", "Service A", "Feature Service")
    wm = _MockItem("WM1", "Web Map", "Web Map", deps=[svc])
    gis = _gis(svc, wm)
    qa = QACollector()
    records = audit_item_dependencies(gis, "WM1", qa=qa)
    r = records[0]
    assert r.source_item_id == "WM1"
    assert r.source_title == "Web Map"
    assert r.dependent_type == "Feature Service"
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `audit_dependencies.py`.
- [ ] Run unit tests, verify pass (all mock-based; no AGOL connection needed).

---

### Task 2: Wire CLI + register

**CLI command (add to the `agol` group in `cli.py`):**

```python
@agol.command("audit-dependencies")
@click.option("--item-id", required=True, help="AGOL item ID to audit.")
@click.option("--profile", default=None, help="ArcGIS profile name.")
@click.option("--max-depth", type=int, default=2, show_default=True)
@click.option("--output", default=None, type=click.Path(),
              help="Output CSV path (default: print to stdout).")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]),
              default="csv", show_default=True)
def audit_dependencies_cmd(item_id, profile, max_depth, output, fmt):
    """List AGOL items that depend on a given item (HYBRID)."""
    import csv as _csv, json as _json, dataclasses, io
    from autogis.runtime.sessions import agol_from_profile
    from autogis.core.common.qa import QACollector
    from autogis.core.agol.audit_dependencies import (
        audit_item_dependencies, DependencyRecord)

    gis = agol_from_profile(profile)
    qa = QACollector()
    records = audit_item_dependencies(gis, item_id, qa=qa, max_depth=max_depth)

    if fmt == "json":
        payload = [dataclasses.asdict(r) for r in records]
        content = _json.dumps(payload, indent=2)
    else:
        buf = io.StringIO()
        cols = [f.name for f in dataclasses.fields(DependencyRecord)]
        w = _csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))
        content = buf.getvalue()

    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Written: {output}  ({len(records)} record(s))")
    else:
        click.echo(content)
    for rec in qa.records:
        if rec.severity in ("ERROR", "WARNING"):
            click.echo(f"[{rec.severity}] {rec.message}")
```

**`capabilities.py` entry:** `"audit-dependencies": Runtime.HYBRID`

**Steps:**
- [ ] Write failing CLI test in `tests/test_cli_audit_dependencies.py` using monkeypatched GIS.
- [ ] Add command, update capabilities.
- [ ] Run `python -m pytest -q`, verify all pass.
- [ ] Commit: `feat(agol): audit-dependencies — AGOL item dependency audit (HYBRID)`
