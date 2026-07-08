"""Tests for feature-code-mapped RTK survey CSV/GeoJSON/LandXML export."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from autogis.core.common.qa import QACollector
from autogis.core.envmon.export_survey_cad import (
    export_survey_to_cad_gis,
    group_points_by_layer,
    load_feature_code_map,
    write_layer_csv,
    write_layer_geojson,
    write_layer_landxml,
)
from autogis.core.envmon.import_rtk_survey import RTKPoint


def _pt(point_id, feature_code="", description=""):
    return RTKPoint(
        point_id=point_id, northing=2000.0, easting=1000.0, elevation_ft=50.0,
        feature_code=feature_code, description=description,
    )


def test_group_points_by_mapped_layer():
    qa = QACollector()
    points = [_pt("MW-1", "MW"), _pt("GCP-1", "GCP"), _pt("MW-2", "MW")]
    layers = group_points_by_layer(
        points, {"MW": "MonitoringWells", "GCP": "DroneControlPoints"}, qa=qa)
    assert set(layers) == {"MonitoringWells", "DroneControlPoints"}
    assert len(layers["MonitoringWells"]) == 2
    assert len(layers["DroneControlPoints"]) == 1


def test_unmapped_code_routes_to_default_and_warns():
    qa = QACollector()
    points = [_pt("X-1", "XYZ")]
    layers = group_points_by_layer(points, {"MW": "MonitoringWells"}, qa=qa)
    assert "Miscellaneous" in layers
    assert any(r.category == "unmapped_feature_codes" for r in qa.records)


def test_configured_default_overrides_miscellaneous():
    qa = QACollector()
    points = [_pt("X-1", "XYZ")]
    layers = group_points_by_layer(
        points, {"MW": "MonitoringWells", "default": "Other"}, qa=qa)
    assert "Other" in layers
    assert "Miscellaneous" not in layers


def test_blank_feature_code_routes_to_default():
    qa = QACollector()
    points = [_pt("X-1", "")]
    layers = group_points_by_layer(points, {"MW": "MonitoringWells"}, qa=qa)
    assert "Miscellaneous" in layers
    # blank codes are not "unmapped" (nothing to map)
    assert not any(r.category == "unmapped_feature_codes" for r in qa.records)


def test_write_layer_csv(tmp_path):
    out = tmp_path / "MonitoringWells.csv"
    write_layer_csv([_pt("MW-1", "MW")], out)
    text = out.read_text(encoding="utf-8")
    assert "MW-1" in text
    assert "1000.0" in text  # easting -> x


def test_write_layer_geojson(tmp_path):
    out = tmp_path / "MonitoringWells.geojson"
    write_layer_geojson([_pt("MW-1", "MW")], out)
    fc = json.loads(out.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["geometry"]["coordinates"] == [1000.0, 2000.0, 50.0]


def test_write_layer_landxml(tmp_path):
    out = tmp_path / "MonitoringWells.xml"
    write_layer_landxml([_pt("MW-1", "MW", "well head")], out)
    root = ET.parse(out).getroot()
    ns = {"lx": "http://www.landxml.org/schema/LandXML-1.2"}
    points = root.findall("lx:CgPoints/lx:CgPoint", ns)
    assert len(points) == 1
    pt = points[0]
    assert pt.get("name") == "MW-1"
    assert pt.get("code") == "MW"
    assert pt.get("desc") == "well head"
    assert pt.text.split() == ["2000.0", "1000.0", "50.0"]


def test_export_with_landxml_flag(tmp_path):
    qa = QACollector()
    output_dir = tmp_path / "out"
    export_survey_to_cad_gis(
        [_pt("MW-1", "MW")], {"MW": "MonitoringWells"}, output_dir,
        write_landxml=True, qa=qa,
    )
    assert (output_dir / "MonitoringWells.xml").exists()


def test_load_feature_code_map(tmp_path):
    path = tmp_path / "map.yaml"
    path.write_text("MW: MonitoringWells\nGCP: DroneControlPoints\n", encoding="utf-8")
    mapping = load_feature_code_map(path)
    assert mapping == {"MW": "MonitoringWells", "GCP": "DroneControlPoints"}


def test_export_survey_to_cad_gis_writes_manifest(tmp_path):
    qa = QACollector()
    points = [_pt("MW-1", "MW"), _pt("GCP-1", "GCP")]
    output_dir = tmp_path / "out"
    manifest = export_survey_to_cad_gis(
        points, {"MW": "MonitoringWells", "GCP": "DroneControlPoints"},
        output_dir, qa=qa,
    )
    assert {m.layer_name for m in manifest} == {"MonitoringWells", "DroneControlPoints"}
    assert (output_dir / "MonitoringWells.csv").exists()
    assert (output_dir / "manifest.json").exists()
    manifest_data = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest_data) == 2


def test_export_with_geojson_flag(tmp_path):
    qa = QACollector()
    output_dir = tmp_path / "out"
    export_survey_to_cad_gis(
        [_pt("MW-1", "MW")], {"MW": "MonitoringWells"}, output_dir,
        write_geojson=True, qa=qa,
    )
    assert (output_dir / "MonitoringWells.geojson").exists()


def test_export_empty_points(tmp_path):
    qa = QACollector()
    manifest = export_survey_to_cad_gis([], {}, tmp_path / "out", qa=qa)
    assert manifest == []
    assert any(r.category == "no_points" for r in qa.records)


def test_malicious_layer_name_cannot_escape_output_dir(tmp_path):
    """A layer name containing '../' must not write outside output_dir."""
    qa = QACollector()
    output_dir = tmp_path / "out"
    points = [_pt("X-1", "EVIL")]
    manifest = export_survey_to_cad_gis(
        points, {"EVIL": "../../etc/pwn"}, output_dir, qa=qa)

    # Nothing was written outside output_dir.
    assert not (tmp_path.parent / "etc").exists()
    assert not (tmp_path / "etc").exists()
    for entry in manifest:
        assert Path(entry.output_path).resolve().is_relative_to(output_dir.resolve())
    assert any(r.category == "unsafe_layer_name" for r in qa.records)


def test_colliding_sanitized_layer_names_merge_not_overwrite(tmp_path):
    """Two raw layer names that sanitize to the same safe name must merge,
    not silently drop one group's points."""
    qa = QACollector()
    output_dir = tmp_path / "out"
    points = [_pt("A-1", "A"), _pt("B-1", "B")]
    manifest = export_survey_to_cad_gis(
        points, {"A": "../x", "B": "..\\x"}, output_dir, qa=qa)

    assert len(manifest) == 1
    assert manifest[0].point_count == 2
