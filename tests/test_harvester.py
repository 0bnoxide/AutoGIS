import os
import pytest
from autogis.core.models import HarvestConfig
from autogis.core import harvester


class FakeFeature:
    def __init__(self, attributes):
        self.attributes = attributes


class FakeQueryResult:
    def __init__(self, features):
        self.features = features


class FakeAttachmentMgr:
    def __init__(self, listing, fail_ids=()):
        self.listing = listing          # {oid: [ {id,name,size}, ... ]}
        self.fail_ids = set(fail_ids)

    def get_list(self, oid):
        return self.listing.get(oid, [])

    def download(self, oid, attachment_id, save_path):
        if attachment_id in self.fail_ids:
            raise RuntimeError("boom")
        tmp = os.path.join(save_path, f"raw_{attachment_id}.bin")
        with open(tmp, "wb") as fh:
            fh.write(b"x")
        return tmp


class FakeProps(dict):
    __getattr__ = dict.get


class FakeLayer:
    def __init__(self, features, listing, fail_ids=(), props=None):
        self._features = features
        self.attachments = FakeAttachmentMgr(listing, fail_ids)
        self.properties = props if props is not None else {"hasAttachments": True}

    def query(self, where, out_fields, return_geometry):
        self.last_where = where
        return FakeQueryResult(self._features)


def _cfg(tmp_path, **kw):
    base = dict(item_id="x", url=None, directory=str(tmp_path),
                group_template="{Status}",
                filename_template="{OBJECTID}_{name}")
    base.update(kw)
    return HarvestConfig(**base)


def test_harvest_downloads_and_groups(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"}),
                FakeFeature({"OBJECTID": 2, "Status": "Open"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}],
               2: [{"id": 20, "name": "b.jpg", "size": 5}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=123, sleep=lambda s: None)
    assert summary.downloaded == 2
    assert (tmp_path / "Done" / "1_a.jpg").exists()
    assert (tmp_path / "Open" / "2_b.jpg").exists()
    assert (tmp_path / "manifest.csv").exists()
    assert (tmp_path / "manifest.json").exists()


def test_harvest_skips_existing(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    target = tmp_path / "Done" / "1_a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert summary.skipped == 1
    assert summary.downloaded == 0
    assert target.read_bytes() == b"old"


def test_harvest_records_failure_and_continues(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"}),
                FakeFeature({"OBJECTID": 2, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}],
               2: [{"id": 20, "name": "b.jpg", "size": 5}]}
    layer = FakeLayer(features, listing, fail_ids=(10,))
    summary = harvester.harvest(None, _cfg(tmp_path, retries=1), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert summary.failed == 1
    assert summary.downloaded == 1
    assert (tmp_path / "Done" / "2_b.jpg").exists()


def test_resolve_layer_rejects_no_attachments(tmp_path):
    layer = FakeLayer([], {}, props={"hasAttachments": False})

    class FakeContent:
        def get(self, item_id):
            class Item:
                layers = [layer]
            return Item()

    class FakeGIS:
        content = FakeContent()

    with pytest.raises(ValueError):
        harvester.resolve_layer(FakeGIS(), _cfg(tmp_path))


def test_incremental_writes_state_and_filters(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    props = {"hasAttachments": True,
             "editorTrackingInfo": {"enableEditorTracking": True}}
    layer = FakeLayer(features, listing, props=props)
    from autogis.core import state
    state.write_last_run(str(tmp_path), 500)
    summary = harvester.harvest(None, _cfg(tmp_path, incremental=True),
                                layer=layer, now_ms=999, sleep=lambda s: None)
    assert "EditDate > 500" in layer.last_where
    assert state.read_last_run(str(tmp_path)) == 999
    assert summary.downloaded == 1


def test_incremental_without_tracking_raises(tmp_path):
    layer = FakeLayer([], {}, props={"hasAttachments": True})
    with pytest.raises(ValueError):
        harvester.harvest(None, _cfg(tmp_path, incremental=True),
                          layer=layer, now_ms=1, sleep=lambda s: None)


def test_harvest_results_list_populated(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"}),
                FakeFeature({"OBJECTID": 2, "Status": "Open"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}],
               2: [{"id": 20, "name": "b.jpg", "size": 5}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert len(summary.results) == 2
    statuses = {r.status for r in summary.results}
    assert statuses == {"downloaded"}


def test_harvest_skips_existing_results_list(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    target = tmp_path / "Done" / "1_a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert len(summary.results) == 1
    assert summary.results[0].status == "skipped"


def test_harvest_failure_results_list(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"}),
                FakeFeature({"OBJECTID": 2, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}],
               2: [{"id": 20, "name": "b.jpg", "size": 5}]}
    layer = FakeLayer(features, listing, fail_ids=(10,))
    summary = harvester.harvest(None, _cfg(tmp_path, retries=1), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    statuses = {r.status for r in summary.results}
    assert "failed" in statuses
    assert "downloaded" in statuses


def test_incremental_does_not_advance_state_on_failure(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    props = {"hasAttachments": True,
             "editorTrackingInfo": {"enableEditorTracking": True}}
    layer = FakeLayer(features, listing, fail_ids=(10,), props=props)
    from autogis.core import state
    state.write_last_run(str(tmp_path), 500)
    summary = harvester.harvest(None, _cfg(tmp_path, incremental=True),
                                layer=layer, now_ms=999, sleep=lambda s: None)
    assert summary.failed == 1
    assert state.read_last_run(str(tmp_path)) == 500
