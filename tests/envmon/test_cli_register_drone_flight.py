"""CLI tests for envmon register-drone-flight command."""
import dataclasses

import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.schema.drone import DroneFlight
from autogis.core.envmon.register_drone_flight import (
    _FLIGHT_REQUIRED, flight_yaml_template)

_YAML = """\
flight_id: "H281-2026-F01"
project_id: "H281"
site_id: "H281"
flight_date: "2026-06-14"
pilot: "Alice Smith"
drone_model: "DJI Phantom 4 RTK"
sensor: "RGB"
flight_altitude_m: 60.0
gcp_used: true
checkpoint_count: 5
qa_status: "PASS"
"""

_YAML_BAD = """\
flight_id: "F02"
site_id: "H281"
flight_date: "2026-06-14"
flight_altitude_m: 60.0
"""


def _write(tmp_path, text):
    p = tmp_path / "flight.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_register_drone_flight_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "register-drone-flight" in result.output


def test_register_drone_flight_dry_run_valid(tmp_path):
    p = _write(tmp_path, _YAML)
    result = CliRunner().invoke(autogis, [
        "envmon", "register-drone-flight", str(p),
        "--gdb", str(tmp_path / "fake.gdb"), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "Status: PASS" in result.output


def test_register_drone_flight_missing_fields_fails(tmp_path):
    p = _write(tmp_path, _YAML_BAD)
    result = CliRunner().invoke(autogis, [
        "envmon", "register-drone-flight", str(p),
        "--gdb", str(tmp_path / "fake.gdb"), "--dry-run",
    ])
    assert result.exit_code != 0
    assert "missing_required_field" in result.output


def test_register_drone_flight_write_without_arcpy_is_clean(tmp_path):
    """Valid YAML + no --dry-run hits the guard; arcpy absent → clean error."""
    p = _write(tmp_path, _YAML)
    result = CliRunner().invoke(autogis, [
        "envmon", "register-drone-flight", str(p),
        "--gdb", str(tmp_path / "fake.gdb"),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output


# --- new-flight-yaml scaffold -------------------------------------------------

def test_flight_yaml_template_keys_match_droneflight():
    """Drift guard: the scaffold must emit exactly the keys load_flight_yaml
    reads -- i.e. every DroneFlight field, no more, no less."""
    assert set(flight_yaml_template()) == {
        f.name for f in dataclasses.fields(DroneFlight)}


def test_flight_yaml_template_required_first_and_empty():
    tpl = flight_yaml_template()
    assert list(tpl)[:len(_FLIGHT_REQUIRED)] == list(_FLIGHT_REQUIRED)
    assert all(tpl[k] == "" for k in _FLIGHT_REQUIRED)  # -> dry-run flags them


def test_flight_yaml_template_applies_overrides():
    tpl = flight_yaml_template({"site_id": "H281", "gcp_used": True})
    assert tpl["site_id"] == "H281"
    assert tpl["gcp_used"] is True


def test_new_flight_yaml_writes_all_keys(tmp_path):
    out = tmp_path / "flight.yaml"
    result = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out)])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(data) == {f.name for f in dataclasses.fields(DroneFlight)}


def test_new_flight_yaml_set_prefills(tmp_path):
    out = tmp_path / "flight.yaml"
    result = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out),
        "--set", "site_id=H281_Glasgow"])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["site_id"] == "H281_Glasgow"


def test_new_flight_yaml_rejects_bad_set(tmp_path):
    out = tmp_path / "flight.yaml"
    # unknown field
    r1 = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out),
        "--set", "nope=x"])
    assert r1.exit_code != 0 and "unknown field" in r1.output
    # missing '='
    r2 = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out), "--set", "site_id"])
    assert r2.exit_code != 0 and "KEY=VALUE" in r2.output


def test_new_flight_yaml_refuses_to_overwrite(tmp_path):
    """A rerun must not clobber a filled inventory; --overwrite is the escape."""
    out = tmp_path / "flight.yaml"
    out.write_text("flight_id: KEEPME\nsite_id: H281\n", encoding="utf-8")
    r = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out)])
    assert r.exit_code != 0 and "already exists" in r.output
    assert "KEEPME" in out.read_text(encoding="utf-8")  # left untouched
    # --overwrite is the explicit escape hatch
    r2 = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out), "--overwrite"])
    assert r2.exit_code == 0, r2.output
    assert "KEEPME" not in out.read_text(encoding="utf-8")


def test_new_flight_yaml_roundtrips_into_register_dry_run(tmp_path):
    """A template with the required fields filled must validate clean through
    register-drone-flight --dry-run; an unfilled one must report missing."""
    out = tmp_path / "flight.yaml"
    filled = CliRunner().invoke(autogis, [
        "envmon", "new-flight-yaml", "--output", str(out),
        "--set", "flight_id=F1", "--set", "site_id=H281",
        "--set", "flight_date=2026-07-21", "--set", "pilot=A. Smith",
        "--set", "drone_model=DJI Mavic 3", "--set", "sensor=RGB"])
    assert filled.exit_code == 0, filled.output
    ok = CliRunner().invoke(autogis, [
        "envmon", "register-drone-flight", str(out),
        "--gdb", str(tmp_path / "fake.gdb"), "--dry-run"])
    assert ok.exit_code == 0, ok.output
    assert "Status: PASS" in ok.output

    # bare template (required empty) -> dry-run flags the missing fields
    bare = tmp_path / "bare.yaml"
    CliRunner().invoke(autogis, ["envmon", "new-flight-yaml",
                                 "--output", str(bare)])
    miss = CliRunner().invoke(autogis, [
        "envmon", "register-drone-flight", str(bare),
        "--gdb", str(tmp_path / "fake.gdb"), "--dry-run"])
    assert miss.exit_code != 0 and "missing_required_field" in miss.output
