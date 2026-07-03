"""CLI smoke tests for envmon create-sampling-event — arcpy-free."""
import json
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis


# ── helpers ───────────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_site(tmp_path: Path) -> Path:
    p = tmp_path / "site.json"
    _write_json(p, {
        "site_id": "H281",
        "site_name": "H281 Glasgow",
        "project_number": "P-001",
        "address": "1 Test St",
        "city": "Glasgow",
        "state": "MT",
        "coordinate_system": "NAD83 / UTM Zone 12N",
        "default_gdb": "H281.gdb",
        "default_aprx_template": "template.aprx",
        "monitoring_wells_fc": "MonitoringWells",
        "soil_borings_fc": "SoilBorings",
        "site_boundary_fc": "SiteBoundary",
    })
    return p


def _minimal_event(tmp_path: Path) -> Path:
    p = tmp_path / "event.json"
    _write_json(p, {
        "event_name": "2026-Q2",
        "event_date": "2026-07-15",
        "coc_prefix": "H281-COC",
        "lab_name": "TestAmerica",
        "matrices": ["GW"],
        "location_ids": ["MW-1", "MW-2"],
        "crew_list": ["Alice Smith"],
        "dup_frequency": 0,
        "analyte_groups": {"VOCs": ["Benzene"]},
        "group_sampling": {
            "VOCs": {"container": "40mL VOA", "preservative": "HCl",
                     "hold_time_hr": 14, "bottles": 1}
        },
    })
    return p


def _minimal_analytes(tmp_path: Path) -> Path:
    p = tmp_path / "analytes.json"
    _write_json(p, {
        "analytes": {
            "Benzene": {"abbreviation": "B", "display_order": 10,
                        "default_units_by_matrix": {"GW": "ug/L"}}
        }
    })
    return p


# ── tests ─────────────────────────────────────────────────────────────────

def test_command_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "create-sampling-event" in result.output


def test_create_sampling_event_exit_zero(tmp_path):
    site = _minimal_site(tmp_path)
    event = _minimal_event(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(event),
        "--analytes", str(analytes),
        "--out-dir", str(out_dir),
    ])
    assert result.exit_code == 0, result.output


def test_create_sampling_event_writes_workbook(tmp_path):
    site = _minimal_site(tmp_path)
    event = _minimal_event(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    out_dir = tmp_path / "out"
    CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(event),
        "--analytes", str(analytes),
        "--out-dir", str(out_dir),
    ])
    xlsx_files = list(out_dir.glob("*.xlsx"))
    assert len(xlsx_files) == 1
    assert xlsx_files[0].name == "H281_2026-Q2_sampling_plan.xlsx"


def test_create_sampling_event_echoes_path(tmp_path):
    site = _minimal_site(tmp_path)
    event = _minimal_event(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(event),
        "--analytes", str(analytes),
        "--out-dir", str(out_dir),
    ])
    assert "sampling_plan.xlsx" in result.output


def test_missing_location_ids_exits_nonzero(tmp_path):
    site = _minimal_site(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    bad_event = tmp_path / "bad_event.json"
    _write_json(bad_event, {
        "event_name": "2026-Q2",
        "event_date": "2026-07-15",
        "coc_prefix": "H281-COC",
        "lab_name": "TestAmerica",
        "matrices": ["GW"],
        "location_ids": [],   # empty — should fail
        "crew_list": ["Alice Smith"],
        "dup_frequency": 0,
        "analyte_groups": {"VOCs": ["Benzene"]},
        "group_sampling": {},
    })
    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(bad_event),
        "--analytes", str(analytes),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0


def test_help_text_shows_required_options():
    result = CliRunner().invoke(autogis,
                                ["envmon", "create-sampling-event", "--help"])
    assert result.exit_code == 0
    assert "--site" in result.output
    assert "--event" in result.output
    assert "--analytes" in result.output
    assert "--out-dir" in result.output
    assert "Tool 2.7" in result.output
