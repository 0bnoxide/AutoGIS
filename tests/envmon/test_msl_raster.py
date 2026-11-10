import json
from pathlib import Path
import numpy as np
import pytest
rasterio=pytest.importorskip('rasterio')
from rasterio.transform import from_origin
from autogis.core.envmon import msl_lidar as m, msl_raster as r


def source(tmp_path,name='a',x=0,values=None,project='A',metadata=True):
    path=tmp_path/(name+'.tif')
    values=np.array(values if values is not None else [[1,2],[3,0]],dtype='float32')
    with rasterio.open(path,'w',driver='GTiff',width=values.shape[1],height=values.shape[0],count=1,dtype='float32',crs='EPSG:4326',transform=from_origin(x,2,1,1),nodata=0) as dst:dst.write(values,1)
    if metadata:path.with_suffix('.tif.xml').write_text('<metadata><altdatum>NAVD88</altdatum><altunits>meters</altunits></metadata>')
    return m.RasterSource(path,project,'https://ftpgeoinfo.msl.mt.gov/a.zip','abc',path.name)


def test_native_mosaic_partial_coverage_and_values(tmp_path):
    sources=[source(tmp_path),source(tmp_path,'b',2,[[5,6],[7,8]])]
    out=tmp_path/'out.tif';aoi=m.resolve_msl_aoi(bbox=(0,0,4,2))
    result=r.process_msl_dem(sources,aoi,out)
    with rasterio.open(out) as ds:
        assert ds.res==(1,1) and ds.shape==(2,4)
        np.testing.assert_allclose(ds.read(1),[[1,2,5,6],[3,np.nan,7,8]],equal_nan=True)
    assert result['coverage']['valid_cells']==7 and result['coverage']['aoi_cells']==8
    assert result['coverage']['complete'] is False
    assert result['output']['vertical_datum']=='NAVD88'
    assert result['sources'][0]['resolution']==[1,1]


def test_polygon_hole_and_unit_conversion(tmp_path):
    src=source(tmp_path,values=np.ones((4,4)),x=0)
    aoi={'type':'Polygon','coordinates':[[[0,-2],[4,-2],[4,2],[0,2],[0,-2]],[[1,-1],[1,1],[3,1],[3,-1],[1,-1]]]}
    out=tmp_path/'out.tif';result=r.process_msl_dem([src],aoi,out,z_units='us-ft')
    with rasterio.open(out) as ds:
        data=ds.read(1);assert np.isnan(data[1:3,1:3]).all()
        assert data[0,0]==pytest.approx(3937/1200)
    assert result['coverage']['aoi_cells']==12 and result['coverage']['complete']
    assert result['output']['z_units']=='us-ft' and result['output']['vertical_transformation'] is None


def test_unknown_native_metadata_warns_and_conversion_fails(tmp_path):
    src=source(tmp_path,metadata=False)
    result=r.process_msl_dem([src],m.resolve_msl_aoi(bbox=(0,0,2,2)),tmp_path/'native.tif')
    assert result['warnings'] and result['output']['z_units'] is None
    with pytest.raises(ValueError,match='units'):r.process_msl_dem([src],m.resolve_msl_aoi(bbox=(0,0,2,2)),tmp_path/'bad.tif',z_units='m')
    assert not (tmp_path/'bad.tif').exists()


def test_overlap_is_deterministic_and_reported(tmp_path):
    a=source(tmp_path,values=[[1,1],[1,1]]);b=source(tmp_path,'b',values=[[2,2],[2,2]])
    result=r.process_msl_dem([a,b],m.resolve_msl_aoi(bbox=(0,0,2,2)),tmp_path/'out.tif')
    assert result['coverage']['overlap_cells']==4
    assert result['coverage']['max_overlap_difference']==1
    with rasterio.open(tmp_path/'out.tif') as ds:assert (ds.read(1)==1).all()


def test_output_collision_and_explicit_resolution(tmp_path):
    src=source(tmp_path);out=tmp_path/'existing.tif';out.write_bytes(b'keep')
    with pytest.raises(FileExistsError):r.process_msl_dem([src],m.resolve_msl_aoi(bbox=(0,0,2,2)),out)
    assert out.read_bytes()==b'keep'
    result=r.process_msl_dem([src],m.resolve_msl_aoi(bbox=(0,0,2,2)),tmp_path/'fine.tif',resolution=.5)
    assert result['output']['resolution']==[.5,.5]


def test_invalid_crs_or_empty_aoi_fails_before_output(tmp_path):
    src=source(tmp_path);out=tmp_path/'bad.tif'
    with pytest.raises((ValueError,rasterio.errors.CRSError)):r.process_msl_dem([src],m.resolve_msl_aoi(bbox=(0,0,2,2)),out,output_crs='garbage',resolution=1)
    assert not out.exists()
