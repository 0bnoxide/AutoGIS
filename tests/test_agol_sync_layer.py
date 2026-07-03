"""Tests for core/agol/sync_layer.py — Tool 6.2 SyncAGOLFeatureLayerToGDB.

Pure-core tests (edits_where_clause, plan_sync) plus CLI tests with the AGOL
session and the fetch seam monkeypatched.  No arcgis or arcpy needed;
fetch_layer_edits / write_sync_to_gdb are ``# pragma: no cover`` seams.
"""
from datetime import date, datetime, timezone

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.agol.sync_layer import edits_where_clause, plan_sync
from autogis.core.common.qa import QACollector


# -- edits_where_clause --------------------------------------------------------

def test_where_clause_default():
    assert edits_where_clause(None, None) == "1=1"


def test_where_clause_passthrough():
    assert edits_where_clause("SiteID='S1'", None) == "SiteID='S1'"


def test_where_clause_since_only():
    expected_ms = int(datetime(2026, 7, 1, tzinfo=timezone.utc)
                      .timestamp() * 1000)
    assert edits_where_clause(None, date(2026, 7, 1)) == \
        f"EditDate > {expected_ms}"


def test_where_clause_where_and_since():
    clause = edits_where_clause("SiteID='S1'", date(2026, 7, 1))
    assert clause.startswith("(SiteID='S1') AND EditDate > ")


# -- plan_sync -------------------------------------------------------------------

_RECORDS = [
    {"GlobalID": "g1", "OBJECTID": 1, "WellStatus": "OK",
     "Shape__Area": 2.0, "Notes": "gate locked"},
    {"GlobalID": "g2", "OBJECTID": 2, "WellStatus": "DAMAGED", "Notes": None},
    {"GlobalID": None, "WellStatus": "?"},
]


def test_plan_splits_updates_and_inserts():
    plan = plan_sync(_RECORDS, {"g1"})
    assert set(plan.updates) == {"g1"}
    assert [r["GlobalID"] for r in plan.inserts] == ["g2"]
    assert plan.skipped_no_key == 1


def test_plan_missing_key_warns():
    qa = QACollector()
    plan_sync(_RECORDS, set(), qa=qa)
    assert any(r.category == "missing_key_field" for r in qa.records)
    assert any(r.category == "sync_plan_complete" for r in qa.records)


def test_plan_system_fields_excluded():
    plan = plan_sync(_RECORDS, {"g1"})
    rec = plan.updates["g1"]
    assert "OBJECTID" not in rec
    assert "Shape__Area" not in rec
    assert "OBJECTID" not in plan.field_names


def test_plan_fields_filter_keeps_key_and_named():
    plan = plan_sync(_RECORDS, set(), fields=["WellStatus"])
    assert plan.field_names == ["GlobalID", "WellStatus"]
    assert all(set(r) <= {"GlobalID", "WellStatus"} for r in plan.inserts)


def test_plan_field_names_sorted_key_first():
    plan = plan_sync(_RECORDS, set())
    assert plan.field_names == ["GlobalID", "Notes", "WellStatus"]


def test_plan_empty_records():
    plan = plan_sync([], {"g1"})
    assert plan.updates == {} and plan.inserts == []
    assert plan.field_names == ["GlobalID"]


# -- CLI: agol sync-to-gdb -------------------------------------------------------

def test_sync_to_gdb_in_help():
    result = CliRunner().invoke(autogis, ["agol", "--help"])
    assert "sync-to-gdb" in result.output


def test_gdb_and_out_csv_mutually_exclusive(tmp_path):
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--layer-url", "https://x/0",
        "--out-csv", str(tmp_path / "o.csv"),
        "--gdb", str(tmp_path / "f.gdb"), "--table", "Wells"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_requires_out_csv_or_gdb():
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--layer-url", "https://x/0"])
    assert result.exit_code != 0
    assert "out-csv" in result.output or "gdb" in result.output.lower()


def test_gdb_requires_table(tmp_path):
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--layer-url", "https://x/0",
        "--gdb", str(tmp_path / "f.gdb")])
    assert result.exit_code != 0
    assert "--table" in result.output


def test_requires_layer_url_or_item_id(tmp_path):
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--out-csv", str(tmp_path / "o.csv")])
    assert result.exit_code != 0
    assert "layer-url" in result.output or "item-id" in result.output


def test_gdb_without_arcpy_is_clean(tmp_path):
    """The guard fires before any AGOL session is built."""
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--layer-url", "https://x/0",
        "--gdb", str(tmp_path / "f.gdb"), "--table", "Wells"])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output


def test_headless_out_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile",
                        lambda profile=None: object())
    monkeypatch.setattr(
        "autogis.core.agol.sync_layer.fetch_layer_edits",
        lambda gis, **kw: [
            {"GlobalID": "g1", "OBJECTID": 1, "WellStatus": "OK"},
            {"GlobalID": "g2", "WellStatus": "DAMAGED"},
        ])
    out = tmp_path / "edits.csv"
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--layer-url", "https://x/0",
        "--out-csv", str(out)])
    assert result.exit_code == 0, result.output
    assert "Fetched 2 record(s)" in result.output
    text = out.read_text(encoding="utf-8").replace("\r", "")
    assert text.splitlines()[0] == "GlobalID,WellStatus"   # OBJECTID dropped
    assert "g1,OK" in text and "g2,DAMAGED" in text


def test_since_reaches_fetch_as_editdate_clause(tmp_path, monkeypatch):
    seen = {}

    def fake_fetch(gis, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile",
                        lambda profile=None: object())
    monkeypatch.setattr("autogis.core.agol.sync_layer.fetch_layer_edits",
                        fake_fetch)
    result = CliRunner().invoke(autogis, [
        "agol", "sync-to-gdb", "--layer-url", "https://x/0",
        "--since", "2026-07-01", "--out-csv", str(tmp_path / "o.csv")])
    assert result.exit_code == 0, result.output
    assert seen["where"].startswith("EditDate > ")
