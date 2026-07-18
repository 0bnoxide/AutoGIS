import json
from types import SimpleNamespace

import pytest

from autogis.adapters.toolbox_core import (
    export_tin_landxml,
    staged_cad_layers,
    surface_from_triangle_json,
)
from autogis.core.envmon.cad_layer_map import CADLayerMapping


class _Cursor:
    def __init__(self, rows):
        self.rows = [list(row) for row in rows]
        self.updated = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.rows)

    def updateRow(self, row):
        self.updated.append(tuple(row))


class _FakeArcPy:
    def __init__(self, tmp_path, triangle_rows=(), license_status="Available",
                 vertical_reference=None, checkout_status="CheckedOut"):
        self.env = SimpleNamespace(scratchGDB=str(tmp_path / "scratch.gdb"))
        self.copied = []
        self.added = []
        self.deleted = []
        self.triangulated = []
        self.update_cursors = {}
        self.triangle_rows = list(triangle_rows)
        self.license_status = license_status
        self.checkout_status = checkout_status
        self.vertical_reference = vertical_reference
        self.checked_out = []
        self.checked_in = []
        self.management = SimpleNamespace(
            CopyFeatures=lambda source, dest: self.copied.append((source, dest)),
            Delete=lambda path: self.deleted.append(path),
        )
        self.conversion = SimpleNamespace(
            AddCADFields=lambda *args: self.added.append(args),
        )
        self.ddd = SimpleNamespace(TinTriangle=self._tin_triangle)
        self.da = SimpleNamespace(
            UpdateCursor=self._update_cursor,
            SearchCursor=lambda _path, _fields: _Cursor(self.triangle_rows),
        )

    def _update_cursor(self, path, fields):
        cursor = _Cursor([[None, None, None], [None, None, None]])
        cursor.fields = list(fields)
        self.update_cursors[path] = cursor
        return cursor

    def _tin_triangle(self, *args):
        self.triangulated.append(args)

    @staticmethod
    def _spatial_reference(vertical_reference=None):
        return SimpleNamespace(spatialReference=SimpleNamespace(
            factoryCode=2256, metersPerUnit=1200.0 / 3937.0,
            type="Projected", VCS=vertical_reference))

    def Describe(self, _path):
        return self._spatial_reference(self.vertical_reference)

    def CheckExtension(self, _extension):
        return self.license_status

    def CheckOutExtension(self, extension):
        self.checked_out.append(extension)
        return self.checkout_status

    def CheckInExtension(self, extension):
        self.checked_in.append(extension)


def _triangle(*xyz):
    ring = [list(point) for point in xyz]
    ring.append(ring[0])
    return (json.dumps({"hasZ": True, "rings": [ring]}),)


def test_staged_cad_layers_apply_properties_to_copies_and_clean_up(tmp_path):
    arcpy = _FakeArcPy(tmp_path)
    mappings = [
        CADLayerMapping("wells", "V-WELL", 3, "DASHED"),
        CADLayerMapping("contours", "C-TOPO", None, None),
    ]

    with staged_cad_layers(arcpy, ["source/wells", "source/contours"], mappings) as staged:
        assert len(staged) == 2
        assert not arcpy.deleted
        assert [call[0] for call in arcpy.copied] == ["source/wells", "source/contours"]
        assert all(call[0] in staged for call in arcpy.added)
        # AddCADFields(..., ADD_LAYER_PROPERTIES, ...) names the reserved
        # layer field ``LyrName`` (not ``Layer``) — a cursor over ``Layer``
        # raises "Cannot find field 'Layer'" against real arcpy and aborts
        # every export. Pin the schema so that regression cannot recur.
        assert arcpy.update_cursors[staged[0]].fields == [
            "LyrName", "LyrColor", "LyrLnType"]
        assert arcpy.update_cursors[staged[0]].updated == [
            ("V-WELL", 3, "DASHED"), ("V-WELL", 3, "DASHED")]
        assert arcpy.update_cursors[staged[1]].updated == [
            ("C-TOPO", None, None), ("C-TOPO", None, None)]

    assert arcpy.deleted == staged


def test_staged_cad_layers_clean_up_when_export_fails(tmp_path):
    arcpy = _FakeArcPy(tmp_path)
    mapping = CADLayerMapping("wells", "V-WELL")
    with pytest.raises(RuntimeError, match="export failed"):
        with staged_cad_layers(arcpy, ["source/wells"], [mapping]) as staged:
            raise RuntimeError("export failed")
    assert arcpy.deleted == staged


def test_surface_from_triangle_json_deduplicates_shared_vertices():
    rows = [
        _triangle((0, 0, 100), (10, 0, 101), (0, 10, 102))[0],
        _triangle((10, 0, 101), (10, 10, 103), (0, 10, 102))[0],
    ]
    surface = surface_from_triangle_json(rows, "Groundwater")
    assert surface.points == {
        1: (0.0, 0.0, 100.0),
        2: (0.0, 10.0, 101.0),
        3: (10.0, 0.0, 102.0),
        4: (10.0, 10.0, 103.0),
    }
    assert surface.faces == [(1, 2, 3), (2, 4, 3)]


def test_surface_from_triangle_json_rejects_non_finite_coordinates():
    with pytest.raises(ValueError, match="non-finite"):
        surface_from_triangle_json([
            _triangle((0, 0, 100), (10, 0, float("nan")), (0, 10, 102))[0],
        ], "Groundwater")


def test_export_tin_landxml_extracts_faces_and_cleans_scratch(tmp_path):
    arcpy = _FakeArcPy(tmp_path, [
        _triangle((1000, 2000, 512.5), (1010, 2000, 513), (1000, 2010, 514)),
    ])
    out = export_tin_landxml(
        arcpy, "groundwater_tin", tmp_path / "surface.xml",
        surface_name="Groundwater", crs="EPSG:2256", linear_unit="USSurveyFoot")

    assert out.exists()
    assert arcpy.triangulated[0][0] == "groundwater_tin"
    assert arcpy.triangulated[0][2:] == ("PERCENT",)
    assert arcpy.deleted == [arcpy.triangulated[0][1]]
    assert arcpy.checked_out == ["3D"]
    assert arcpy.checked_in == ["3D"]
    text = out.read_text(encoding="utf-8")
    assert '<Surface name="Groundwater">' in text
    assert '<F>1 2 3</F>' in text
    assert 'linearUnit="USSurveyFoot"' in text


def test_export_tin_landxml_rejects_mislabeled_units(tmp_path):
    arcpy = _FakeArcPy(tmp_path)
    with pytest.raises(ValueError, match="does not match"):
        export_tin_landxml(
            arcpy, "groundwater_tin", tmp_path / "surface.xml",
            surface_name="Groundwater", crs="EPSG:2256", linear_unit="meter")
    assert not arcpy.triangulated


def test_export_tin_landxml_rejects_geographic_tin(tmp_path):
    arcpy = _FakeArcPy(tmp_path)
    arcpy.Describe = lambda _path: SimpleNamespace(
        spatialReference=SimpleNamespace(
            factoryCode=2256, type="Geographic", metersPerUnit=0, VCS=None))
    with pytest.raises(ValueError, match="projected coordinate system"):
        export_tin_landxml(
            arcpy, "groundwater_tin", tmp_path / "surface.xml",
            surface_name="Groundwater", crs="EPSG:2256",
            linear_unit="USSurveyFoot")
    assert not arcpy.checked_out


def test_export_tin_landxml_rejects_mismatched_vertical_units(tmp_path):
    arcpy = _FakeArcPy(
        tmp_path,
        vertical_reference=SimpleNamespace(metersPerUnit=1.0, direction=1),
    )
    with pytest.raises(ValueError, match="vertical coordinates"):
        export_tin_landxml(
            arcpy, "groundwater_tin", tmp_path / "surface.xml",
            surface_name="Groundwater", crs="EPSG:2256",
            linear_unit="USSurveyFoot")
    assert not arcpy.checked_out


def test_export_tin_landxml_rejects_unavailable_license(tmp_path):
    arcpy = _FakeArcPy(tmp_path, license_status="Unavailable")
    with pytest.raises(ValueError, match="3D Analyst license is unavailable"):
        export_tin_landxml(
            arcpy, "groundwater_tin", tmp_path / "surface.xml",
            surface_name="Groundwater", crs="EPSG:2256",
            linear_unit="USSurveyFoot")
    assert not arcpy.checked_out


def test_export_tin_landxml_rejects_failed_license_checkout(tmp_path):
    arcpy = _FakeArcPy(tmp_path, checkout_status="Unavailable")
    with pytest.raises(ValueError, match="license checkout failed"):
        export_tin_landxml(
            arcpy, "groundwater_tin", tmp_path / "surface.xml",
            surface_name="Groundwater", crs="EPSG:2256",
            linear_unit="USSurveyFoot")
    assert arcpy.checked_out == ["3D"]
    assert not arcpy.checked_in
    assert not arcpy.triangulated


def test_export_tin_landxml_releases_license_when_extraction_fails(tmp_path):
    arcpy = _FakeArcPy(tmp_path)

    def fail_extraction(*_args):
        raise RuntimeError("triangle extraction failed")

    arcpy.ddd.TinTriangle = fail_extraction
    with pytest.raises(RuntimeError, match="triangle extraction failed"):
        export_tin_landxml(
            arcpy, "groundwater_tin", tmp_path / "surface.xml",
            surface_name="Groundwater", crs="EPSG:2256",
            linear_unit="USSurveyFoot")
    assert arcpy.checked_out == ["3D"]
    assert arcpy.checked_in == ["3D"]
    assert len(arcpy.deleted) == 1
