import pytest
from autogis.core.envmon import msl_raster as r


def test_unknown_vertical_units_are_not_inferred_from_horizontal_crs(tmp_path):
    path=tmp_path/'tile.tif';path.write_bytes(b'x')
    metadata=r.inspect_vertical_metadata(path,'PROJCS["NAD83 Montana",UNIT["metre",1]]')
    assert metadata['z_units'] is None and metadata['vertical_datum'] is None
    assert metadata['accuracy_evidence']==[]


def test_artifact_xml_accuracy_is_source_attributed_not_measured(tmp_path):
    path=tmp_path/'tile.tif';path.write_bytes(b'x')
    path.with_suffix('.tif.xml').write_text('<metadata><spref><vertdef><altsys><altdatum>NAVD88</altdatum><altunits>meters</altunits></altsys></vertdef></spref><dataqual><posacc><vertacc><vertaccr>Tested 0.10 meters at 95 percent confidence</vertaccr><qvertpa><vertaccv>0.10</vertaccv></qvertpa></vertacc></posacc></dataqual></metadata>')
    metadata=r.inspect_vertical_metadata(path,'')
    assert metadata['z_units']=='m' and metadata['vertical_datum']=='NAVD88'
    assert metadata['accuracy_evidence'][0]['status']=='publisher_reported'
    assert '95 percent' in metadata['accuracy_evidence'][0]['text']
    assert metadata['accuracy_evidence'][0]['source'].endswith('tile.tif.xml')


def test_compound_wkt_and_conflicting_xml(tmp_path):
    path=tmp_path/'tile.tif';path.write_bytes(b'x')
    wkt='COMPD_CS["test",PROJCS["horizontal",UNIT["metre",1]],VERT_CS["NAVD88 height",VERT_DATUM["North American Vertical Datum 1988",2005],UNIT["US survey foot",0.3048006096012192]]]'
    metadata=r.inspect_vertical_metadata(path,wkt)
    assert metadata['z_units']=='us-ft' and metadata['vertical_datum']=='NAVD88'
    path.with_suffix('.tif.xml').write_text('<metadata><altdatum>NAVD88</altdatum><altunits>meters</altunits></metadata>')
    with pytest.raises(ValueError,match='conflict'):r.inspect_vertical_metadata(path,wkt)


def test_xml_entities_rejected(tmp_path):
    path=tmp_path/'tile.tif';path.write_bytes(b'x')
    path.with_suffix('.tif.xml').write_text('<!DOCTYPE x [<!ENTITY bad SYSTEM "file:///secret">]><x>&bad;</x>')
    with pytest.raises(ValueError,match='Unsafe'):r.inspect_vertical_metadata(path,'')


def meta(project='A', units='m', datum='NAVD88', res=(1,1), origin=(0,10), crs='EPSG:6514'):
    return {'project':project,'z_units':units,'vertical_datum':datum,'resolution':list(res),'origin':list(origin),'horizontal_crs':crs,'dtype':'float32','nodata':0,'bands':1}


def test_compatibility_unknown_and_cross_project_gates():
    assert r.validate_raster_compatibility([meta(units=None,datum=None)])['z_units'] is None
    with pytest.raises(ValueError,match='units'):r.validate_raster_compatibility([meta(units=None)],z_units='int-ft')
    with pytest.raises(ValueError,match='unknown'):r.validate_raster_compatibility([meta(datum=None),meta('B',datum=None)])
    with pytest.raises(ValueError,match='datum'):r.validate_raster_compatibility([meta(),meta('B',datum='NGVD29')])
    with pytest.raises(ValueError,match='units'):r.validate_raster_compatibility([meta(),meta(units='us-ft')])


def test_native_grid_preservation_and_explicit_resolution():
    with pytest.raises(ValueError,match='resolution'):r.validate_raster_compatibility([meta(),meta(res=(2,2))])
    with pytest.raises(ValueError,match='alignment'):r.validate_raster_compatibility([meta(),meta(origin=(.5,10))])
    assert r.validate_raster_compatibility([meta(),meta(res=(2,2))],resolution=2)['z_units']=='m'
    assert r.validate_raster_compatibility([meta()],z_units='us-ft')['scale_factors']==pytest.approx([3937/1200])
