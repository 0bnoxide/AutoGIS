"""Offline native-adapter contracts; ArcPy I/O is replaced, adapter math is real."""
import json
from contextlib import contextmanager
from types import SimpleNamespace as NS

import numpy as np
import pytest

from autogis.adapters import toolbox_core as t
from autogis.core.envmon.msl_lidar import RasterSource


def rectangle(left=0, bottom=0, right=2, top=2):
    return [[left, bottom], [left, top], [right, top], [right, bottom], [left, bottom]]


class Reference:
    def __init__(self, code=4326, *, datum=None, vcs=None):
        self.factoryCode = code
        self.name = f'CRS {code}'
        self.type = 'Geographic' if code == 4326 else 'Projected'
        self.GCS = NS(datumName=datum or ('NAD83' if code == 6514 else 'WGS84'))
        self.VCS = vcs
        self.linearUnitName = 'Meter'
        self.angularUnitName = 'Degree'
        self.wkt = f'GEOGCRS["{self.name}",CS[ellipsoidal,2]]'

    def exportToString(self):
        return self.wkt

    def loadFromString(self, text):
        self.wkt = text


class Geometry:
    def __init__(self, rings, sr=None):
        self.rings = rings
        self.spatialReference = sr or Reference()
        points = [p for ring in rings for p in ring]
        self.extent = NS(XMin=min(p[0] for p in points), YMin=min(p[1] for p in points),
                         XMax=max(p[0] for p in points), YMax=max(p[1] for p in points))
        self.projections = []

    @property
    def JSON(self):
        return json.dumps({'rings': self.rings})

    def projectAs(self, target, *transformation):
        self.projections.append((target, transformation))
        return Geometry(self.rings, target)


class ArcIO:
    """External I/O double: fixed clip result, real file copy and block windows.

    This does not emulate Esri projection/mosaic/clip algorithms. Those calls are
    recorded as boundary contracts; the supplied raster represents their output.
    NaN denotes NoData in these tiny on-disk NumPy fixtures, not a TIFF encoding.
    """
    def __init__(self, values=((0, 1), (2, np.nan))):
        self.values = np.array(values, dtype=float)
        self.sr = Reference()
        self.nodata = 'NaN'
        self.pixel_type = 'F32'
        self.cell_height = 1
        self.calls = []
        self.reads = []
        self.transforms = []
        self.available = {'Spatial': 'Available', 'ImageAnalyst': 'Available'}
        self.checkout = 'CheckedOut'
        self.fail_save = False
        self.management = NS(CopyFeatures=self.copy_features, ProjectRaster=self.project,
                             MosaicToNewRaster=self.mosaic, Clip=self.clip,
                             DefineProjection=self.define)
        self.sa = NS(Times=self.times)

    SpatialReference = staticmethod(Reference)
    Point = staticmethod(lambda x, y: NS(X=x, Y=y))

    def Describe(self, path):
        return NS(spatialReference=self.sr, noDataValue=self.nodata,
                  meanCellWidth=1, meanCellHeight=self.cell_height,
                  extent=NS(XMin=0, YMin=0, XMax=self.values.shape[1], YMax=self.values.shape[0]),
                  pixelType=self.pixel_type, bandCount=1)

    def Raster(self, path):
        return self.Describe(path)

    def RasterToNumPyArray(self, raster, point, ncols, nrows, nodata):
        self.reads.append((point.X, point.Y, ncols, nrows, nodata))
        result = np.full((nrows, ncols), nodata, dtype=float)
        top = round(self.values.shape[0] - point.Y - nrows)
        left = round(point.X)
        for row in range(nrows):
            for col in range(ncols):
                r, c = top + row, left + col
                if 0 <= r < self.values.shape[0] and 0 <= c < self.values.shape[1]:
                    value = self.values[r, c]
                    result[row, col] = nodata if np.isnan(value) else value
        return result

    def AsShape(self, geojson, esri_json):
        assert esri_json is False
        return Geometry(geojson['coordinates'])

    def ListTransformations(self, source, target, extent, vertical, first_only):
        self.calls.append(('transform', source, target, extent, vertical, first_only))
        return self.transforms

    def copy_features(self, shapes, path):
        self.calls.append(('features', shapes, path))

    def project(self, source, output, target, **kwargs):
        self.calls.append(('project', source, output, target, kwargs))

    def mosaic(self, inputs, directory, name, **kwargs):
        self.calls.append(('mosaic', inputs, directory, name, kwargs))

    @staticmethod
    def write(path, values):
        with open(path, 'wb') as stream:
            np.save(stream, values)

    def clip(self, source, rectangle, output, polygon, **kwargs):
        self.calls.append(('clip', source, rectangle, output, polygon, kwargs))
        self.write(output, self.values)

    def define(self, path, target):
        self.calls.append(('define', path, target))
        self.values = np.load(path)

    @contextmanager
    def EnvManager(self, **kwargs):
        self.calls.append(('environment', kwargs))
        try:
            yield
        finally:
            self.calls.append(('environment_exit',))

    def CheckExtension(self, extension):
        return self.available[extension]

    def CheckOutExtension(self, extension):
        self.calls.append(('checkout', extension))
        return self.checkout

    def CheckInExtension(self, extension):
        self.calls.append(('checkin', extension))

    def times(self, path, factor):
        def save(output):
            if self.fail_save:
                raise RuntimeError('conversion save failed')
            self.write(output, np.load(path) * factor)
        return NS(save=save)


@pytest.fixture
def processing(tmp_path):
    source = RasterSource(tmp_path / 'tile.tif', 'project-a', 'https://example.test/tile.zip',
                          'abc123', 'tile.tif', 'quad-a', '2026-11-10T00:00:00Z')
    aoi = {'type': 'Polygon', 'coordinates': [rectangle()]}
    return ArcIO(), source, aoi, tmp_path / 'output.tif'


def add_vertical_metadata(source):
    source.path.with_suffix('.tif.xml').write_text(
        '<metadata><altdatum>NAVD88</altdatum><altunits>meters</altunits></metadata>')


def test_native_copy_keeps_zero_one_nodata_and_unknown_vertical_provenance(processing):
    """Catches zero-as-NoData, invented vertical units, and lossy default mosaic type."""
    arc, source, aoi, out = processing
    result = t.process_msl_dem_arcpy(arc, [source], aoi, out)
    np.testing.assert_equal(np.load(out), [[0, 1], [2, np.nan]])
    assert result['coverage']['aoi_cells'] == 4
    assert result['coverage']['valid_cells'] == 3
    assert result['coverage']['fraction'] == .75
    assert result['coverage']['complete'] is False
    assert result['output']['z_units'] is None
    assert result['output']['vertical_datum'] is None
    assert result['output']['scale_factors'] == [1.0]
    assert result['sources'][0]['archive_sha256'] == 'abc123'
    assert result['sources'][0]['nodata'] == 'NaN'
    assert result['sources'][0]['vertical_metadata_status'] == 'unknown'
    assert result['operations'][0]['priority'] == ['project-a:tile.tif']
    assert any('1 AOI pixel centers' in w for w in result['warnings'])
    assert any('unknown' in w for w in result['warnings'])
    mosaic = next(c for c in arc.calls if c[0] == 'mosaic')
    assert mosaic[1] == [str(source.path)]
    assert mosaic[4]['pixel_type'] == '32_BIT_FLOAT'
    assert mosaic[4]['mosaic_method'] == 'FIRST'
    assert mosaic[4]['number_of_bands'] == 1
    clip = next(c for c in arc.calls if c[0] == 'clip')
    assert clip[2] == '#'
    assert clip[5] == {'clipping_geometry': 'ClippingGeometry',
                       'maintain_clipping_extent': 'NO_MAINTAIN_EXTENT'}
    assert not any(c[0] in ('checkout', 'project') for c in arc.calls)


def test_explicit_projection_records_ranked_horizontal_transform_and_precision(processing):
    """Catches using a lower-ranked transform, vertical reprojection, or float32 int32 loss."""
    arc, source, aoi, out = processing
    arc.pixel_type = 'S32'
    arc.transforms = ['ranked-first', 'ranked-second']
    result = t.process_msl_dem_arcpy(arc, [source], aoi, out, output_crs='EPSG:3857', resolution=1)
    project = next(c for c in arc.calls if c[0] == 'project')
    assert project[1] == str(source.path)
    assert project[3].factoryCode == 3857
    assert project[4] == {'resampling_type': 'BILINEAR', 'cell_size': 1,
                          'geographic_transform': 'ranked-first', 'vertical': 'NO_VERTICAL'}
    assert next(c for c in arc.calls if c[0] == 'mosaic')[4]['pixel_type'] == '64_BIT'
    environment = next(c for c in arc.calls if c[0] == 'environment')[1]
    assert environment['snapRaster'] == project[2]
    assert environment['cellSize'] == 1
    assert result['operations'][2]['transformations'] == [
        {'purpose': 'AOI', 'name': 'ranked-first'}, {'purpose': 'tile.tif', 'name': 'ranked-first'}]
    assert all(c[4:] == (False, True) for c in arc.calls if c[0] == 'transform')


@pytest.mark.parametrize('extension', ['Spatial', 'ImageAnalyst'])
def test_conversion_scales_only_valid_cells_and_returns_license(processing, extension):
    """Catches reversed conversion factor, missing fallback, or leaked checkout."""
    arc, source, aoi, out = processing
    add_vertical_metadata(source)
    if extension == 'ImageAnalyst':
        arc.available['Spatial'] = 'Unavailable'
    result = t.process_msl_dem_arcpy(arc, [source], aoi, out, z_units='int-ft')
    np.testing.assert_allclose(np.load(out), [[0, 3.280839895], [6.56167979, np.nan]])
    assert result['output']['vertical_datum'] == 'NAVD88'
    assert result['output']['z_units'] == 'int-ft'
    assert result['output']['vertical_transformation'] is None
    assert result['coverage']['valid_cells'] == 3
    assert ('checkout', extension) in arc.calls
    assert ('checkin', extension) in arc.calls
    assert arc.calls.index(('checkin', extension)) < arc.calls.index(('environment_exit',))


@pytest.mark.parametrize('failure, message, checked_in', [
    ('unavailable', 'requires Spatial Analyst', False),
    ('checkout', 'checkout failed', False),
    ('save', 'conversion save failed', True),
])
def test_conversion_failure_never_publishes_and_releases_acquired_license(processing, failure, message, checked_in):
    """Catches writing despite failed checkout or skipping finally after Times.save fails."""
    arc, source, aoi, out = processing
    add_vertical_metadata(source)
    if failure == 'unavailable':
        arc.available = dict.fromkeys(arc.available, 'Unavailable')
    elif failure == 'checkout':
        arc.checkout = 'Unavailable'
    else:
        arc.fail_save = True
    with pytest.raises((ValueError, RuntimeError), match=message):
        t.process_msl_dem_arcpy(arc, [source], aoi, out, z_units='us-ft')
    assert not out.exists()
    assert (('checkin', 'Spatial') in arc.calls) is checked_in
    assert arc.calls[-1] == ('environment_exit',)
    assert not any(c[0] == 'define' for c in arc.calls)


def test_existing_output_is_not_modified_or_inspected(processing):
    """Catches replacing an existing user raster before refusing the request."""
    arc, source, aoi, out = processing
    out.write_bytes(b'keep existing raster')
    with pytest.raises(FileExistsError):
        t.process_msl_dem_arcpy(arc, [source], aoi, out)
    assert out.read_bytes() == b'keep existing raster'
    assert not (out.parent / 'native-processing').exists()


@pytest.mark.parametrize('nodata', ['not-a-number', [0, 1]])
def test_bad_nodata_metadata_fails_before_processing(processing, nodata):
    """Catches silently coercing malformed NoData to a valid elevation."""
    arc, source, aoi, out = processing
    arc.nodata = nodata
    with pytest.raises(ValueError, match='NoData metadata'):
        t.process_msl_dem_arcpy(arc, [source], aoi, out)
    assert not out.exists()
    assert arc.calls == []


def test_nonsquare_native_grid_requires_explicit_resolution(processing):
    """Catches silently replacing the source Y cell size with X cell size."""
    arc, source, aoi, out = processing
    arc.cell_height = 2
    with pytest.raises(ValueError, match='square cells'):
        t.process_msl_dem_arcpy(arc, [source], aoi, out)
    assert not any(c[0] == 'mosaic' for c in arc.calls)
    assert not out.exists()


def test_coverage_counts_holes_outside_extent_and_nonfinite_cells():
    """Catches extent-only denominator, lost holes, sentinel collision, and infinite data."""
    arc = ArcIO([[0, 1, np.inf], [2, np.nan, 4], [5, 6, 7]])
    shape = Geometry([rectangle(-1, 0, 4, 3), rectangle(1, 1, 2, 2)])
    coverage = t._msl_native_coverage(arc, 'output', [shape])
    assert coverage['aoi_cells'] == 14
    assert coverage['valid_cells'] == 7
    assert coverage['fraction'] == .5
    assert coverage['complete'] is False
    assert coverage['overlap_cells'] is None
    assert arc.reads == [(-1, 0, 5, 3, 0), (-1, 0, 5, 3, 1)]


def test_coverage_reads_bounded_blocks_with_correct_lower_left_coordinates():
    """Catches row/column block offsets and incorrect lower-left coordinates on last blocks."""
    arc = ArcIO(np.zeros((513, 513)))
    coverage = t._msl_native_coverage(arc, 'output', [Geometry([rectangle(0, 0, 513, 513)])])
    assert coverage['valid_cells'] == coverage['aoi_cells'] == 263169
    assert coverage['complete'] is True
    assert arc.reads[::2] == [(0, 1, 512, 512, 0), (512, 1, 1, 512, 0),
                              (0, 0, 512, 1, 0), (512, 0, 1, 1, 0)]


@pytest.mark.parametrize('ring, values, message', [
    (rectangle(0, 0, .1, .1), [[1]], 'no output pixel centers'),
    (rectangle(0, 0, 1, 1), [[np.nan]], 'No valid HFDEM'),
])
def test_coverage_rejects_empty_sample_or_all_nodata(ring, values, message):
    """Catches reporting success for an AOI with no usable output cells."""
    with pytest.raises(ValueError, match=message):
        t._msl_native_coverage(ArcIO(values), 'output', [Geometry([ring])])


def test_geometry_projection_uses_first_horizontal_transform_and_same_crs_shortcut():
    """Catches discarded transform names and unnecessary projection of matching CRSs."""
    arc = ArcIO()
    geometry = Geometry([rectangle()])
    assert t._msl_project_geometry(arc, geometry, Reference()) == (geometry, None)
    assert arc.calls == []
    arc.transforms = ['best', 'worse']
    target = Reference(3857, datum='other')
    projected, selected = t._msl_project_geometry(arc, geometry, target)
    assert selected == 'best'
    assert projected.spatialReference is target
    assert geometry.projections == [(target, ('best',))]
    assert arc.calls[0][3] is geometry.extent
    assert arc.calls[0][4:] == (False, True)


def test_geometry_projection_without_transform_only_allows_same_datum():
    """Catches silently treating different datums as interchangeable."""
    arc = ArcIO()
    geometry = Geometry([rectangle()])
    target = Reference(3857)
    projected, selected = t._msl_project_geometry(arc, geometry, target)
    assert selected is None
    assert projected.spatialReference is target
    assert geometry.projections == [(target, ())]
    with pytest.raises(ValueError, match='No available horizontal transformation'):
        t._msl_project_geometry(arc, geometry, Reference(9999, datum='other'))
    geometry.spatialReference.name = 'Unknown'
    with pytest.raises(ValueError, match='unknown spatial reference'):
        t._msl_project_geometry(arc, geometry, target)


def test_raster_projection_refuses_missing_datum_transform(processing):
    """Catches invoking ProjectRaster with an empty transformation across datums."""
    arc, source, aoi, out = processing
    arc.sr = Reference(6514, datum='NAD83')
    with pytest.raises(ValueError, match='No available horizontal raster transformation'):
        t.process_msl_dem_arcpy(arc, [source], aoi, out, output_crs='EPSG:4326', resolution=1)
    assert not any(c[0] in ('project', 'mosaic') for c in arc.calls)
    assert not out.exists()


def test_horizontal_reference_strips_known_vcs_but_rejects_custom_compound():
    """Catches passing a vertical CRS to the horizontal raster projection pipeline."""
    arc = ArcIO()
    compound = Reference(6514, vcs=object())
    horizontal = t._msl_horizontal_sr(arc, compound)
    assert horizontal.factoryCode == 6514
    assert horizontal.VCS is None
    custom = Reference(0)
    assert t._msl_horizontal_sr(arc, custom) is custom
    custom.VCS = object()
    with pytest.raises(ValueError, match='Custom compound'):
        t._msl_horizontal_sr(arc, custom)
    custom.name = 'Unknown'
    with pytest.raises(ValueError, match='unknown horizontal'):
        t._msl_horizontal_sr(arc, custom)


@pytest.mark.parametrize('text, code', [('EPSG:3857', 3857), ('4326', 4326)])
def test_output_reference_parses_authority_before_validating(text, code):
    """Catches loading EPSG identifiers as WKT rather than authority codes."""
    assert t.msl_arcpy_output_sr(ArcIO(), text).factoryCode == code


def test_output_reference_loads_wkt_and_rejects_vertical_dimensions():
    """Catches bypassing dimension checks for user-provided WKT."""
    wkt = 'PROJCRS["custom",CS[Cartesian,2]]'
    assert t.msl_arcpy_output_sr(ArcIO(), wkt).exportToString() == wkt
    with pytest.raises(ValueError, match='two-dimensional'):
        t.msl_arcpy_output_sr(ArcIO(), 'GEOGCRS["3D",CS[ellipsoidal,3]]')


@pytest.mark.parametrize('nodata, expected', [(None, None), ('', None), ('-9999', -9999.0)])
def test_source_nodata_metadata_normalizes_without_changing_cells(processing, nodata, expected):
    """Catches losing the source sentinel or mistaking missing metadata for zero."""
    arc, source, aoi, out = processing
    arc.nodata = nodata
    result = t.process_msl_dem_arcpy(arc, [source], aoi, out)
    assert result['sources'][0]['nodata'] == expected
    np.testing.assert_equal(np.load(out), [[0, 1], [2, np.nan]])


def test_conversion_with_unknown_units_stops_before_native_processing(processing):
    """Catches assuming horizontal meters are evidence of elevation units."""
    arc, source, aoi, out = processing
    with pytest.raises(ValueError, match='unknown elevation units'):
        t.process_msl_dem_arcpy(arc, [source], aoi, out, z_units='m')
    assert arc.calls == []
    assert not out.exists()
    assert not (out.parent / 'native-processing').exists()


@pytest.mark.parametrize('attribute, value', [('name', 'Unknown'), ('type', 'Vertical'), ('VCS', 'NAVD88')])
def test_target_reference_rejects_nonhorizontal_or_unknown_crs(attribute, value):
    """Catches accepting vertical/unknown reference metadata as an output horizontal CRS."""
    sr = Reference()
    setattr(sr, attribute, value)
    with pytest.raises(ValueError, match='two-dimensional'):
        t._msl_validate_target_sr(sr)


def test_overlapping_features_are_unioned_before_coverage(processing):
    """Catches XOR cancellation of overlapping selected features in the coverage mask."""
    arc, source, aoi, out = processing
    shapes = [Geometry(aoi['coordinates']), Geometry(aoi['coordinates'])]
    unions = []
    # The ArcPy union boundary returns one polygon for identical polygons.
    def union(other):
        unions.append(other)
        return Geometry(aoi['coordinates'])
    shapes[0].union = union
    iterator = iter(shapes)
    arc.AsShape = lambda *args: next(iterator)
    multi = {'type': 'MultiPolygon', 'coordinates': [aoi['coordinates'], aoi['coordinates']]}
    result = t.process_msl_dem_arcpy(arc, [source], multi, out)
    assert unions == [shapes[1]]
    assert result['coverage']['aoi_cells'] == 4
    assert result['coverage']['valid_cells'] == 3
