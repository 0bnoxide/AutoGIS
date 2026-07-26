"""Survey123 Phase 2 incremental submission sync (survey_sync.py, ADR-0116).

All arcgis-free: the live seam (``fetch_item_pulls``) is exercised via fakes
and monkeypatching only; the pure planner, checkpoint semantics, staging
writers, and the CLI wiring are covered headlessly.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters import cli
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon import survey_sync as ss
from autogis.core.envmon.normalize_survey123 import (
    load_survey123_csv_submissions,
)
from autogis.core.envmon.survey_sync import (
    LayerPull,
    SubmissionEnvelope,
    payload_hash,
    plan_layer_envelopes,
    read_checkpoint,
    sync_item,
    write_checkpoint,
    write_envelopes_jsonl,
    write_submissions_csv,
)


def _ms(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


def _feat(gid, edit_ms, create_ms=None, geometry=None, **attrs):
    a = {"globalid": gid, "EditDate": edit_ms,
         "CreationDate": edit_ms if create_ms is None else create_ms}
    a.update(attrs)
    return {"attributes": a, "geometry": geometry}


def _pull(**kw) -> LayerPull:
    base = dict(layer_id=0, name="survey")
    base.update(kw)
    return LayerPull(**base)


def _plan(pull, *, watermark=None, known=(), qa=None):
    return plan_layer_envelopes(
        pull, item_id="ITEM1", watermark_ms=watermark,
        known_global_ids=known, source={"mode": "sync"},
        qa=qa if qa is not None else QACollector())


# -- payload hash --------------------------------------------------------------

def test_payload_hash_is_key_order_independent():
    a = payload_hash({"x": 1, "y": "2"}, {"rings": [[0, 0]]})
    b = payload_hash({"y": "2", "x": 1}, {"rings": [[0, 0]]})
    assert a == b
    assert a != payload_hash({"x": 1, "y": "3"}, {"rings": [[0, 0]]})


# -- planner -------------------------------------------------------------------

def test_first_pull_is_all_adds_and_seeds_checkpoint_state():
    pull = _pull(features=[_feat("g1", 1000), _feat("g2", 2000)],
                 all_global_ids=["g1", "g2"])
    envelopes, state = _plan(pull)
    assert [e.operation for e in envelopes] == ["add", "add"]
    assert envelopes[0].payload_hash and envelopes[0].global_id == "g1"
    assert state == {"name": "survey", "last_edit_ms": 2000,
                     "known_global_ids": ["g1", "g2"]}


def test_add_vs_update_classified_by_creation_time():
    pull = _pull(
        features=[_feat("new", 6000, create_ms=5500),      # created in window
                  _feat("old", 7000, create_ms=100)],       # edited only
        all_global_ids=["new", "old"])
    envelopes, state = _plan(pull, watermark=5000, known=["old"])
    assert {e.global_id: e.operation for e in envelopes} == {
        "new": "add", "old": "update"}
    assert state["last_edit_ms"] == 7000


def test_deletes_come_from_known_ids_missing_in_sweep():
    pull = _pull(features=[], all_global_ids=["keep"])
    envelopes, state = _plan(pull, watermark=1000, known=["keep", "gone"])
    assert [(e.operation, e.global_id) for e in envelopes] == [
        ("delete", "gone")]
    assert envelopes[0].payload_hash == "" and envelopes[0].attributes == {}
    assert state["known_global_ids"] == ["keep"]
    assert state["last_edit_ms"] == 1000  # deletes never move the watermark


def test_feature_without_global_id_is_skipped_with_qa_warning():
    qa = QACollector()
    pull = _pull(features=[{"attributes": {"EditDate": 1}, "geometry": None}],
                 all_global_ids=[])
    envelopes, _ = _plan(pull, qa=qa)
    assert envelopes == []
    assert any(r.severity == SEV_WARNING and r.category == "missing_global_id"
               for r in qa.records)


def test_repeat_table_records_carry_repeat_path_and_parent():
    pull = _pull(layer_id=1, name="purge_readings", is_table=True,
                 parent_global_id_field="parentglobalid",
                 features=[_feat("r1", 100, parentglobalid="g1")],
                 all_global_ids=["r1"])
    envelopes, _ = _plan(pull)
    assert envelopes[0].repeat_path == "purge_readings"
    assert envelopes[0].parent_global_id == "g1"


def test_attachment_metadata_rides_the_envelope():
    meta = [{"id": 1, "name": "photo.jpg", "size": 9,
             "content_type": "image/jpeg"}]
    pull = _pull(features=[_feat("g1", 100)], all_global_ids=["g1"],
                 attachments={"g1": meta})
    envelopes, _ = _plan(pull)
    assert envelopes[0].attachments == meta


# -- sync_item / checkpoint ----------------------------------------------------

def test_replay_never_regresses_a_stored_watermark():
    checkpoint = {"version": 1, "item_id": "ITEM1",
                  "layers": {"0": {"name": "survey", "last_edit_ms": 9000,
                                   "known_global_ids": ["g1"]}}}
    pulls = [_pull(features=[_feat("g1", 5000)], all_global_ids=["g1"])]
    _, new_cp = sync_item(pulls, checkpoint, item_id="ITEM1",
                          pulled_at_ms=1, mode="replay",
                          replay_since_ms=4000, qa=QACollector())
    assert new_cp["layers"]["0"]["last_edit_ms"] == 9000


def test_checkpoint_roundtrip_is_atomic(tmp_path):
    cp = {"version": 1, "item_id": "I", "layers": {}}
    write_checkpoint(tmp_path, cp)
    assert read_checkpoint(tmp_path) == cp
    assert not list(tmp_path.glob("*.tmp"))
    assert read_checkpoint(tmp_path / "elsewhere") is None


# -- staging writers -----------------------------------------------------------

def test_envelopes_jsonl_round_trips(tmp_path):
    envelopes, _ = _plan(_pull(features=[_feat("g1", 100, WellID="MW-1")],
                               all_global_ids=["g1"]))
    path = tmp_path / "envelopes.jsonl"
    write_envelopes_jsonl(envelopes, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["global_id"] == "g1" and rec["attributes"]["WellID"] == "MW-1"


def test_submissions_csv_keeps_parent_adds_updates_only(tmp_path):
    envelopes = [
        SubmissionEnvelope("I", 0, "survey", "g1", "add", 1,
                           attributes={"WellID": "MW-1"}),
        SubmissionEnvelope("I", 0, "survey", "g2", "delete", None),
        SubmissionEnvelope("I", 1, "purge", "r1", "add", 1,
                           repeat_path="purge",
                           attributes={"Reading": "1"}),
    ]
    path = tmp_path / "subs.csv"
    assert write_submissions_csv(envelopes, path) == 1
    rows = path.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "WellID" and rows[1] == "MW-1"
    assert write_submissions_csv([], tmp_path / "empty.csv") == 0
    assert (tmp_path / "empty.csv").read_text(encoding="utf-8") == ""


def test_date_fields_render_midnight_as_date_else_full_timestamp(tmp_path):
    midnight = _ms(2026, 7, 1)
    with_time = _ms(2026, 7, 1, 7, 30)
    envelopes = [SubmissionEnvelope(
        "I", 0, "survey", "g1", "add", 1,
        attributes={"SamplingDate": midnight, "Synced": with_time})]
    path = tmp_path / "subs.csv"
    write_submissions_csv(envelopes, path,
                          date_fields={"SamplingDate", "Synced"})
    body = path.read_text(encoding="utf-8").splitlines()[1]
    assert "2026-07-01," in body or body.startswith("2026-07-01")
    assert "2026-07-01 07:30:00" in body


def test_staging_csv_feeds_the_existing_normalizer(tmp_path):
    pull = _pull(
        features=[_feat("g1", 100, WellID="MW-1",
                        SamplingDate=_ms(2026, 7, 1), Matrix="GW",
                        SampledBy="tech", COCNumber="C-1",
                        DepthToWater_ft="12.5", QAFlags="")],
        all_global_ids=["g1"], date_fields=["SamplingDate"])
    envelopes, _ = _plan(pull)
    path = tmp_path / "subs.csv"
    write_submissions_csv(envelopes, path, date_fields=set(pull.date_fields))

    qa = QACollector()
    water_levels, samples = load_survey123_csv_submissions(
        path, "SITE1", "B1", qa)
    assert not any(r.severity == SEV_ERROR for r in qa.records)
    assert len(samples) == 1 and len(water_levels) == 1
    assert samples[0]["SampleID"].startswith("MW-1-20260701")
    assert water_levels[0]["DTW_ft"] == 12.5


# -- CLI -----------------------------------------------------------------------

def _fake_pulls(features, all_gids, **kw):
    def fetch(gis, item_id, *, checkpoint=None, replay_since_ms=None,
              include_attachments=True):
        return [_pull(features=features, all_global_ids=all_gids, **kw)]
    return fetch


@pytest.fixture()
def live_fakes(monkeypatch):
    monkeypatch.setattr(cli, "agol_from_profile", lambda profile=None: object())
    return monkeypatch


def _invoke(args):
    return CliRunner().invoke(cli.autogis, ["envmon", "sync-survey123", *args])


def test_cli_missing_arcgis_fails_before_network_with_install_hint(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec",
        lambda name, *a: None if name == "arcgis" else real(name, *a))
    called = []
    monkeypatch.setattr(cli, "agol_from_profile",
                        lambda profile=None: called.append(1))
    result = _invoke(["--item-id", "I", "--out", "unused"])
    assert result.exit_code != 0
    assert 'pip install "autogis[survey123]"' in result.output
    assert not called  # failed before any live/network step


def test_cli_sync_writes_staging_then_checkpoint(tmp_path, live_fakes):
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000, WellID="MW-1")], ["g1"]))
    out = tmp_path / "stage"
    result = _invoke(["--item-id", "I", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert len(list(out.glob("envelopes_*.jsonl"))) == 1
    assert len(list(out.glob("submissions_*.csv"))) == 1
    cp = read_checkpoint(out)
    assert cp["layers"]["0"]["last_edit_ms"] == 1000
    assert cp["layers"]["0"]["known_global_ids"] == ["g1"]


def test_cli_repeated_clean_run_is_up_to_date_no_new_artifacts(
        tmp_path, live_fakes):
    out = tmp_path / "stage"
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000)], ["g1"]))
    assert _invoke(["--item-id", "I", "--out", str(out)]).exit_code == 0
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls([], ["g1"]))
    result = _invoke(["--item-id", "I", "--out", str(out)])
    assert result.exit_code == 0 and "Up to date" in result.output
    assert len(list(out.glob("envelopes_*.jsonl"))) == 1  # no duplicates


def test_cli_replay_does_not_advance_checkpoint(tmp_path, live_fakes):
    out = tmp_path / "stage"
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000)], ["g1"]))
    assert _invoke(["--item-id", "I", "--out", str(out)]).exit_code == 0
    before = (out / ss.CHECKPOINT_FILENAME).read_text(encoding="utf-8")
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 900)], ["g1"]))
    result = _invoke(["--item-id", "I", "--out", str(out),
                      "--since", "2026-01-01"])
    assert result.exit_code == 0, result.output
    assert "checkpoint not advanced" in result.output
    assert (out / ss.CHECKPOINT_FILENAME).read_text(encoding="utf-8") == before


def test_cli_dry_run_writes_nothing(tmp_path, live_fakes):
    out = tmp_path / "stage"
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000)], ["g1"]))
    result = _invoke(["--item-id", "I", "--out", str(out), "--dry-run"])
    assert result.exit_code == 0 and "[dry-run]" in result.output
    assert not out.exists() or not list(out.iterdir())


def test_cli_rejects_checkpoint_from_a_different_survey(tmp_path, live_fakes):
    # review round 1: a foreign checkpoint would silently apply the other
    # survey's watermarks and fabricate deletes from its known-ID set
    out = tmp_path / "stage"
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000)], ["g1"]))
    assert _invoke(["--item-id", "SURVEY-A", "--out", str(out)]).exit_code == 0
    result = _invoke(["--item-id", "SURVEY-B", "--out", str(out)])
    assert result.exit_code != 0
    assert "SURVEY-A" in result.output and "SURVEY-B" in result.output


def test_cli_empty_replay_window_says_checkpoint_not_advanced(
        tmp_path, live_fakes):
    out = tmp_path / "stage"
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000)], ["g1"]))
    assert _invoke(["--item-id", "I", "--out", str(out)]).exit_code == 0
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls([], ["g1"]))
    result = _invoke(["--item-id", "I", "--out", str(out),
                      "--since", "2026-01-01"])
    assert result.exit_code == 0
    assert "checkpoint not advanced" in result.output


def test_cli_interrupted_staging_write_leaves_checkpoint_unwritten(
        tmp_path, live_fakes):
    out = tmp_path / "stage"
    live_fakes.setattr(ss, "fetch_item_pulls", _fake_pulls(
        [_feat("g1", 1000)], ["g1"]))

    def boom(envelopes, path):
        raise RuntimeError("disk full")

    live_fakes.setattr(ss, "write_envelopes_jsonl", boom)
    result = _invoke(["--item-id", "I", "--out", str(out)])
    assert result.exit_code != 0
    assert read_checkpoint(out) is None  # next run re-pulls the same window
