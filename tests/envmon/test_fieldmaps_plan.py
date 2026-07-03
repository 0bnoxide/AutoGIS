"""Tests for Tool 7.1: arcpy-free Field Maps plan derivation, mocked-arcpy
provisioning, and the build-fieldmaps CLI."""
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.fieldmaps_plan import (
    FieldDef, LayerPlan, plan_fieldmaps_project, provision_fieldmaps_layers)

SITE = {"site_id": "H281", "monitoring_wells_fc": "MonitoringWells"}


def _layer(plans, name):
    return next(p for p in plans if p.name == name)


# --- plan_fieldmaps_project (arcpy-free) ---

def test_plan_returns_six_canonical_layers():
    assert [p.name for p in plan_fieldmaps_project(SITE)] == [
        "MonitoringWells", "SampleStatus", "WaterLevels",
        "AccessNotes", "PhotoPoints", "IssueFlags"]


def test_wells_layer_carries_editable_visit_fields_with_71b_names():
    wells = _layer(plan_fieldmaps_project(SITE), "MonitoringWells")
    names = [f.name for f in wells.fields]
    # Names match RouteSurvey123Submission's Survey123Field defaults,
    # not the 2026-06-28 spec's prose (Sampler / DTW / SampleDate).
    for expected in ("Sampled", "SamplingDate", "SampledBy", "COCNumber",
                     "Matrix", "DepthToWater_ft", "PurgeVolume",
                     "AccessIssue", "WellCondition", "PhotoRequired",
                     "Notes"):
        assert expected in names, expected
    for stale in ("Sampler", "DTW", "SampleDate"):
        assert stale not in names, stale


def test_well_identity_fields_are_not_editable():
    wells = _layer(plan_fieldmaps_project(SITE), "MonitoringWells")
    by = {f.name: f for f in wells.fields}
    assert not by["WellID"].editable
    assert not by["SiteID"].editable
    assert by["Sampled"].editable


def test_field_types_and_domains():
    wells = _layer(plan_fieldmaps_project(SITE), "MonitoringWells")
    by = {f.name: f for f in wells.fields}
    assert by["Sampled"] == FieldDef("Sampled", "short", domain="YesNo")
    assert by["SamplingDate"].field_type == "date"
    assert by["DepthToWater_ft"].field_type == "double"
    assert by["WellCondition"].domain == "WellCondition"
    assert by["PhotoRequired"].domain == "YesNo"


def test_photo_points_are_points_and_status_tables_have_no_geometry():
    plans = plan_fieldmaps_project(SITE)
    assert _layer(plans, "PhotoPoints").geometry == "point"
    assert _layer(plans, "SampleStatus").geometry == "none"
    assert _layer(plans, "WaterLevels").geometry == "none"


def test_analyte_groups_add_status_fields():
    cfg = dict(SITE, analyte_groups={
        "Volatile Organic Compounds": ["Benzene"],
        "Inorganic Indicator Parameters": ["Iron"]})
    status = _layer(plan_fieldmaps_project(cfg), "SampleStatus")
    names = [f.name for f in status.fields]
    assert "Status_Volatile_Organic_Compounds" in names
    assert "Status_Inorganic_Indicator_Parameters" in names


def test_wells_layer_name_comes_from_site_config():
    plans = plan_fieldmaps_project({"monitoring_wells_fc": "Wells_H281"})
    assert plans[0].name == "Wells_H281"


# --- provision_fieldmaps_layers (arcpy mocked, same pattern as
#     test_layout_manager) ---

def _mock_arcpy(existing=(), fields=(), domains=()):
    arcpy = MagicMock()
    arcpy.Exists.side_effect = lambda p: Path(p).name in existing
    arcpy.ListFields.side_effect = lambda t: [
        types.SimpleNamespace(name=n) for n in fields]
    arcpy.da.ListDomains.return_value = [
        types.SimpleNamespace(name=n) for n in domains]
    return arcpy


def test_provision_creates_layers_fields_and_domains(tmp_path):
    plans = plan_fieldmaps_project(SITE)
    arcpy = _mock_arcpy()
    qa = QACollector()
    with patch("autogis.runtime.sessions.arcpy_env", return_value=arcpy):
        n = provision_fieldmaps_layers(tmp_path / "x.gdb", plans, qa)
    assert n == 6
    assert arcpy.management.CreateFeatureclass.call_count == 4
    assert arcpy.management.CreateTable.call_count == 2
    created_domains = [c.args[1] for c
                       in arcpy.management.CreateDomain.call_args_list]
    assert sorted(created_domains) == ["WellCondition", "YesNo"]
    # every planned field is added on a fresh GDB
    total_fields = sum(len(p.fields) for p in plans)
    assert arcpy.management.AddField.call_count == total_fields


def test_provision_refresh_adds_only_missing_fields(tmp_path):
    plans = [LayerPlan("MonitoringWells", "point",
                       [FieldDef("WellID", "text", editable=False),
                        FieldDef("Notes", "text")])]
    arcpy = _mock_arcpy(existing={"MonitoringWells"}, fields=("WellID",),
                        domains=("YesNo", "WellCondition"))
    qa = QACollector()
    with patch("autogis.runtime.sessions.arcpy_env", return_value=arcpy):
        provision_fieldmaps_layers(tmp_path / "x.gdb", plans, qa)
    arcpy.management.CreateFeatureclass.assert_not_called()
    arcpy.management.CreateDomain.assert_not_called()
    added = [c.args[1] for c in arcpy.management.AddField.call_args_list]
    assert added == ["Notes"]


def test_provision_without_srs_warns_unknown_crs(tmp_path):
    arcpy = _mock_arcpy()
    qa = QACollector()
    with patch("autogis.runtime.sessions.arcpy_env", return_value=arcpy):
        provision_fieldmaps_layers(
            tmp_path / "x.gdb", plan_fieldmaps_project(SITE), qa)
    assert any(r.category == "unknown_crs" for r in qa.records)


# --- CLI wiring ---

def _site_yaml(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text("site_id: H281\n", encoding="utf-8")
    return p


def test_build_fieldmaps_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-fieldmaps" in result.output


def test_build_fieldmaps_dry_run_is_headless(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "build-fieldmaps",
        "--site-config", str(_site_yaml(tmp_path)), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "MonitoringWells" in result.output
    assert "SamplingDate" in result.output


def test_build_fieldmaps_event_config_adds_status_fields(tmp_path):
    event = tmp_path / "event.yaml"
    event.write_text("analyte_groups:\n  VOC:\n    - Benzene\n",
                     encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-fieldmaps",
        "--site-config", str(_site_yaml(tmp_path)),
        "--event-config", str(event), "--dry-run"])
    assert "Status_VOC" in result.output


def test_build_fieldmaps_gdb_without_arcpy_is_clean_guard(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "build-fieldmaps",
        "--site-config", str(_site_yaml(tmp_path)),
        "--gdb", str(tmp_path / "x.gdb")])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output


def test_build_fieldmaps_requires_gdb_or_dry_run(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "build-fieldmaps",
        "--site-config", str(_site_yaml(tmp_path))])
    assert result.exit_code != 0
    assert "--dry-run" in result.output
