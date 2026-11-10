import json
from types import SimpleNamespace as NS
from pathlib import Path
import pytest
from autogis.adapters import toolbox_core as t

class Cursor:
    def __init__(self,rows):self.rows=rows
    def __enter__(self):return iter(self.rows)
    def __exit__(self,*args):pass

class Geometry:
    def __init__(self,rings):self.rings=rings;self.spatialReference=NS(name='WGS 1984',factoryCode=4326)
    @property
    def JSON(self):return json.dumps({'rings':self.rings,'spatialReference':{'wkid':4326}})
    def projectAs(self,*args):return self


def test_feature_layer_selection_preserves_holes_and_disjoint_parts():
    rings=[[[0,0],[0,4],[4,4],[4,0],[0,0]],[[1,1],[3,1],[3,3],[1,3],[1,1]]]
    seen=[]
    def cursor(layer,fields):seen.append(layer);return Cursor([(Geometry(rings),)])
    arc=NS(da=NS(SearchCursor=cursor),SpatialReference=lambda code:NS(name='WGS 1984',factoryCode=code))
    aoi=t.resolve_msl_arcpy_aoi(arc,'Feature layer (selection if any)',layer='selected layer')
    assert seen==['selected layer']
    assert aoi['type']=='MultiPolygon' and len(aoi['coordinates'][0])==2


def test_empty_selection_and_missing_active_map_fail():
    arc=NS(da=NS(SearchCursor=lambda *a:Cursor([])),SpatialReference=lambda code:NS(name='WGS 1984',factoryCode=code),mp=NS(ArcGISProject=lambda x:NS(activeView=None)))
    with pytest.raises(ValueError,match='features'):t.resolve_msl_arcpy_aoi(arc,'Feature layer (selection if any)',layer='x')
    with pytest.raises(ValueError,match='active map'):t.resolve_msl_arcpy_aoi(arc,'Active map extent')


def test_manual_aoi_and_polygon_mask_hole():
    import numpy as np
    aoi=t.resolve_msl_arcpy_aoi(None,'Manual bbox',bbox='0 0 4 4')
    assert aoi['coordinates'][0][0]==[0,0]
    rings=[[[0,0],[0,4],[4,4],[4,0],[0,0]],[[1,1],[3,1],[3,3],[1,3],[1,1]]]
    mask=t.msl_polygon_center_mask(rings,0,4,1,1,4,4)
    assert mask.sum()==12 and not mask[1:3,1:3].any()


def test_toolbox_has_required_msl_parameters_and_preserves_opentopo():
    text=Path('autogis/adapters/toolbox.pyt').read_text()
    assert 'class DownloadMSLDEM' in text and 'class DownloadOpenTopoDEM' in text
    # Structural check complements live Pro Parameter construction QA.
    for name in ['large_download_gib','projects','preview','output_resolution','z_units']:
        assert '"'+name+'"' in text
