"""Arcpy-free tests for register_drone_flight.py."""
from datetime import date

import yaml

from autogis.core.common.qa import QACollector
from autogis.core.common.schema.drone import DroneFlight
from autogis.core.envmon.register_drone_flight import (
    load_flight_yaml,
    validate_flight_record,
)

_YAML = """\
flight_id: "H281-2026-F01"
project_id: "H281"
site_id: "H281"
flight_date: "2026-06-14"
pilot: "Alice Smith"
drone_model: "DJI Phantom 4 RTK"
sensor: "RGB"
flight_altitude_m: 60.0
overlap_forward_pct: 80
overlap_side_pct: 70
gcp_used: true
checkpoint_count: 5
processing_software: "Agisoft Metashape"
output_crs: "EPSG:26917"
vertical_datum: "NAVD88"
orthomosaic_path: "C:/data/H281_ortho.tif"
dsm_path: "C:/data/H281_DSM.tif"
qa_status: "PASS"
"""


def _write(tmp_path, text):
    p = tmp_path / "flight.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_flight_yaml_returns_schema_dataclass(tmp_path):
    rec = load_flight_yaml(_write(tmp_path, _YAML))
    assert isinstance(rec, DroneFlight)
    assert rec.flight_id == "H281-2026-F01"
    assert rec.gcp_used is True
    assert rec.checkpoint_count == 5


def test_load_flight_yaml_parses_date(tmp_path):
    rec = load_flight_yaml(_write(tmp_path, _YAML))
    assert rec.flight_date == date(2026, 6, 14)


def test_load_flight_yaml_unquoted_date(tmp_path):
    """PyYAML parses an unquoted ISO date to datetime.date; loader must accept it."""
    text = _YAML.replace('flight_date: "2026-06-14"', "flight_date: 2026-06-14")
    rec = load_flight_yaml(_write(tmp_path, text))
    assert rec.flight_date == date(2026, 6, 14)


def test_validate_flight_required_fields(tmp_path):
    rec = load_flight_yaml(_write(tmp_path, _YAML))
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_validate_flight_missing_pilot(tmp_path):
    data = yaml.safe_load(_YAML)
    data.pop("pilot")
    rec = load_flight_yaml(_write(tmp_path, yaml.dump(data)))
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert any(r.category == "missing_required_field" for r in qa.records)


def test_validate_flight_negative_altitude(tmp_path):
    data = yaml.safe_load(_YAML)
    data["flight_altitude_m"] = -10.0
    rec = load_flight_yaml(_write(tmp_path, yaml.dump(data)))
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert any(r.category == "invalid_altitude" for r in qa.records)


def test_load_flight_yaml_defaults(tmp_path):
    minimal = "flight_id: F01\nsite_id: H281\nflight_date: 2026-06-14\n"
    rec = load_flight_yaml(_write(tmp_path, minimal))
    assert rec.gcp_used is False
    assert rec.checkpoint_count == 0
    assert rec.qa_status == "pending"


def test_validate_flight_missing_date(tmp_path):
    data = yaml.safe_load(_YAML)
    data.pop("flight_date")
    rec = load_flight_yaml(_write(tmp_path, yaml.dump(data)))
    qa = QACollector()
    validate_flight_record(rec, qa)
    assert any(r.category == "missing_required_field"
               and "flight_date" in r.message for r in qa.records)


def test_module_imports_without_arcpy():
    import importlib
    mod = importlib.import_module("autogis.core.envmon.register_drone_flight")
    assert hasattr(mod, "load_flight_yaml")
    assert hasattr(mod, "validate_flight_record")
