"""Tests for autogis/core/common/landxml.py (read-only TIN parser, stdlib)."""
import pytest

from autogis.core.common.landxml import elevation_at, parse_landxml_surface

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
