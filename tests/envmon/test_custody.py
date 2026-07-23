"""Tests for the Phase 6 chain-of-custody lifecycle — arcpy-free.

Covers the core state machine, reconciliation, plan bridge, and persistence,
plus an end-to-end CLI lifecycle (generate → advance → reconcile) proving a
real event reconciles from sampling plan through laboratory receipt with a full
audit trail and stable exit codes.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.envmon import custody
from autogis.core.envmon.custody import (
    DRAFT, GENERATED, RELEASED, LAB_RECEIVED, RESULTS_RECEIVED,
    RECONCILED, EXCEPTION, CustodyError,
)

T0 = datetime(2026, 7, 23, 9, 0, 0)


# ── core state machine ─────────────────────────────────────────────────────

def _rec(sample_ids=("S1", "S2", "S3")):
    return custody.new_record(
        "COC-001", event_name="EVT", site_id="SITE", event_date="2026-07-23",
        lab_name="LabCo", sample_ids=list(sample_ids), at=T0, actor="planner")


def test_new_record_starts_draft_with_audit():
    rec = _rec()
    assert rec.state == DRAFT
    assert len(rec.audit) == 1
    assert rec.audit[0].to_state == DRAFT
    assert rec.audit[0].details["sample_count"] == 3


def test_legal_forward_path():
    rec = _rec()
    custody.transition(rec, GENERATED, actor="a", at=T0)
    custody.transition(rec, RELEASED, actor="courier", at=T0, details={"carrier": "FedEx"})
    custody.transition(rec, LAB_RECEIVED, actor="lab", at=T0,
                       details={"temperature_c": 4.0, "temperature_ok": True})
    custody.transition(rec, RESULTS_RECEIVED, actor="lab", at=T0)
    custody.transition(rec, RECONCILED, actor="rev", at=T0)
    assert rec.state == RECONCILED
    assert [e.to_state for e in rec.audit] == [
        DRAFT, GENERATED, RELEASED, LAB_RECEIVED, RESULTS_RECEIVED, RECONCILED]


def test_illegal_skip_rejected():
    rec = _rec()
    with pytest.raises(CustodyError):
        custody.transition(rec, RELEASED, actor="a", at=T0)  # skips generated
    assert rec.state == DRAFT  # unchanged
    assert len(rec.audit) == 1


def test_terminal_states_have_no_exits():
    for terminal in (RECONCILED, EXCEPTION):
        assert custody._ALLOWED[terminal] == set()


def test_exception_reachable_from_each_active_state():
    for start, reach in [
        (DRAFT, True), (GENERATED, True), (RELEASED, True),
        (LAB_RECEIVED, True), (RESULTS_RECEIVED, True),
    ]:
        assert (EXCEPTION in custody._ALLOWED[start]) is reach


def test_actor_required():
    rec = _rec()
    with pytest.raises(CustodyError):
        custody.transition(rec, GENERATED, actor="   ", at=T0)


def test_unknown_state_rejected():
    rec = _rec()
    with pytest.raises(CustodyError):
        custody.transition(rec, "shipped", actor="a", at=T0)


# ── reconciliation ─────────────────────────────────────────────────────────

def test_reconcile_clean():
    r = custody.reconcile(_rec(), ["S1", "S2", "S3"])
    assert r.clean
    assert r.matched == ["S1", "S2", "S3"] and not r.missing and not r.extra


def test_reconcile_missing_and_extra():
    r = custody.reconcile(_rec(), ["S1", "S2", "S9"])
    assert not r.clean
    assert r.matched == ["S1", "S2"]
    assert r.missing == ["S3"]     # planned, not received
    assert r.extra == ["S9"]       # received, not planned


def test_reconcile_does_not_mutate():
    rec = _rec()
    custody.reconcile(rec, ["S1"])
    assert rec.state == DRAFT and len(rec.audit) == 1


# ── plan bridge ────────────────────────────────────────────────────────────

def test_records_from_plan_groups_by_coc():
    from autogis.core.envmon.create_sampling_event import (
        ExpectedSampleRow, SamplingEventPlan)

    def _row(coc, sid):
        return ExpectedSampleRow(
            sample_id=sid, location_id="L", event_date="2026-07-23", matrix="GW",
            analyte_group="VOCs", sample_type="Regular", container_type="",
            preservative="", hold_time_hr=0, bottle_count=1,
            coc_number=coc, assigned_to="a")

    plan = SamplingEventPlan(
        event_name="EVT", event_date="2026-07-23", site_id="SITE",
        site_name="Site", lab_name="LabCo", coc_prefix="P", run_id="r",
        expected_samples=[_row("P-001", "A"), _row("P-001", "B"), _row("P-002", "C")],
        crew_assignments=[])
    recs = custody.records_from_plan(plan, at=T0, actor="planner")
    assert [r.coc_number for r in recs] == ["P-001", "P-002"]
    assert recs[0].sample_ids == ["A", "B"]
    assert all(r.state == DRAFT for r in recs)


# ── persistence ────────────────────────────────────────────────────────────

def test_store_round_trip(tmp_path):
    rec = _rec()
    custody.transition(rec, GENERATED, actor="a", at=T0)
    path = tmp_path / "EVT_custody.json"
    custody.save_store(path, {rec.coc_number: rec})
    back = custody.load_store(path)
    assert back[rec.coc_number].state == GENERATED
    assert back[rec.coc_number].sample_ids == ["S1", "S2", "S3"]
    assert len(back[rec.coc_number].audit) == 2


def test_load_missing_store_is_empty(tmp_path):
    assert custody.load_store(tmp_path / "nope.json") == {}


def test_load_corrupt_store_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(CustodyError):
        custody.load_store(p)


# ── CLI end-to-end lifecycle ────────────────────────────────────────────────

def _write_json(path, data):
    Path(path).write_text(json.dumps(data), encoding="utf-8")


def _reference_event(tmp_path):
    """Sanitized reference event: 2 wells, 1 analyte group, no field dups."""
    site = tmp_path / "site.json"
    _write_json(site, {
        "site_id": "H281", "site_name": "H281 Glasgow", "project_number": "P-001",
        "address": "1 Test St", "city": "Glasgow", "state": "MT",
        "coordinate_system": "NAD83 / UTM Zone 12N", "default_gdb": "H281.gdb",
        "default_aprx_template": "template.aprx",
        "monitoring_wells_fc": "MonitoringWells", "soil_borings_fc": "SoilBorings",
        "site_boundary_fc": "SiteBoundary"})
    event = tmp_path / "event.json"
    _write_json(event, {
        "event_name": "2026-Q2", "event_date": "2026-07-15",
        "coc_prefix": "H281-COC", "lab_name": "TestAmerica",
        "matrices": ["GW"], "location_ids": ["MW-1", "MW-2"],
        "crew_list": ["Alice Smith"], "dup_frequency": 0,
        "analyte_groups": {"VOCs": ["Benzene"]},
        "group_sampling": {"VOCs": {"container": "40mL VOA", "preservative": "HCl",
                                    "hold_time_hr": 14, "bottles": 1}},
    })
    analytes = tmp_path / "analytes.json"
    _write_json(analytes, {"analytes": {
        "Benzene": {"abbreviation": "B", "display_order": 10,
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    return site, event, analytes


def _generate(tmp_path):
    site, event, analytes = _reference_event(tmp_path)
    store = tmp_path / "custody.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "coc", "generate", "--site", str(site), "--event", str(event),
        "--analytes", str(analytes), "--store", str(store), "--by", "planner"])
    assert res.exit_code == 0, res.output
    return store


def test_coc_group_in_help():
    res = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "coc" in res.output


def test_generate_creates_records_at_generated(tmp_path):
    store = _generate(tmp_path)
    data = custody.load_store(store)
    # 2 wells → 2 COC numbers, each with 1 sample
    assert len(data) == 2
    for rec in data.values():
        assert rec.state == GENERATED
        assert len(rec.sample_ids) == 1
        # created (draft) + draft→generated
        assert [e.to_state for e in rec.audit] == [DRAFT, GENERATED]


def test_full_lifecycle_reconcile_clean(tmp_path):
    store = _generate(tmp_path)
    data = custody.load_store(store)
    coc = sorted(data)[0]
    planned = data[coc].sample_ids

    run = lambda *a: CliRunner().invoke(autogis, ["envmon", "coc", *a])
    assert run("advance", "--store", str(store), "--coc", coc, "--to", RELEASED,
               "--by", "courier", "--set", "carrier=FedEx").exit_code == 0
    assert run("advance", "--store", str(store), "--coc", coc, "--to", LAB_RECEIVED,
               "--by", "lab", "--set", "temperature_c=4.0",
               "--set", "temperature_ok=true").exit_code == 0

    res = run("reconcile", "--store", str(store), "--coc", coc, "--by", "rev",
              "--received-ids", ",".join(planned))
    assert res.exit_code == 0, res.output
    rec = custody.load_store(store)[coc]
    assert rec.state == RECONCILED
    # temperature detail coerced to float/bool, carrier recorded
    lab_entry = next(e for e in rec.audit if e.to_state == LAB_RECEIVED)
    assert lab_entry.details["temperature_c"] == 4.0
    assert lab_entry.details["temperature_ok"] is True


def test_reconcile_discrepancy_routes_to_exception_exit_2(tmp_path):
    store = _generate(tmp_path)
    data = custody.load_store(store)
    coc = sorted(data)[0]

    run = lambda *a: CliRunner().invoke(autogis, ["envmon", "coc", *a])
    run("advance", "--store", str(store), "--coc", coc, "--to", RELEASED, "--by", "c")
    run("advance", "--store", str(store), "--coc", coc, "--to", LAB_RECEIVED, "--by", "l")

    # lab received a bogus ID and none of the planned ones → missing + extra
    res = run("reconcile", "--store", str(store), "--coc", coc, "--by", "rev",
              "--received-ids", "BOGUS-1")
    assert res.exit_code == 2, res.output
    assert "missing" in res.output.lower()
    rec = custody.load_store(store)[coc]
    assert rec.state == EXCEPTION
    exc_entry = rec.audit[-1]
    assert exc_entry.details["extra"] == ["BOGUS-1"]
    assert exc_entry.details["missing"] == sorted(data[coc].sample_ids)


def test_advance_all_flag(tmp_path):
    store = _generate(tmp_path)
    res = CliRunner().invoke(autogis, [
        "envmon", "coc", "advance", "--store", str(store), "--to", RELEASED,
        "--all", "--by", "courier"])
    assert res.exit_code == 0
    assert all(r.state == RELEASED for r in custody.load_store(store).values())


def test_advance_illegal_transition_errors(tmp_path):
    store = _generate(tmp_path)
    coc = sorted(custody.load_store(store))[0]
    # generated → results_received skips released + lab_received
    res = CliRunner().invoke(autogis, [
        "envmon", "coc", "advance", "--store", str(store), "--coc", coc,
        "--to", RESULTS_RECEIVED, "--by", "x"])
    assert res.exit_code != 0
    assert "Illegal transition" in res.output


def test_reconcile_received_file(tmp_path):
    store = _generate(tmp_path)
    data = custody.load_store(store)
    coc = sorted(data)[0]
    run = lambda *a: CliRunner().invoke(autogis, ["envmon", "coc", *a])
    run("advance", "--store", str(store), "--coc", coc, "--to", RELEASED, "--by", "c")
    run("advance", "--store", str(store), "--coc", coc, "--to", LAB_RECEIVED, "--by", "l")
    rf = tmp_path / "received.txt"
    rf.write_text("\n".join(data[coc].sample_ids) + "\n", encoding="utf-8")
    res = run("reconcile", "--store", str(store), "--coc", coc, "--by", "rev",
              "--received-file", str(rf))
    assert res.exit_code == 0, res.output


def test_status_lists_states(tmp_path):
    store = _generate(tmp_path)
    res = CliRunner().invoke(autogis, ["envmon", "coc", "status", "--store", str(store)])
    assert res.exit_code == 0
    assert "generated" in res.output
    assert "COC(s)." in res.output
