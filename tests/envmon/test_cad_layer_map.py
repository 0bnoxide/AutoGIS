import builtins

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import SEV_ERROR
from autogis.core.envmon.cad_layer_map import (
    load_cad_mapping, resolve_cad_plan, validate_crs, write_mapping_report,
    write_projection_note)


def _no_arcpy_monkeypatch(monkeypatch):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "arcpy":
            raise ModuleNotFoundError("No module named 'arcpy'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)


def test_resolve_cad_plan_maps_selected_layers():
    plan = resolve_cad_plan(
        ["wells", "contours"],
        {"wells": {"cad_layer": "V-WELL"}, "contours": {"cad_layer": "C-TOPO-MAJR"}},
        crs="EPSG:2256",
    )
    assert {m.gis_layer: m.cad_layer for m in plan.mappings} == {
        "wells": "V-WELL", "contours": "C-TOPO-MAJR"}
    assert plan.unmapped == []
    assert plan.qa.has_blocking() is False


def test_unmapped_layer_is_blocking_error():
    plan = resolve_cad_plan(["orphan"], {}, crs="EPSG:2256")
    assert plan.unmapped == ["orphan"]
    assert any(r.severity == SEV_ERROR and r.category == "unmapped_layers"
               for r in plan.qa.records)
    assert plan.qa.has_blocking() is True


def test_color_and_linetype_pass_through():
    plan = resolve_cad_plan(
        ["wells", "contours"],
        {"wells": {"cad_layer": "V-WELL", "color": 3, "linetype": "DASHED"},
         "contours": {"cad_layer": "C-TOPO-MAJR"}},
        crs="EPSG:2256",
    )
    by_layer = {m.gis_layer: m for m in plan.mappings}
    assert by_layer["wells"].color == 3
    assert by_layer["wells"].linetype == "DASHED"
    assert by_layer["contours"].color is None
    assert by_layer["contours"].linetype is None


def test_missing_crs_is_qa_error():
    plan = resolve_cad_plan(["wells"], {"wells": {"cad_layer": "V-WELL"}}, crs="")
    assert any(r.severity == SEV_ERROR and r.category == "missing_crs"
               for r in plan.qa.records)
    assert plan.qa.has_blocking() is True


def test_config_layer_not_selected_is_ignored():
    plan = resolve_cad_plan(
        ["wells"],
        {"wells": {"cad_layer": "V-WELL"}, "contours": {"cad_layer": "C-TOPO-MAJR"},
         "extra": {"cad_layer": "X"}},
        crs="EPSG:2256",
    )
    assert len(plan.mappings) == 1
    assert plan.unmapped == []
    assert plan.qa.records == []


def test_load_cad_mapping_yaml(tmp_path):
    path = tmp_path / "map.yaml"
    path.write_text("wells:\n  cad_layer: V-WELL\n  color: 3\n", encoding="utf-8")
    mapping = load_cad_mapping(path)
    assert mapping == {"wells": {"cad_layer": "V-WELL", "color": 3}}


def test_write_projection_note_records_crs(tmp_path):
    out = write_projection_note("EPSG:2256", tmp_path / "note.txt")
    assert out.exists()
    assert "EPSG:2256" in out.read_text(encoding="utf-8")


def test_validate_crs_blank_is_error():
    from autogis.core.common.qa import QACollector
    qa = QACollector()
    assert validate_crs("", qa=qa) is False
    assert validate_crs("EPSG:2256", qa=qa) is True


def test_write_mapping_report(tmp_path):
    plan = resolve_cad_plan(
        ["wells", "contours"],
        {"wells": {"cad_layer": "V-WELL", "color": 3, "linetype": "DASHED"},
         "contours": {"cad_layer": "C-TOPO-MAJR"}},
        crs="EPSG:2256",
    )
    out = write_mapping_report(plan, tmp_path / "mapping_report.csv")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "gis_layer,cad_layer,color,linetype"
    assert "wells,V-WELL,3,DASHED" in lines
    assert "contours,C-TOPO-MAJR,," in lines


def test_write_mapping_report_preserves_zero_color(tmp_path):
    plan = resolve_cad_plan(
        ["wells"], {"wells": {"cad_layer": "V-WELL", "color": 0}},
        crs="EPSG:2256")
    out = write_mapping_report(plan, tmp_path / "mapping_report.csv")
    assert "wells,V-WELL,0," in out.read_text(encoding="utf-8").splitlines()


def test_build_cad_package_guard_headless(monkeypatch, tmp_path):
    _no_arcpy_monkeypatch(monkeypatch)
    layers = tmp_path / "layers.txt"
    layers.write_text("wells\n", encoding="utf-8")
    mapping = tmp_path / "map.yaml"
    mapping.write_text("wells:\n  cad_layer: V-WELL\n", encoding="utf-8")

    result = CliRunner().invoke(
        autogis,
        ["envmon", "build-cad-package",
         "--layers", str(layers), "--mapping", str(mapping), "--crs", "EPSG:2256"],
    )
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower()
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_find_prj_conflicts_detects_all_forms(tmp_path):
    """<stem>.prj/.wld, esri_cad.prj/.wld, and *.uprj/*.uwld each move
    Export To CAD output (issue #238)."""
    from autogis.core.envmon.cad_layer_map import find_prj_conflicts

    out = tmp_path / "site.dwg"
    assert find_prj_conflicts(out) == []

    expected = {"site.prj", "site.wld", "esri_cad.prj", "esri_cad.wld",
                "statewide.uprj", "statewide.uwld"}
    for name in expected:
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "other.prj").write_text("x", encoding="utf-8")  # unrelated stem
    (tmp_path / "other.wld").write_text("x", encoding="utf-8")  # unrelated stem

    assert {f.name for f in find_prj_conflicts(out)} == expected
