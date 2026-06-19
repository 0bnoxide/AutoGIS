import pytest
from autogis.core.models import HarvestConfig, AttachmentResult, RunSummary


def test_layer_ref_prefers_url():
    cfg = HarvestConfig(item_id="abc", url="http://x/0", directory="d",
                         group_template="{S}", filename_template="{OBJECTID}")
    assert cfg.layer_ref() == "http://x/0"


def test_layer_ref_falls_back_to_item_id():
    cfg = HarvestConfig(item_id="abc", url=None, directory="d",
                        group_template="{S}", filename_template="{OBJECTID}")
    assert cfg.layer_ref() == "abc"


def test_layer_ref_raises_when_both_missing():
    cfg = HarvestConfig(item_id=None, url=None, directory="d",
                        group_template="{S}", filename_template="{OBJECTID}")
    with pytest.raises(ValueError):
        cfg.layer_ref()


def test_config_defaults():
    cfg = HarvestConfig(item_id="a", url=None, directory="d",
                        group_template="{S}", filename_template="{OBJECTID}")
    assert cfg.where == "1=1"
    assert cfg.skip_existing is True
    assert cfg.incremental is False
    assert cfg.retries == 3
    assert cfg.backoff_seconds == 2


def test_run_summary_record():
    s = RunSummary()
    s.record("downloaded")
    s.record("skipped")
    s.record("failed")
    s.record("failed")
    assert (s.downloaded, s.skipped, s.failed) == (1, 1, 2)


def test_run_summary_rejects_unknown_status():
    s = RunSummary()
    with pytest.raises(ValueError):
        s.record("bogus")


def test_attachment_result_fields():
    r = AttachmentResult(objectid=5, attachment_id=2, original_name="p.jpg",
                         saved_path="/tmp/p.jpg", size=10, status="downloaded")
    assert r.status == "downloaded"
    assert r.error is None
