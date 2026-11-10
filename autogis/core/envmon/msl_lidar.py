"""Montana State Library HFDEM inventory and archive acquisition (arcpy-free)."""
from __future__ import annotations

import copy
import json
import math
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .opentopo import resolve_bbox

INVENTORY_URL = 'https://mslgis.mt.gov/arcgishosting/rest/services/GEOINFO/LidarInventory/MapServer'
DOWNLOAD_ROOT = 'https://ftpgeoinfo.msl.mt.gov/Data/Spatial/MSDI/Elevation/Lidar/'
DEFAULT_THRESHOLD = 1024 ** 3


class HTTPClient:
    """Bounded public-source HTTP; injectable at the JSON/HEAD/stream boundary."""
    def __init__(self, timeout=60, retries=2):
        self.timeout, self.retries = timeout, retries

    def open(self, url, method='GET', data=None):
        _official_url(url)
        for attempt in range(self.retries + 1):
            try:
                response = urlopen(Request(url, data=data, method=method,
                    headers={'User-Agent': 'AutoGIS-MSL/1.0', 'Accept-Encoding': 'identity'}), timeout=self.timeout)
                _official_url(response.url)
                if response.status != 200:
                    response.close()
                    raise ValueError(f'MSL HTTP response was not 200: {url}')
                return response
            except HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == self.retries:
                    raise ValueError(f'MSL HTTP {exc.code}: {url}') from exc
            except (URLError, TimeoutError, ConnectionError):
                if attempt == self.retries:
                    raise
            time.sleep(min(2 ** attempt, 4))

    def request_json(self, url, params=None):
        # POST avoids truncation of detailed polygon geometries in query URLs.
        params = {'f': 'json', **(params or {})}
        with self.open(url, 'POST', urlencode(params).encode('ascii')) as response:
            data = response.read(32 * 1024 ** 2 + 1)
        if len(data) > 32 * 1024 ** 2:
            raise ValueError('MSL JSON response exceeds 32 MiB safety limit')
        try:
            return json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f'MSL returned invalid JSON (possibly HTML): {url}') from exc

    def head(self, url):
        with self.open(url, 'HEAD') as response:
            return dict(response.headers)

    def stream(self, url):
        return self.open(url)


def _official_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('mslgis.mt.gov', 'ftpgeoinfo.msl.mt.gov')
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError(f'Expected an official MSL HTTPS URL: {url}')
    return url


def _json(client, url, params=None):
    data = client.request_json(url, params)
    if not isinstance(data, dict):
        raise ValueError(f'MSL JSON object expected: {url}')
    if data.get('error'):
        raise ValueError(f"MSL REST error at {url}: {data['error']}")
    return data


def _polygons(geometry):
    return [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']


def _ring_area(ring):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:])) / 2


def resolve_msl_aoi(*, bbox=None, aoi_path=None, geometry=None):
    """Return polygon geometry in WGS84, preserving multipart and hole rings."""
    if sum(x is not None for x in (bbox, aoi_path, geometry)) != 1:
        raise ValueError('Supply exactly one AOI: bbox, aoi_path or geometry')
    if bbox is not None:
        w,s,e,n = resolve_bbox(bbox=bbox)
        geometry = {'type':'Polygon','coordinates':[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}
    if aoi_path is not None:
        path = Path(aoi_path)
        if path.suffix.lower() == '.shp':
            try:
                import shapefile
                from pyproj import CRS, Transformer
            except ImportError as exc:
                raise RuntimeError('Shapefile polygon AOIs require pip install "autogis[msl]"') from exc
            prj = path.with_suffix('.prj')
            if not prj.exists():
                raise ValueError('Shapefile AOI requires a .prj spatial reference')
            transform = Transformer.from_crs(CRS.from_wkt(prj.read_text()), 4326, always_xy=True)
            with shapefile.Reader(str(path)) as reader:
                geoms = [s.__geo_interface__ for s in reader.shapes()]
            def project(v):
                if v and isinstance(v[0], (int,float)):
                    return list(transform.transform(v[0],v[1],errcheck=True))
                return [project(x) for x in v]
            geometry = {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':g['type'],'coordinates':project(g['coordinates'])}} for g in geoms]}
        else:
            geometry = json.loads(path.read_text(encoding='utf-8-sig'))
    geometry = copy.deepcopy(geometry)
    if not isinstance(geometry, dict):
        raise ValueError('AOI must be a GeoJSON Polygon or MultiPolygon')
    if geometry.get('crs'):
        raise ValueError('GeoJSON AOI must use WGS84 without a legacy CRS declaration')
    if geometry.get('type') == 'Feature':
        return resolve_msl_aoi(geometry=geometry.get('geometry'))
    if geometry.get('type') == 'FeatureCollection':
        polygons = []
        for feature in geometry.get('features', []):
            polygons.extend(_polygons(resolve_msl_aoi(geometry=feature)))
        geometry = {'type':'MultiPolygon','coordinates':polygons}
    if geometry.get('type') not in ('Polygon','MultiPolygon'):
        raise ValueError('AOI must contain polygons, not points or lines')
    if not geometry.get('coordinates'):
        raise ValueError('AOI polygon is empty')
    for polygon in _polygons(geometry):
        if not polygon:
            raise ValueError('AOI polygon is empty')
        for ring in polygon:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('AOI polygon rings must be closed with at least four positions')
            for point in ring:
                if (len(point) != 2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in point)
                        or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                    raise ValueError('AOI positions must be finite WGS84 longitude/latitude pairs')
            if not _ring_area(ring) or any(abs(a[0]-b[0])>180 for a,b in zip(ring,ring[1:])):
                raise ValueError('AOI polygon is degenerate or crosses the antimeridian')
    return geometry


def _esri_polygon(aoi):
    rings=[]
    for polygon in _polygons(aoi):
        for index,ring in enumerate(polygon):
            # Esri outer rings clockwise, holes counterclockwise.
            rings.append(list(reversed(ring)) if (_ring_area(ring)>0) == (index==0) else ring)
    return {'rings':rings, 'spatialReference':{'wkid':4326}}


@dataclass
class InventoryRecord:
    attributes: dict
    raw_attributes: dict
    source_url: str
    fields: list


@dataclass
class ArchivePlan:
    url: str
    name: str
    size_bytes: int | None
    quad: str | None = None
    project: str | None = None
    validators: dict = field(default_factory=dict)
    cached: bool = False


@dataclass
class DownloadPlan:
    aoi: dict
    projects: list[InventoryRecord]
    quads: list[InventoryRecord]
    selected_projects: list[str]
    archives: list[ArchivePlan]
    warnings: list[str] = field(default_factory=list)
    disk_free_bytes: int | None = None

    @property
    def total_bytes(self):
        return None if any(a.size_bytes is None for a in self.archives) else sum(a.size_bytes for a in self.archives)

    def to_dict(self):
        return {**asdict(self), 'total_bytes':self.total_bytes, 'product':'HFDEM',
                'source_agency':'Montana State Library', 'selection_policy':'explicit when multiple projects',
                'accuracy_note':'Pixel spacing and QualityLevel are not measured elevation accuracy. Unknown accuracy/confidence is not estimated.'}


def _query_inventory(layer, aoi, required, client):
    client = client or HTTPClient()
    url = f'{INVENTORY_URL}/{layer}'
    schema = _json(client,url)
    fields = schema.get('fields',[])
    names = {f['name'] for f in fields}
    oid = schema.get('objectIdField') or next((f['name'] for f in fields if f.get('type')=='esriFieldTypeOID'), 'OBJECTID')
    if not (set(required) | {oid}) <= names:
        raise ValueError(f'MSL inventory schema changed at {url}; missing {sorted((set(required)|{oid})-names)}')
    params = {'where':'1=1','geometry':json.dumps(_esri_polygon(aoi)), 'geometryType':'esriGeometryPolygon',
              'inSR':4326,'spatialRel':'esriSpatialRelIntersects','returnIdsOnly':'true'}
    result = _json(client, url+'/query', params)
    if result.get('exceededTransferLimit') or 'objectIds' not in result:
        raise ValueError('MSL returned incomplete inventory object IDs')
    ids = sorted(set(result['objectIds'] or []))
    page_size = min(int(schema.get('maxRecordCount',1000)),1000)
    if page_size < 1:
        raise ValueError('MSL invalid page-size schema')
    rows=[]
    domains={f['name']:{v['code']:v['name'] for v in (f.get('domain') or {}).get('codedValues',[])} for f in fields}
    for offset in range(0,len(ids),page_size):
        batch=ids[offset:offset+page_size]
        result=_json(client,url+'/query',{'objectIds':','.join(map(str,batch)),'outFields':'*','returnGeometry':'false'})
        features=result.get('features',[])
        if result.get('exceededTransferLimit') or {f.get('attributes',{}).get(oid) for f in features} != set(batch):
            raise ValueError('MSL returned incomplete inventory records; retry discovery')
        for feature in features:
            raw=feature['attributes']
            attrs={k:domains.get(k,{}).get(v,v) for k,v in raw.items()}
            rows.append(InventoryRecord(attrs,raw,url,fields))
    return rows


def query_msl_projects(aoi, *, client=None):
    return _query_inventory(2,resolve_msl_aoi(geometry=aoi),['ProjectName','BeDEM','HydroFlattened'],client)


def query_msl_quads(aoi, *, client=None):
    return _query_inventory(1,resolve_msl_aoi(geometry=aoi),['QCode_Text','Downloadable','DataCoverage'],client)


def resolve_msl_download_urls(quad_code):
    code=str(quad_code).lower().strip()
    if not re.fullmatch(r'\d{5}[a-h][1-8]',code):
        raise ValueError(f'Invalid MSL quadrangle identifier: {quad_code!r}')
    return DOWNLOAD_ROOT+'Quads/'+code+'.zip'


def _headers(headers):
    return {k.lower():v for k,v in headers.items()}


def build_msl_download_plan(aoi, *, projects=(), cache_dir=None, source='quads', client=None):
    aoi=resolve_msl_aoi(geometry=aoi)
    client=client or HTTPClient()
    records=query_msl_projects(aoi,client=client)
    quads=query_msl_quads(aoi,client=client)
    available={r.attributes['ProjectName']:r for r in records if str(r.attributes.get('BeDEM','')).casefold()=='available for download' and str(r.attributes.get('HydroFlattened','')).casefold()=='yes'}
    if not available:
        details='; '.join(f"{r.attributes.get('ProjectName')}: {r.attributes.get('BeDEM')}, HFDEM={r.attributes.get('HydroFlattened')}" for r in records)
        raise ValueError('No downloadable MSL HFDEM coverage. '+details)
    selected=list(dict.fromkeys(projects))
    if not selected:
        if len(available)>1:
            raise ValueError('Multiple MSL projects intersect AOI; select explicitly with --project: '+', '.join(sorted(available)))
        selected=list(available)
    if set(selected)-available.keys():
        raise ValueError('Selected project is unavailable or does not intersect AOI: '+', '.join(sorted(set(selected)-available.keys())))
    plan=DownloadPlan(aoi,records,quads,selected,[])
    candidates={}
    if source=='quads':
        for record in quads:
            attrs=record.attributes
            if str(attrs.get('Downloadable','')).casefold()!='yes':
                plan.warnings.append(f"Quadrangle {attrs.get('QCode_Text')} not downloadable: {attrs.get('DataCoverage')}")
                continue
            url=resolve_msl_download_urls(attrs['QCode_Text'])
            candidates[url]=(None,str(attrs['QCode_Text']).lower())
            if attrs.get('DataCoverage')!='Complete Coverage':
                plan.warnings.append(f"Quadrangle {attrs['QCode_Text']}: {attrs.get('DataCoverage','unknown coverage')}; raster coverage must be measured")
        if not candidates:
            raise ValueError('No downloadable MSL quadrangle coverage; inspect project availability')
    elif source=='projects':
        for name in selected:
            url=str(available[name].attributes.get('ProjectDownload') or '')
            expected=DOWNLOAD_ROOT+'Projects/'+name+'/'
            if url.rstrip('/')+'/' != expected:
                raise ValueError(f'Cannot establish official project mosaic directory for {name}: {url}')
            candidates[expected+'Mosaics/HFDEM.zip']=(name,None)
    else:
        raise ValueError('Archive source must be quads or projects')
    for url,(project,quad) in sorted(candidates.items()):
        headers=_headers(client.head(url))
        if 'html' in headers.get('content-type','').lower():
            raise ValueError(f'MSL archive URL returned HTML: {url}')
        length=headers.get('content-length')
        if length is not None and (not str(length).isdigit() or int(length)<=0):
            raise ValueError(f'MSL archive has invalid Content-Length: {url}')
        name=f'{quad}.zip' if quad else f'{project}_HFDEM.zip'
        archive=ArchivePlan(url,name,int(length) if length else None,quad,project,
                            {k:headers[k] for k in ('etag','last-modified') if headers.get(k)})
        if cache_dir:
            archive.cached=(Path(cache_dir)/name).is_file() and (Path(cache_dir)/(name+'.json')).is_file()
        plan.archives.append(archive)
    if cache_dir:
        disk=Path(cache_dir).absolute()
        while not disk.exists(): disk=disk.parent
        plan.disk_free_bytes=shutil.disk_usage(disk).free
    return plan
