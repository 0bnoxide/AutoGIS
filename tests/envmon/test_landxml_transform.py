import xml.etree.ElementTree as ET

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


def test_transform_rejects_unit_that_does_not_match_crs(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:26913", linear_unit="meter")

    with pytest.raises(ValueError, match="EPSG:2256.*international foot"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:26913", target_crs="EPSG:2256",
            source_unit="meter", target_unit="USSurveyFoot")


def test_transform_rejects_geographic_crs(tmp_path):
    input_xml = write_landxml_surface(
        _surface(), tmp_path / "input.xml",
        crs="EPSG:4326", linear_unit="meter")
    with pytest.raises(ValueError, match="projected"):
        transform_landxml_surface(
            input_xml, tmp_path / "out.xml",
            source_crs="EPSG:4326", target_crs="EPSG:26913",
            source_unit="meter", target_unit="meter")


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
