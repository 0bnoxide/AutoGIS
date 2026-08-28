from autogis.core.common.qa import QACollector
from autogis.core.common.reporting import Reporter
from autogis.core.harvest.models import AttachmentResult


def test_result_carries_disposition_and_reserved_fields():
    r = AttachmentResult(objectid=1, attachment_id=2, original_name="a.pdf",
                         saved_path="x", size=3, status="downloaded",
                         disposition="downloaded")
    assert r.disposition == "downloaded"
    assert r.checksum is None and r.geometry is None
    assert r.source_table is None and r.relationship_id is None


def test_record_result_records():
    rep = Reporter(QACollector())
    assert rep.record_result("r1") == "r1"
    assert rep.results == ["r1"]


def test_reporter_cancel_hook():
    flag = {"stop": False}
    rep = Reporter(QACollector(), cancel=lambda: flag["stop"])
    assert rep.cancelled() is False
    flag["stop"] = True
    assert rep.cancelled() is True
