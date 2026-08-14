import hashlib
import json as _json
import math
import os
from datetime import datetime, timezone

import pytest
from autogis.core.models import HarvestConfig
from autogis.core import harvester


class FakeFeature:
    def __init__(self, attributes, geometry=None):
        self.attributes = attributes
        self.geometry = geometry


class FakeQueryResult:
    def __init__(self, features, spatial_reference=None):
        self.features = features
        self.spatial_reference = spatial_reference


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
        self.last_return_geometry = return_geometry
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
    assert layer.last_return_geometry is True


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


def _fake_gis(layers=(), tables=()):
    class Item:
        pass
    item = Item()
    item.layers = list(layers)
    item.tables = list(tables)
    # Real AGOL sublayers carry their own REST id on .properties.id; assign
    # the combined layers-then-tables position as that id here (unless a
    # test already set one explicitly), matching production's id-based
    # lookup instead of raw positional indexing.
    for position, sub in enumerate(item.layers + item.tables):
        sub.properties.setdefault("id", position)

    class FakeContent:
        def get(self, item_id):
            return item

    class FakeGIS:
        content = FakeContent()

    return FakeGIS()


def test_resolve_layer_rejects_no_attachments(tmp_path):
    layer = FakeLayer([], {}, props={"hasAttachments": False})
    gis = _fake_gis(layers=[layer])
    with pytest.raises(ValueError):
        harvester.resolve_layer(gis, _cfg(tmp_path))


def test_resolve_layer_defaults_to_first_sublayer(tmp_path):
    first = FakeLayer([], {})
    gis = _fake_gis(layers=[first, FakeLayer([], {})])
    assert harvester.resolve_layer(gis, _cfg(tmp_path)) is first


def test_resolve_layer_index_reaches_table_in_combined_list(tmp_path):
    # layer_index counts across layers-then-tables combined (AGOL
    # ?sublayer=N numbering): 2 layers + tables means index 3 = tables[1].
    target = FakeLayer([], {})
    gis = _fake_gis(
        layers=[FakeLayer([], {}), FakeLayer([], {})],
        tables=[FakeLayer([], {}), target],
    )
    cfg = _cfg(tmp_path, layer_index=3)
    assert harvester.resolve_layer(gis, cfg) is target


def test_resolve_layer_index_out_of_range_raises_config_error(tmp_path):
    from autogis.core.common.config import ConfigError
    gis = _fake_gis(layers=[FakeLayer([], {})])  # only sublayer id 0 exists
    with pytest.raises(ConfigError, match="does not match any sublayer id"):
        harvester.resolve_layer(gis, _cfg(tmp_path, layer_index=5))
    with pytest.raises(ConfigError, match="does not match any sublayer id"):
        harvester.resolve_layer(gis, _cfg(tmp_path, layer_index=-1))


def test_resolve_layer_index_matches_by_id_not_position(tmp_path):
    # Sublayer ids aren't guaranteed contiguous-from-position-0 -- a service
    # can have non-zero-based or gappy ids. Position 0 here carries id=7;
    # requesting layer_index=7 must resolve it by id, not by treating 7 as
    # an out-of-bounds position in a 1-element list.
    target = FakeLayer([], {}, props={"hasAttachments": True, "id": 7})
    gis = _fake_gis(layers=[target])
    assert harvester.resolve_layer(gis, _cfg(tmp_path, layer_index=7)) is target


def test_resolve_all_layers_returns_only_attachment_bearing_sublayers(tmp_path):
    no_attach = FakeLayer([], {}, props={"hasAttachments": False, "name": "Skip"})
    attach_layer = FakeLayer([], {}, props={"hasAttachments": True, "name": "Wells"})
    attach_table = FakeLayer([], {}, props={"hasAttachments": True, "name": "Photos"})
    gis = _fake_gis(layers=[no_attach, attach_layer], tables=[attach_table])
    result = harvester.resolve_all_layers(gis, _cfg(tmp_path))
    assert result == [attach_layer, attach_table]


def test_resolve_all_layers_raises_when_none_have_attachments(tmp_path):
    gis = _fake_gis(layers=[FakeLayer([], {}, props={"hasAttachments": False})])
    with pytest.raises(ValueError, match="no layers or tables"):
        harvester.resolve_all_layers(gis, _cfg(tmp_path))


def test_harvest_all_sublayers_downloads_into_per_sublayer_subfolders(tmp_path):
    wells = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Done"})],
        {1: [{"id": 10, "name": "a.jpg", "size": 4}]},
        props={"hasAttachments": True, "name": "Wells", "id": 0})
    photos = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Open"})],
        {1: [{"id": 20, "name": "b.jpg", "size": 5}]},
        props={"hasAttachments": True, "name": "Daily Photos", "id": 1})
    gis = _fake_gis(layers=[wells], tables=[photos])

    summary = harvester.harvest(
        gis, _cfg(tmp_path, all_sublayers=True), now_ms=1, sleep=lambda s: None)

    assert summary.downloaded == 2
    # folder = sanitize(name) + "_" + sublayer id, guaranteeing distinct
    # subfolders even if two sublayers' names sanitize to the same string.
    assert (tmp_path / "Wells_0" / "Done" / "1_a.jpg").exists()
    assert (tmp_path / "Daily_Photos_1" / "Open" / "1_b.jpg").exists()
    source_tables = {r.source_table for r in summary.results}
    assert source_tables == {"Wells", "Daily Photos"}


def test_harvest_all_sublayers_folder_disambiguates_same_sanitized_name(tmp_path):
    # Two sublayers whose names sanitize to the SAME string (sanitize() only
    # strips illegal filesystem chars -- "Photos/A" and "PhotosA" both
    # become "PhotosA") must still land in distinct subfolders -- the id
    # suffix is what actually guarantees this, not the name.
    a = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Done"})],
        {1: [{"id": 10, "name": "a.jpg", "size": 4}]},
        props={"hasAttachments": True, "name": "Photos/A", "id": 0})
    b = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Done"})],
        {1: [{"id": 20, "name": "b.jpg", "size": 5}]},
        props={"hasAttachments": True, "name": "PhotosA", "id": 1})
    gis = _fake_gis(layers=[a, b])

    summary = harvester.harvest(
        gis, _cfg(tmp_path, all_sublayers=True), now_ms=1, sleep=lambda s: None)

    assert summary.downloaded == 2
    assert (tmp_path / "PhotosA_0" / "Done" / "1_a.jpg").exists()
    assert (tmp_path / "PhotosA_1" / "Done" / "1_b.jpg").exists()


def test_harvest_all_sublayers_one_sublayer_failure_keeps_others(tmp_path):
    # A fatal error resolving/querying ONE sublayer (bad where-clause, layer-
    # level exception, ...) must not discard the manifest for sublayers
    # already processed, nor abort the ones still queued.
    class _BrokenLayer(FakeLayer):
        def query(self, where, out_fields, return_geometry):
            raise RuntimeError("layer offline")

    good_first = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Done"})],
        {1: [{"id": 10, "name": "a.jpg", "size": 4}]},
        props={"hasAttachments": True, "name": "Good", "id": 0})
    broken = _BrokenLayer([], {}, props={"hasAttachments": True, "name": "Bad", "id": 1})
    good_second = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Done"})],
        {1: [{"id": 30, "name": "c.jpg", "size": 6}]},
        props={"hasAttachments": True, "name": "AlsoGood", "id": 2})
    gis = _fake_gis(layers=[good_first, broken, good_second])

    summary = harvester.harvest(
        gis, _cfg(tmp_path, all_sublayers=True), now_ms=1, sleep=lambda s: None)

    assert summary.downloaded == 2
    assert summary.failed == 1
    assert (tmp_path / "Good_0" / "Done" / "1_a.jpg").exists()
    assert (tmp_path / "AlsoGood_2" / "Done" / "1_c.jpg").exists()
    failed = next(r for r in summary.results if r.status == "failed")
    assert failed.source_table == "Bad"
    assert "layer offline" in failed.error
    # single-sublayer mode keeps its pre-existing behavior: propagate
    assert (tmp_path / "manifest.csv").exists()


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


def test_harvest_single_sublayer_populates_source_table(tmp_path):
    # Not just the new all-sublayers path -- harvest() now names the
    # resolved sublayer once for both modes, so the pre-existing
    # single-sublayer path gets accurate provenance too (previously always
    # None; see ADR-0072's "Positive consequences").
    layer = FakeLayer(
        [FakeFeature({"OBJECTID": 1, "Status": "Done"})],
        {1: [{"id": 10, "name": "a.jpg", "size": 4}]},
        props={"hasAttachments": True, "name": "Wells"})
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert summary.results[0].source_table == "Wells"


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


def test_harvest_fills_geometry_checksum_editdate(tmp_path):
    # Web Mercator x/y computed in-test with the FORWARD projection formula;
    # the harvester implements the INVERSE — a genuine round-trip, not a
    # mirror of the implementation.
    lat, lon = 45.874, -103.487
    r_earth = 6378137.0
    x = r_earth * math.radians(lon)
    y = r_earth * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    edit_ms = int(datetime(2026, 5, 5, 14, 37, 36,
                           tzinfo=timezone.utc).timestamp() * 1000)
    features = [FakeFeature(
        {"OBJECTID": 1, "Status": "Done", "EditDate": edit_ms},
        geometry={"x": x, "y": y,
                  "spatialReference": {"wkid": 102100, "latestWkid": 3857}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing, props={
        "hasAttachments": True,
        "editFieldsInfo": {"editDateField": "EditDate"}})
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    geom = _json.loads(r.geometry)
    assert geom["lat"] == pytest.approx(45.874, abs=1e-5)
    assert geom["lon"] == pytest.approx(-103.487, abs=1e-5)
    assert r.algorithm == "sha256"
    assert r.checksum == hashlib.sha256(b"x").hexdigest()
    assert r.feature_edited_at == "2026-05-05T14:37:36+00:00"
    # geometry survives the manifest round-trip as a JSON string
    rows = _json.loads((tmp_path / "manifest.json").read_text())
    assert _json.loads(rows[0]["geometry"])["lat"] == geom["lat"]


def test_harvest_geometry_wgs84_passthrough_and_centroid(tmp_path):
    features = [FakeFeature(
        {"OBJECTID": 1, "Status": "Done"},
        geometry={"rings": [[[10.0, 40.0], [12.0, 40.0], [12.0, 42.0],
                             [10.0, 42.0], [10.0, 40.0]]],
                  "spatialReference": {"wkid": 4326}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    geom = _json.loads(summary.results[0].geometry)
    assert geom == {"lat": pytest.approx(40.8), "lon": pytest.approx(10.8)}


def test_harvest_unknown_wkid_leaves_geometry_null(tmp_path, caplog):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"},
                            geometry={"x": 1.0, "y": 2.0,
                                      "spatialReference": {"wkid": 26913}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    with caplog.at_level("WARNING"):
        summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                    now_ms=1, sleep=lambda s: None)
    assert summary.results[0].geometry is None
    assert any("spatial reference" in m for m in caplog.messages)


def test_harvest_skipped_existing_file_still_hashed(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    target = tmp_path / "Done" / "1_a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.status == "skipped"
    assert r.checksum == hashlib.sha256(b"old").hexdigest()


def test_harvest_no_geometry_attr_stays_null(tmp_path):
    # Old-style feature (no .geometry): everything still works, columns null.
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.geometry is None and r.feature_edited_at is None


def test_harvest_skip_branch_hash_failure_still_records_row(tmp_path):
    # dest exists (passes the skip_existing check) but is a directory, not a
    # file -- open(dest, "rb") inside _sha256 raises OSError, simulating an
    # AV/indexer lock or a delete-after-exists-check race. The row must
    # still be recorded (checksum null) and the manifest must still get
    # written, not abort the whole run.
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    target = tmp_path / "Done" / "1_a.jpg"
    target.mkdir(parents=True)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.status == "skipped"
    assert r.checksum is None and r.algorithm is None
    assert (tmp_path / "manifest.json").exists()


def test_harvest_malformed_geometry_leaves_geometry_null_and_continues(tmp_path):
    # A ring vertex with only 1 coordinate can't unpack as (x, y, *_) --
    # _vertices raises ValueError. Must degrade this row's geometry to null
    # rather than aborting the run (which would also strand the just-
    # downloaded file with zero manifest record).
    features = [FakeFeature(
        {"OBJECTID": 1, "Status": "Done"},
        geometry={"rings": [[[5.0]]], "spatialReference": {"wkid": 4326}})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.status == "downloaded"
    assert r.geometry is None
    assert (tmp_path / "manifest.json").exists()


def test_iso_utc_overflow_magnitude_returns_none():
    # 10**25 ms overflows the platform time_t datetime.fromtimestamp uses --
    # confirmed empirically to raise OverflowError (not OSError/ValueError,
    # which were already caught).
    assert harvester._iso_utc(10**25) is None


def test_harvest_download_hash_failure_still_downloaded(tmp_path, monkeypatch):
    # PR #497 review should-fix: a hash-time OSError right AFTER a successful
    # download (same AV-lock race the skip branch is hardened against) must
    # not demote the row to "failed" with saved_path=None -- that orphans the
    # on-disk file. The row stays "downloaded" and only loses its checksum.
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)

    def locked(path):
        raise OSError("file locked by scanner")

    monkeypatch.setattr(harvester, "_sha256", locked)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    r = summary.results[0]
    assert r.status == "downloaded" and r.disposition == "downloaded"
    assert r.checksum is None and r.algorithm is None
    assert r.saved_path is not None and os.path.exists(r.saved_path)
    assert r.error is None
