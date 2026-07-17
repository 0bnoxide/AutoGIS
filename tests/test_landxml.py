"""Tests for autogis/core/common/landxml.py (read-only TIN parser, stdlib)."""
import pytest

from autogis.core.common.landxml import (
    LandXMLSurface, elevation_at, parse_landxml_surface,
)

_LANDXML = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
  <Surfaces>
    <Surface name="EG">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">0.0 0.0 100.0</P>
          <P id="2">0.0 10.0 102.0</P>
          <P id="3">10.0 0.0 98.0</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
</LandXML>
"""


def _write(tmp_path, text=_LANDXML):
    p = tmp_path / "surface.xml"
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_landxml_surface_points_and_faces(tmp_path):
    surface = parse_landxml_surface(_write(tmp_path))
    assert surface.name == "EG"
    assert surface.points == {1: (0.0, 0.0, 100.0), 2: (0.0, 10.0, 102.0),
                              3: (10.0, 0.0, 98.0)}
    assert surface.faces == [(1, 2, 3)]


def test_parse_landxml_surface_missing_surface_raises(tmp_path):
    p = _write(tmp_path, "<LandXML><Surfaces/></LandXML>")
    with pytest.raises(ValueError, match="No <Surface>"):
        parse_landxml_surface(p)


def test_parse_landxml_surface_unknown_name_raises(tmp_path):
    with pytest.raises(ValueError, match="Bogus"):
        parse_landxml_surface(_write(tmp_path), surface_name="Bogus")


def test_elevation_at_centroid_is_average_of_vertices(tmp_path):
    surface = parse_landxml_surface(_write(tmp_path))
    z = elevation_at(surface, 10.0 / 3, 10.0 / 3)
    assert z == pytest.approx(100.0)


def test_elevation_at_vertex_matches_vertex_elevation(tmp_path):
    surface = parse_landxml_surface(_write(tmp_path))
    assert elevation_at(surface, 0.0, 0.0) == pytest.approx(100.0)


def test_elevation_at_outside_triangle_is_none(tmp_path):
    surface = parse_landxml_surface(_write(tmp_path))
    assert elevation_at(surface, 1000.0, 1000.0) is None


def _grid_surface() -> LandXMLSurface:
    """A 2x2-quad (8-triangle) mesh with z == northing everywhere, so any
    point inside the mesh's convex hull interpolates to exactly its own
    northing regardless of which triangle contains it (the sampled function
    is itself an affine plane, exactly reproduced by every triangle)."""
    points = {}
    for row in range(3):
        for col in range(3):
            points[row * 3 + col + 1] = (float(row), float(col), float(row))
    faces = []
    for row in range(2):
        for col in range(2):
            tl, tr = row * 3 + col + 1, row * 3 + col + 2
            bl, br = (row + 1) * 3 + col + 1, (row + 1) * 3 + col + 2
            faces.append((tl, tr, br))
            faces.append((tl, br, bl))
    return LandXMLSurface(name="grid", points=points, faces=faces)


def test_elevation_at_grid_index_is_correct_across_many_faces():
    surface = _grid_surface()
    for northing, easting in [(0.25, 0.75), (0.75, 0.25), (1.3, 0.5),
                              (0.5, 1.9), (1.9, 1.1), (1.0, 1.0)]:
        assert elevation_at(surface, northing, easting) == pytest.approx(northing)


def test_elevation_at_grid_index_outside_mesh_is_none():
    surface = _grid_surface()
    assert elevation_at(surface, 10.0, 10.0) is None


def test_elevation_at_face_with_unknown_point_id_raises_value_error():
    surface = LandXMLSurface(
        name="broken",
        points={1: (0.0, 0.0, 100.0), 2: (0.0, 10.0, 102.0)},
        faces=[(1, 2, 99)])
    with pytest.raises(ValueError, match="99"):
        elevation_at(surface, 1.0, 1.0)


def test_elevation_at_surface_with_no_points_raises_clear_value_error():
    surface = LandXMLSurface(name="empty", points={}, faces=[])
    with pytest.raises(ValueError, match="no points"):
        elevation_at(surface, 1.0, 1.0)


# ---------------------------------------------------------------------------
# write_cgpoints Units / CoordinateSystem emission (PR #246 review)

def test_write_cgpoints_emits_units_and_coordinate_system(tmp_path):
    import xml.etree.ElementTree as ET
    from autogis.core.common.landxml import CgPoint, write_cgpoints

    out = write_cgpoints([CgPoint("1", 2000.0, 1000.0, 512.5)],
                         tmp_path / "pts.xml",
                         crs="EPSG:2256", linear_unit="foot")
    root = ET.parse(str(out)).getroot()
    # required LandXML root attributes (LandXML-1.2.xsd)
    assert root.get("version") == "1.2"
    assert root.get("date") and root.get("time")
    imperial = root.find("{*}Units/{*}Imperial")
    assert imperial is not None
    assert imperial.get("linearUnit") == "foot"
    # elevationUnit defaults to meter in the schema — must be explicit
    assert imperial.get("elevationUnit") == "feet"
    cs = root.find("{*}CoordinateSystem")
    assert cs.get("epsgCode") == "2256"
    assert cs.get("name") == "EPSG:2256"


def test_write_cgpoints_metric_units(tmp_path):
    import xml.etree.ElementTree as ET
    from autogis.core.common.landxml import CgPoint, write_cgpoints

    out = write_cgpoints([CgPoint("1", 1.0, 2.0, 3.0)], tmp_path / "pts.xml",
                         linear_unit="meter")
    root = ET.parse(str(out)).getroot()
    metric = root.find("{*}Units/{*}Metric")
    assert metric.get("linearUnit") == "meter"
    assert metric.get("elevationUnit") == "meter"
    assert root.find("{*}CoordinateSystem") is None  # no crs given


def test_write_cgpoints_rejects_unknown_unit(tmp_path):
    from autogis.core.common.landxml import CgPoint, write_cgpoints
    with pytest.raises(ValueError, match="linear unit"):
        write_cgpoints([CgPoint("1", 1.0, 2.0, 3.0)], tmp_path / "pts.xml",
                       linear_unit="furlong")


def test_write_cgpoints_legacy_bare_output(tmp_path):
    """No crs/linear_unit -> no Units/CoordinateSystem (export-survey-cad path)."""
    import xml.etree.ElementTree as ET
    from autogis.core.common.landxml import CgPoint, write_cgpoints

    out = write_cgpoints([CgPoint("1", 1.0, 2.0, 3.0)], tmp_path / "pts.xml")
    root = ET.parse(str(out)).getroot()
    assert root.find("{*}Units") is None
    assert root.find("{*}CoordinateSystem") is None
    assert root.find("{*}CgPoints/{*}CgPoint") is not None


def test_write_cgpoints_rejects_non_epsg_crs(tmp_path):
    """A crs with no EPSG code would emit a name-only <CoordinateSystem>
    that consumers can't read — refuse instead (issue #238)."""
    from autogis.core.common.landxml import CgPoint, write_cgpoints

    with pytest.raises(ValueError, match="EPSG"):
        write_cgpoints([CgPoint("1", 1.0, 2.0, 3.0)], tmp_path / "pts.xml",
                       crs="NAD83 State Plane")
    assert not (tmp_path / "pts.xml").exists()


@pytest.mark.parametrize("crs,expected", [
    ("EPSG:2256", 2256),
    ("epsg: 2256", 2256),
    ("2256", 2256),
    ("NAD83 State Plane", None),
    ("", None),
    (None, None),
])
def test_parse_epsg(crs, expected):
    from autogis.core.common.landxml import parse_epsg
    assert parse_epsg(crs) == expected


def test_write_landxml_surface_round_trips_points_faces_crs_and_units(tmp_path):
    import xml.etree.ElementTree as ET
    from autogis.core.common.landxml import write_landxml_surface

    surface = LandXMLSurface(
        name="Groundwater",
        points={
            1: (2000.0, 1000.0, 512.5),
            2: (2000.0, 1010.0, 513.0),
            3: (2010.0, 1000.0, 514.0),
        },
        faces=[(1, 2, 3)],
    )
    out = write_landxml_surface(
        surface, tmp_path / "surface.xml",
        crs="EPSG:2256", linear_unit="USSurveyFoot")

    parsed = parse_landxml_surface(out)
    assert parsed == surface
    root = ET.parse(out).getroot()
    assert root.find("{*}Units/{*}Imperial").get("linearUnit") == "USSurveyFoot"
    assert root.find("{*}CoordinateSystem").get("epsgCode") == "2256"
    assert root.find("{*}Surfaces/{*}Surface").get("name") == "Groundwater"


@pytest.mark.parametrize("surface,match", [
    (LandXMLSurface(name="", points={1: (0, 0, 0)}, faces=[(1, 1, 1)]), "name"),
    (LandXMLSurface(name="TIN", points={}, faces=[]), "no points"),
    (LandXMLSurface(name="TIN", points={1: (0, 0, 0)}, faces=[]), "no faces"),
    (LandXMLSurface(name="TIN", points={1: (0, 0, 0)}, faces=[(1, 2, 3)]),
     "unknown point"),
    (LandXMLSurface(name="TIN", points={1: (0, 0, 0)}, faces=[(1, 1, 1)]),
     "distinct points"),
    (LandXMLSurface(name="TIN", points={1: (0, 0, float("nan"))},
                    faces=[(1, 2, 3)]),
     "finite coordinates"),
])
def test_write_landxml_surface_rejects_invalid_tin(tmp_path, surface, match):
    from autogis.core.common.landxml import write_landxml_surface
    with pytest.raises(ValueError, match=match):
        write_landxml_surface(
            surface, tmp_path / "surface.xml", crs="EPSG:2256", linear_unit="foot")
