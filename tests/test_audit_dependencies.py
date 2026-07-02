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

    def dependent_to(self):
        return {"list": [{"id": d.id} for d in self._deps]}


class _RaisingItem(_MockItem):
    """Mock item whose dependent_to() always raises (simulates AGOL API error)."""
    def dependent_to(self):
        raise RuntimeError("AGOL API error")


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
    assert any(r.severity == "ERROR" for r in qa.records)


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


def test_cycle_prevented_by_visited_set():
    # A depends on B, B depends on A: without the visited set this recurses forever.
    a = _MockItem("A", "A")
    b = _MockItem("B", "B", deps=[a])
    a._deps = [b]
    gis = _gis(a, b)
    qa = QACollector()
    records = audit_item_dependencies(gis, "A", qa=qa, max_depth=5)
    assert len(records) == 2
    assert {r.dependent_item_id for r in records} == {"A", "B"}


def test_dependent_to_error_emits_warning_and_continues_for_siblings():
    # ROOT depends on both a BAD item (dependent_to raises) and a GOOD item
    # that has its own downstream dependency. The BAD failure must not abort
    # the walk of the GOOD sibling.
    svc = _MockItem("SVC1", "Service A")
    good = _MockItem("GOOD", "Good Item", deps=[svc])
    bad = _RaisingItem("BAD", "Bad Item")
    root = _MockItem("ROOT", "Root", deps=[bad, good])
    gis = _gis(svc, good, bad, root)
    qa = QACollector()

    records = audit_item_dependencies(gis, "ROOT", qa=qa, max_depth=2)

    assert any(r.category == "dependency_walk_error" for r in qa.records)
    assert any(r.severity == "WARNING" for r in qa.records)
    dependent_ids = {r.dependent_item_id for r in records}
    assert dependent_ids == {"BAD", "GOOD", "SVC1"}


def test_deleted_dependent_item_emits_warning_not_silent_drop():
    # ROOT is referenced by an item id that no longer resolves (deleted item).
    # This must surface as a warning, not vanish silently.
    root = _MockItem("ROOT", "Root")
    root._deps = [_MockItem("GONE", "Gone")]  # id present in dep list, not in gis
    gis = _gis(root)  # note: "GONE" intentionally absent from the fake GIS
    qa = QACollector()

    records = audit_item_dependencies(gis, "ROOT", qa=qa, max_depth=2)

    assert records == []
    assert any(r.category == "dependent_item_missing" for r in qa.records)
    assert any(r.severity == "WARNING" for r in qa.records)
