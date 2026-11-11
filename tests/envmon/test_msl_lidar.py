"""MSL inventory contract tests. HTTP fixtures model public service schemas."""
import json
import pytest
from autogis.core.envmon import msl_lidar as m

BBOX = (-107.1, 44.9, -107.0, 45.0)

def schema(layer):
    names = (["OBJECTID", "ProjectName", "BeDEM", "HydroFlattened", "ProjectDownload", "QualityLevel", "NativeVerticalUnits"] if layer == 2 else ["OBJECTID", "QCode_Text", "Name", "Downloadable", "DataCoverage"])
    return {"objectIdField": "OBJECTID", "maxRecordCount": 1, "fields": [{"name": n, "type": "esriFieldTypeString", "domain": {"codedValues": [{"code": 1, "name": "Available for Download"}] } if n == "BeDEM" else None} for n in names]}

def project(name="PROJECT_A", oid=1, available=1):
    return {"attributes": {"OBJECTID": oid, "ProjectName": name, "BeDEM": available, "HydroFlattened": "Yes", "ProjectDownload": "https://ftpgeoinfo.msl.mt.gov/Data/Spatial/MSDI/Elevation/Lidar/Projects/" + name + "/", "QualityLevel": "QL2", "NativeVerticalUnits": "US feet"}}

def quad(code="44107H1", oid=1):
    return {"attributes": {"OBJECTID": oid, "QCode_Text": code, "Name": "Monarch", "Downloadable": "Yes", "DataCoverage": "Partial Coverage"}}

class Inventory:
    def __init__(self, projects=None, quads=None, size=1024):
        self.features = {2: projects if projects is not None else [project()], 1: quads if quads is not None else [quad()]}
        self.calls = []
        self.size = size
    def request_json(self, url, params=None):
        self.calls.append((url, params))
        layer = int(url.rstrip('/').split('/')[-2 if url.endswith('/query') else -1])
        if not url.endswith('/query'):
            return schema(layer)
        if params.get('returnIdsOnly') == 'true':
            return {"objectIds": [f['attributes']['OBJECTID'] for f in self.features[layer]]}
        ids = {int(i) for i in params['objectIds'].split(',')}
        return {"features": [f for f in self.features[layer] if f['attributes']['OBJECTID'] in ids]}
    def head(self, url):
        self.calls.append((url, 'HEAD'))
        return {'Content-Length': str(self.size), 'ETag': '"fixture"', 'Content-Type': 'application/zip'} if self.size is not None else {'Content-Type': 'application/zip'}


def test_bbox_geometry_and_invalid_inputs():
    aoi = m.resolve_msl_aoi(bbox=BBOX)
    assert aoi['type'] == 'Polygon'
    assert aoi['coordinates'][0][0] == [-107.1, 44.9]
    for bbox in [(0,0,0,1), (170,0,-170,1), (0,0,float('nan'),1)]:
        with pytest.raises(ValueError): m.resolve_msl_aoi(bbox=bbox)
    with pytest.raises(ValueError): m.resolve_msl_aoi(bbox=BBOX, geometry=aoi)


def test_polygon_holes_survive_geojson_and_rest_query(tmp_path):
    geo = {"type": "Polygon", "coordinates": [[[-107.1,44.9],[-107,44.9],[-107,45],[-107.1,45],[-107.1,44.9]], [[-107.08,44.92],[-107.08,44.98],[-107.02,44.98],[-107.02,44.92],[-107.08,44.92]]]}
    path = tmp_path/'aoi.geojson'; path.write_text(json.dumps({'type':'Feature','properties':{},'geometry':geo}))
    aoi = m.resolve_msl_aoi(aoi_path=path)
    assert aoi == geo
    client = Inventory()
    records = m.query_msl_projects(aoi, client=client)
    query = next(p for u,p in client.calls if u.endswith('/query'))
    assert query['inSR'] == 4326 and query['spatialRel'] == 'esriSpatialRelIntersects'
    assert len(json.loads(query['geometry'])['rings']) == 2
    assert records[0].attributes['BeDEM'] == 'Available for Download'
    assert records[0].raw_attributes['BeDEM'] == 1


@pytest.mark.parametrize('geometry', [{"type":"Point","coordinates":[0,0]}, {"type":"Polygon","coordinates":[]}, {"type":"Polygon","coordinates":[[[0,0],[1,0],[0,1]]]}])
def test_invalid_polygon_rejected(geometry):
    with pytest.raises(ValueError): m.resolve_msl_aoi(geometry=geometry)


def test_inventory_chunks_ids_and_rejects_incomplete_response():
    client = Inventory(projects=[project(oid=1),project('PROJECT_B',2)])
    records = m.query_msl_projects(m.resolve_msl_aoi(bbox=BBOX),client=client)
    assert len(records) == 2
    assert len([1 for u,p in client.calls if isinstance(p,dict) and 'objectIds' in p]) == 2
    original=client.request_json
    client.request_json=lambda u,params=None: {'features':[]} if params and 'objectIds' in params else original(u,params)
    with pytest.raises(ValueError,match='incomplete'): m.query_msl_projects(m.resolve_msl_aoi(bbox=BBOX),client=client)


def test_rest_error_and_schema_drift_fail_actionably():
    client=Inventory(); client.request_json=lambda *a,**kw: {'error':{'code':400,'message':'bad geometry'}}
    with pytest.raises(ValueError,match='bad geometry'): m.query_msl_projects(m.resolve_msl_aoi(bbox=BBOX),client=client)
    client.request_json=lambda *a,**kw: {'fields':[]}
    with pytest.raises(ValueError,match='schema'): m.query_msl_projects(m.resolve_msl_aoi(bbox=BBOX),client=client)


def test_plan_deduplicates_quad_urls_and_retains_source_evidence(tmp_path):
    client=Inventory(quads=[quad(oid=1),quad(oid=2)])
    plan=m.build_msl_download_plan(m.resolve_msl_aoi(bbox=BBOX),client=client,cache_dir=tmp_path/'not-created')
    assert len(plan.archives)==1
    assert plan.archives[0].url.endswith('/44107h1.zip')
    assert plan.total_bytes==1024
    assert plan.to_dict()['projects'][0]['attributes']['QualityLevel']=='QL2'
    assert any('Partial' in w for w in plan.warnings)
    assert not (tmp_path/'not-created').exists()


def test_multiple_projects_need_selection_and_unknown_selection_rejected():
    client=Inventory(projects=[project(),project('PROJECT_B',2)])
    aoi=m.resolve_msl_aoi(bbox=BBOX)
    with pytest.raises(ValueError,match='--project'): m.build_msl_download_plan(aoi,client=client)
    plan=m.build_msl_download_plan(aoi,projects=['PROJECT_A'],client=client)
    assert plan.selected_projects==['PROJECT_A']
    with pytest.raises(ValueError,match='UNKNOWN'): m.build_msl_download_plan(aoi,projects=['UNKNOWN'],client=client)


def test_request_only_and_no_quad_coverage():
    aoi=m.resolve_msl_aoi(bbox=BBOX)
    with pytest.raises(ValueError,match='Request Only'): m.build_msl_download_plan(aoi,client=Inventory(projects=[project(available='Request Only')]))
    with pytest.raises(ValueError,match='quadrangle'): m.build_msl_download_plan(aoi,client=Inventory(quads=[]))


def test_missing_or_html_archive_rejected_and_unknown_size_recorded():
    aoi=m.resolve_msl_aoi(bbox=BBOX)
    client=Inventory(); client.head=lambda url: {'Content-Type':'text/html'}
    with pytest.raises(ValueError,match='HTML'): m.build_msl_download_plan(aoi,client=client)
    client=Inventory(size=None)
    assert m.build_msl_download_plan(aoi,client=client).total_bytes is None


def test_quad_url_validation_and_project_archive_mode():
    assert m.resolve_msl_download_urls('44107H1').endswith('44107h1.zip')
    for bad in ['../other','44107h1.zip','ABC', '44107h1?x']:
        with pytest.raises(ValueError): m.resolve_msl_download_urls(bad)
    plan=m.build_msl_download_plan(m.resolve_msl_aoi(bbox=BBOX),client=Inventory(),source='projects')
    assert plan.archives[0].url.endswith('/PROJECT_A/Mosaics/HFDEM.zip')


@pytest.mark.parametrize('rings', [
    [[[0,0],[2,0],[2,2],[0,2],[0,0]],[[3,0],[4,0],[4,1],[3,1],[3,0]]],
    [[[0,-1],[3,2],[0,2],[2,-1],[0,-1]]],
    [[[0,0],[4,0],[4,4],[0,4],[0,0]],[[1,1],[3,1],[3,3],[1,3],[1,1]],[[1.5,1.5],[2,1.5],[2,2],[1.5,2],[1.5,1.5]]],
])
def test_invalid_polygon_topology_is_rejected_before_query(rings):
    with pytest.raises(ValueError,match='topology'):
        m.resolve_msl_aoi(geometry={'type':'Polygon','coordinates':rings})


def test_project_archive_filename_cannot_escape_cache():
    client=Inventory(projects=[project('../escape')])
    with pytest.raises(ValueError,match='project identifier'):
        m.build_msl_download_plan(m.resolve_msl_aoi(bbox=BBOX),source='projects',client=client)


@pytest.mark.parametrize('geometry', [
    {'type':'FeatureCollection','features':None},
    {'type':'FeatureCollection','features':1},
    {'type':'FeatureCollection','features':{'type':'Feature'}},
    {'type':'Polygon','coordinates':1},
    {'type':'Polygon','coordinates':{'ring':[]}},
    {'type':'Polygon','coordinates':[1]},
    {'type':'Polygon','coordinates':[None]},
    {'type':'Polygon','coordinates':[[1,2,3,1]]},
    {'type':'Polygon','coordinates':[[None,None,None,None]]},
    {'type':'MultiPolygon','coordinates':[1]},
    {'type':'MultiPolygon','coordinates':[[1]]},
    {'type':'Polygon','coordinates':[[[False,0],[1,0],[1,1],[False,0]]]},
    {'type':'Polygon','coordinates':[[[0,0],[True,0],[1,1],[0,0]]]},
    {'type':'Polygon','coordinates':[[[0,0],[10**400,0],[1,1],[0,0]]]},
])
def test_malformed_geojson_file_fails_cleanly_before_inventory(tmp_path, monkeypatch, geometry):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    path=tmp_path/'aoi.geojson'
    path.write_text(json.dumps(geometry),encoding='utf-8')
    original=path.read_bytes()
    client=Inventory()
    monkeypatch.setattr(m,'HTTPClient',lambda:client)
    with pytest.raises(ValueError):
        m.resolve_msl_aoi(aoi_path=path)
    out=tmp_path/'out.tif'
    result=CliRunner().invoke(autogis,['envmon','download-msl-dem','--aoi',str(path),
        '--out',str(out),'--dry-run'])
    assert result.exit_code==1 and 'Error:' in result.output
    assert 'Traceback' not in result.output
    assert client.calls==[] and not out.exists()
    assert path.read_bytes()==original


def test_feature_collection_preserves_valid_multipart_and_holes():
    polygon=m.resolve_msl_aoi(bbox=BBOX)
    hole=[[-107.08,44.92],[-107.08,44.98],[-107.02,44.98],[-107.02,44.92],[-107.08,44.92]]
    polygon['coordinates'].append(hole)
    other=m.resolve_msl_aoi(bbox=(-106.9,44.9,-106.8,45))
    multi={'type':'MultiPolygon','coordinates':[polygon['coordinates'],other['coordinates']]}
    collection={'type':'FeatureCollection','features':[{'type':'Feature','geometry':multi}]}
    assert m.resolve_msl_aoi(geometry=collection)==multi
