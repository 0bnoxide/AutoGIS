"""CLI tests for envmon register-drone-flight command."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis

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
