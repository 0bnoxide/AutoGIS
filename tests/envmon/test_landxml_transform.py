import importlib.util
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.landxml import (
    LandXMLSurface,
    linear_unit_scale,
    parse_landxml_surface,
    write_landxml_surface,
)
from autogis.core.envmon.landxml_transform import transform_landxml_surface

# `landxml_transform` imports pyproj lazily and raises its own message when it
# is absent, so this module imports fine either way -- but every test that
# actually transforms then hard-failed instead of skipping (#441). Marked
# per-test rather than at module level so the parsing/unit-scale tests, which
# need no pyproj at all, keep running on a bare install.
requires_pyproj = pytest.mark.skipif(
    importlib.util.find_spec("pyproj") is None,
    reason="needs the optional [landxml] extra (pyproj)")


def _surface() -> LandXMLSurface:
    return LandXMLSurface(
        name="Existing Ground",
        points={
            1: (4_400_000.0, 500_000.0, 100.0),
            2: (4_400_000.0, 500_010.0, 101.0),
            3: (4_400_010.0, 500_000.0, 102.0),
        },
        faces=[(1, 2, 3)],
    )


@pytest.mark.parametrize("source,target", [
    ("meter", "meter"),
    ("meter", "foot"),
    ("meter", "USSurveyFoot"),
    ("foot", "meter"),
    ("foot", "foot"),
    ("foot", "USSurveyFoot"),
    ("USSurveyFoot", "meter"),
    ("USSurveyFoot", "foot"),
    ("USSurveyFoot", "USSurveyFoot"),
])
def test_linear_unit_scale_supports_every_landxml_pair(source, target):
    meters = {"meter": 1.0, "foot": 0.3048,
              "USSurveyFoot": 1200.0 / 3937.0}
    assert linear_unit_scale(source, target) == pytest.approx(
        meters[source] / meters[target])


@requires_pyproj
def test_transform_meter_to_us_survey_foot_preserves_tin_and_round_trips(
        tmp_path):
    source = _surface()
    input_xml = write_landxml_surface(
        source, tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    result = transform_landxml_surface(
        input_xml, tmp_path / "feet.xml",
        source_crs="EPSG:26913", target_crs="EPSG:2232",
        source_unit="meter", target_unit="USSurveyFoot",
        output_surface_name="Existing Ground - Colorado")

    transformed = parse_landxml_surface(result.output_path)
    assert transformed.name == "Existing Ground - Colorado"
    assert transformed.faces == source.faces
    assert transformed.points[1][2] == pytest.approx(100.0 * 3937.0 / 1200.0)
    assert result.point_count == 3
    assert result.face_count == 1

    root = ET.parse(result.output_path).getroot()
    assert root.find("{*}CoordinateSystem").get("epsgCode") == "2232"
    assert root.find("{*}Units/{*}Imperial").get(
        "linearUnit") == "USSurveyFoot"

    back = transform_landxml_surface(
        result.output_path, tmp_path / "roundtrip.xml",
        source_crs="EPSG:2232", target_crs="EPSG:26913",
        source_unit="USSurveyFoot", target_unit="meter")
    round_trip = parse_landxml_surface(back.output_path)
    for point_id, expected in source.points.items():
        assert round_trip.points[point_id] == pytest.approx(expected, abs=1e-6)
    assert round_trip.faces == source.faces


@requires_pyproj
def test_transform_rejects_source_metadata_mismatch_without_override(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="foot")

    with pytest.raises(ValueError, match="declares linear unit 'foot'"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:26913", target_crs="EPSG:26913",
            source_unit="meter", target_unit="meter")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:26913", target_crs="EPSG:26913",
        source_unit="meter", target_unit="meter",
        override_source_metadata=True)
    assert result.output_path.exists()


@requires_pyproj
def test_transform_converts_mixed_unit_elevations_without_scaling_xy(tmp_path):
    source = _surface()
    input_xml = write_landxml_surface(
        source, tmp_path / "input.xml",
        crs="EPSG:2232", linear_unit="USSurveyFoot")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:2232", target_crs="EPSG:2232",
        source_unit="USSurveyFoot", source_z_unit="meter",
        target_unit="USSurveyFoot")
    transformed = parse_landxml_surface(result.output_path)

    assert transformed.points[1][:2] == pytest.approx(source.points[1][:2])
    assert transformed.points[1][2] == pytest.approx(100.0 * 3937.0 / 1200.0)
    assert result.source_z_unit == "meter"


@requires_pyproj
def test_transform_rejects_unit_that_does_not_match_crs(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    with pytest.raises(ValueError, match="target-unit.*international foot"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:26913", target_crs="EPSG:2256",
            source_unit="meter", target_unit="USSurveyFoot")


def _montana_geographic_surface() -> LandXMLSurface:
    return LandXMLSurface(
        name="Montana",
        points={
            1: (47.0, -110.0, 100.0),
            2: (47.0, -109.999, 101.0),
            3: (47.001, -110.0, 102.0),
        },
        faces=[(1, 2, 3)],
    )


@pytest.mark.parametrize("operation", [
    "ESRI:108190",
    "WGS_1984_(ITRF00)_To_NAD_1983",
])
@requires_pyproj
def test_transform_geographic_source_uses_requested_esri_operation(
        tmp_path, operation):
    source = _montana_geographic_surface()
    input_xml = write_landxml_surface(
        source, tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:4326", target_crs="EPSG:2256",
        geographic_transformation=operation)
    transformed = parse_landxml_surface(result.output_path)

    assert transformed.faces == source.faces
    assert transformed.points[1][:2] == pytest.approx(
        (1_002_946.0212775877, 1_843_819.8537481118), abs=1e-5)
    assert result.source_unit == "degree"
    assert result.target_unit == "foot"
    assert result.operation_name == "WGS_1984_(ITRF00)_To_NAD_1983"
    assert result.operation_authority == "ESRI"
    assert result.operation_code == "108190"
    assert result.operation_accuracy == pytest.approx(0.1)


@requires_pyproj
def test_transform_auto_selects_best_montana_operation(tmp_path):
    input_xml = write_landxml_surface(
        _montana_geographic_surface(), tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:4326", target_crs="EPSG:2256")

    assert result.operation_authority == "ESRI"
    assert result.operation_code == "108190"
    assert result.operation_accuracy == pytest.approx(0.1)


@requires_pyproj
def test_transform_projected_us_survey_foot_to_international_foot(tmp_path):
    source = LandXMLSurface(
        name="Montana",
        points={
            1: (1_000_000.0, 1_968_500.0, 100.0),
            2: (1_000_000.0, 1_968_510.0, 101.0),
            3: (1_000_010.0, 1_968_500.0, 102.0),
        },
        faces=[(1, 2, 3)],
    )
    input_xml = write_landxml_surface(
        source, tmp_path / "input.xml",
        crs="EPSG:2256", linear_unit="USSurveyFoot")
    root = ET.parse(input_xml)
    coordinate_system = root.getroot().find("{*}CoordinateSystem")
    coordinate_system.set("name", "ESRI:102700")
    coordinate_system.attrib.pop("epsgCode")
    root.write(input_xml, encoding="utf-8", xml_declaration=True)

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="ESRI:102700", target_crs="EPSG:2256")
    transformed = parse_landxml_surface(result.output_path)

    assert transformed.faces == source.faces
    assert transformed.points[1][1] == pytest.approx(1_968_503.937, abs=1e-6)
    assert result.source_unit == "USSurveyFoot"
    assert result.target_unit == "foot"


@requires_pyproj
@pytest.mark.parametrize("custom_scale", [3.28, 0.03])
def test_transform_custom_z_scale_changes_only_elevation(
        tmp_path, custom_scale):
    source = _surface()
    input_xml = write_landxml_surface(
        source, tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:26913", target_crs="EPSG:26913",
        z_scale=custom_scale)
    transformed = parse_landxml_surface(result.output_path)

    assert transformed.points[1][:2] == pytest.approx(source.points[1][:2])
    assert transformed.points[1][2] == pytest.approx(
        source.points[1][2] * custom_scale)
    assert result.z_scale == pytest.approx(custom_scale)
    assert result.z_scale_mode == "explicit"


@requires_pyproj
def test_custom_z_scale_needs_no_geographic_source_unit_metadata(tmp_path):
    source = _montana_geographic_surface()
    input_xml = write_landxml_surface(
        source, tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")
    tree = ET.parse(input_xml)
    tree.getroot().remove(tree.getroot().find("{*}Units"))
    tree.write(input_xml, encoding="utf-8", xml_declaration=True)

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:4326", target_crs="EPSG:2256",
        z_scale=3.28)
    transformed = parse_landxml_surface(result.output_path)

    assert transformed.points[1][2] == pytest.approx(328.0)
    assert result.source_z_unit is None
    assert result.z_scale == pytest.approx(3.28)
    assert result.z_scale_mode == "explicit"


@requires_pyproj
def test_geographic_source_z_unit_still_drives_automatic_scale(tmp_path):
    input_xml = write_landxml_surface(
        _montana_geographic_surface(), tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")
    tree = ET.parse(input_xml)
    tree.getroot().remove(tree.getroot().find("{*}Units"))
    tree.write(input_xml, encoding="utf-8", xml_declaration=True)

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:4326", target_crs="EPSG:2256",
        source_z_unit="meter")
    transformed = parse_landxml_surface(result.output_path)

    assert transformed.points[1][2] == pytest.approx(
        100.0 / 0.3048)
    assert result.source_z_unit == "meter"
    assert result.z_scale_mode == "automatic"


@pytest.mark.parametrize("invalid_scale", [0, -1, float("nan"), float("inf")])
def test_transform_rejects_invalid_custom_z_scale(tmp_path, invalid_scale):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    with pytest.raises(ValueError, match="positive finite"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:26913", target_crs="EPSG:26913",
            z_scale=invalid_scale)


def test_transform_rejects_z_unit_and_custom_scale_together(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    with pytest.raises(ValueError, match="source_z_unit.*z_scale"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:26913", target_crs="EPSG:26913",
            source_z_unit="meter", z_scale=3.28)


@requires_pyproj
def test_transform_rejects_unknown_geographic_transformation(tmp_path):
    input_xml = write_landxml_surface(
        _montana_geographic_surface(), tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")

    with pytest.raises(ValueError, match="Montana.*not available"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:4326", target_crs="EPSG:2256",
            geographic_transformation="Montana_Magic")


@requires_pyproj
def test_transform_rejects_missing_best_operation_grid(tmp_path, monkeypatch):
    input_xml = write_landxml_surface(
        _montana_geographic_surface(), tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")
    unavailable = SimpleNamespace(
        operations=(),
        grids=(SimpleNamespace(short_name="required.gsb", available=False),),
    )
    fake_group = SimpleNamespace(
        best_available=False,
        transformers=(),
        unavailable_operations=(unavailable,),
    )
    import pyproj.transformer
    monkeypatch.setattr(
        pyproj.transformer, "TransformerGroup",
        lambda *args, **kwargs: fake_group)

    with pytest.raises(ValueError, match="required.gsb"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:4326", target_crs="EPSG:2256")


@requires_pyproj
def test_transform_requires_override_for_authority_metadata_conflict(tmp_path):
    input_xml = write_landxml_surface(
        _montana_geographic_surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    with pytest.raises(ValueError, match="declares EPSG:26913"):
        transform_landxml_surface(
            input_xml, tmp_path / "blocked.xml",
            source_crs="EPSG:4326", target_crs="EPSG:2256")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:4326", target_crs="EPSG:2256",
        override_source_metadata=True)
    assert result.output_path.exists()


@requires_pyproj
def test_transform_requires_surface_name_when_input_has_multiple_surfaces(
        tmp_path):
    input_xml = tmp_path / "multi.xml"
    input_xml.write_text(
        """<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
        <Units><Metric linearUnit="meter"/></Units>
        <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>
        <Surfaces>
          <Surface name="A"><Definition surfType="TIN"><Pnts>
            <P id="1">4400000 500000 100</P>
            <P id="2">4400000 500010 101</P>
            <P id="3">4400010 500000 102</P>
          </Pnts><Faces><F>1 2 3</F></Faces></Definition></Surface>
          <Surface name="B"><Definition surfType="TIN"><Pnts>
            <P id="1">4400000 500000 200</P>
            <P id="2">4400000 500010 201</P>
            <P id="3">4400010 500000 202</P>
          </Pnts><Faces><F>1 2 3</F></Faces></Definition></Surface>
        </Surfaces></LandXML>""",
        encoding="utf-8")

    with pytest.raises(ValueError, match="multiple surfaces.*A.*B"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:26913", target_crs="EPSG:26913",
            source_unit="meter", target_unit="meter")

    result = transform_landxml_surface(
        input_xml, tmp_path / "out.xml",
        source_crs="EPSG:26913", target_crs="EPSG:26913",
        source_unit="meter", target_unit="meter", surface_name="B")
    assert parse_landxml_surface(result.output_path).name == "B"


def test_transform_refuses_existing_output_without_overwrite(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")
    output_xml = tmp_path / "out.xml"
    output_xml.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="overwrite"):
        transform_landxml_surface(
            input_xml, output_xml,
            source_crs="EPSG:26913", target_crs="EPSG:26913",
            source_unit="meter", target_unit="meter")
    assert output_xml.read_text(encoding="utf-8") == "keep"


@requires_pyproj
def test_transform_landxml_cli(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")
    output_xml = tmp_path / "out.xml"

    result = CliRunner().invoke(autogis, [
        "envmon", "transform-landxml",
        "--input", str(input_xml), "--output", str(output_xml),
        "--source-crs", "EPSG:26913", "--target-crs", "EPSG:26913",
        "--source-unit", "meter", "--target-unit", "meter",
    ])

    assert result.exit_code == 0, result.output
    assert "3 points / 1 faces" in result.output
    assert output_xml.exists()


@requires_pyproj
def test_transform_landxml_cli_hides_legacy_units_and_reports_custom_z(
        tmp_path):
    help_result = CliRunner().invoke(
        autogis, ["envmon", "transform-landxml", "--help"])
    assert help_result.exit_code == 0
    assert "--source-unit" not in help_result.output
    assert "--target-unit" not in help_result.output
    assert "--geographic-transformation" in help_result.output
    assert "--z-scale" in help_result.output

    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")
    output_xml = tmp_path / "out.xml"
    result = CliRunner().invoke(autogis, [
        "envmon", "transform-landxml",
        "--input", str(input_xml), "--output", str(output_xml),
        "--source-crs", "EPSG:26913", "--target-crs", "EPSG:26913",
        "--z-scale", "0.03",
    ])

    assert result.exit_code == 0, result.output
    assert "x 0.03 (explicit)" in result.output
    assert "Coordinate operation:" in result.output
