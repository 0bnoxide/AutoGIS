"""Montana State Library HFDEM inventory and archive acquisition (arcpy-free)."""
from __future__ import annotations

import copy
import json
import math
import re
import shutil
import time
from http.client import IncompleteRead
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

    def open(self, url, method='GET', data=None, *, retry=True):
        _official_url(url)
        retries=self.retries if retry else 0
        for attempt in range(retries + 1):
            try:
                response = urlopen(Request(url, data=data, method=method,
                    headers={'User-Agent': 'AutoGIS-MSL/1.0', 'Accept-Encoding': 'identity'}), timeout=self.timeout)
                _official_url(response.url)
                if response.status != 200:
                    response.close()
                    raise ValueError(f'MSL HTTP response was not 200: {url}')
                return response
            except HTTPError as exc:
                if not retry and exc.code in (408,429,500,502,503,504): raise
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == retries:
                    raise ValueError(f'MSL HTTP {exc.code}: {url}') from exc
            except (URLError, TimeoutError, ConnectionError):
                if attempt == retries:
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
        return self.open(url,retry=False)


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


def _validate_polygon_topology(polygon):
    """Reject crossing rings and invalid holes without optional GIS imports.

    Bounding-box sweep avoids comparing spatially separated edges. Worst-case
    dense intersections remain quadratic and fail on the first intersection.
    Each selected feature is validated independently; multipart features may
    overlap and are interpreted as a union by the processing backends.
    """
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a,b,c):return cross(a,b,c)==0 and min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(a[1],b[1])<=c[1]<=max(a[1],b[1])
    def intersects(a,b,c,d):
        ab1,ab2,cd1,cd2=cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
        return (ab1*ab2<0 and cd1*cd2<0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b)
    def inside(point,ring):
        x,y=point;result=False
        for (ax,ay),(bx,by) in zip(ring,ring[1:]):
            if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:result=not result
        return result
    edges=[]
    for r,ring in enumerate(polygon):
        if len(set(map(tuple,ring[:-1])))!=len(ring)-1:
            raise ValueError('Invalid AOI topology: repeated ring vertex')
        count=len(ring)-1
        for i,(a,b) in enumerate(zip(ring,ring[1:])):
            c=ring[(i+2)%count]
            if cross(a,b,c)==0 and (a[0]-b[0])*(c[0]-b[0])+(a[1]-b[1])*(c[1]-b[1])>0:
                raise ValueError('Invalid AOI topology: backtracking ring edge')
            edges.append((min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1]),r,i,a,b))
    active=[]
    for edge in sorted(edges):
        xmin,xmax,ymin,ymax,r,i,a,b=edge
        active=[e for e in active if e[1]>=xmin]
        for other in active:
            _,_,oymin,oymax,rr,j,c,d=other
            if oymax<ymin or ymax<oymin:continue
            if r==rr and (abs(i-j)==1 or {i,j}=={0,len(polygon[r])-2}):continue
            if intersects(a,b,c,d):raise ValueError('Invalid AOI topology: intersecting or touching rings')
        active.append(edge)
    for i,hole in enumerate(polygon[1:],1):
        if not inside(hole[0],polygon[0]):raise ValueError('Invalid AOI topology: hole lies outside exterior')
        if any(inside(hole[0],other) or inside(other[0],hole) for other in polygon[1:i]):
            raise ValueError('Invalid AOI topology: nested/overlapping holes')


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
        _validate_polygon_topology(polygon)
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
        return {**asdict(self), 'projects':[{**asdict(r),'quality_evidence':inventory_quality_evidence(r)} for r in self.projects], 'total_bytes':self.total_bytes, 'product':'HFDEM',
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
            if re.search(r'[\\/<>:"|?*\x00-\x1f]',name) or name[-1:] in (' ','.'):
                raise ValueError(f'Unsafe MSL project identifier: {name!r}')
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

# Archive acquisition intentionally does not import a raster engine.
@dataclass
class ArchiveDownload:
    path: Path
    archive: ArchivePlan
    sha256: str
    downloaded_at: str


@dataclass
class RasterSource:
    path: Path
    project: str
    archive_url: str
    archive_sha256: str
    member: str
    quad: str | None = None
    downloaded_at: str | None = None


def _sha256(path):
    import hashlib
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024**2),b''): digest.update(chunk)
    return digest.hexdigest()


def inspect_msl_archives(path, *, max_expanded_bytes=200*1024**3):
    """Verify every CRC, rejecting unsafe names/types before decompression."""
    import stat
    import zipfile
    seen=set()
    try:
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)>100000 or sum(i.file_size for i in entries)>max_expanded_bytes:
                raise ValueError('ZIP expanded size exceeds the safety/disk limit')
            for entry in entries:
                name=entry.orig_filename
                parts=name.rstrip('/').split('/')
                if (not name or name.startswith('/') or '\\' in name
                    or any(p in ('','.','..') or p[-1:] in (' ','.') or re.search(r'[<>:"|?*\x00-\x1f]',p)
                           or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',p) for p in parts)
                    or stat.S_ISLNK(entry.external_attr>>16) or entry.flag_bits & 1):
                    raise ValueError(f'Unsafe ZIP member: {name!r}')
                key=name.rstrip('/').casefold()
                if key in seen:
                    raise ValueError(f'Unsafe duplicate/case-colliding ZIP member: {name!r}')
                seen.add(key)
                if entry.file_size>1024**2 and entry.file_size>max(entry.compress_size,1)*10000:
                    raise ValueError(f'Unsafe ZIP compression ratio: {name}')
            bad=archive.testzip()
            if bad:
                raise ValueError(f'Corrupt ZIP member CRC: {bad}')
            return entries
    except (zipfile.BadZipFile,NotImplementedError,RuntimeError) as exc:
        raise ValueError(f'Invalid ZIP archive: {path}: {exc}') from exc


def _cached_download(archive, cache):
    path=cache/archive.name
    receipt=path.with_suffix(path.suffix+'.json')
    if not path.exists() and not receipt.exists(): return None
    if path.is_symlink() or receipt.is_symlink():
        raise ValueError(f'Unsafe cache symlink: {path}')
    if not path.is_file() or not receipt.is_file():
        raise FileExistsError(f'Unrecognized cache file/receipt: {path}; choose a new cache directory')
    try:
        data=json.loads(receipt.read_text(encoding='utf-8'))
        digest=_sha256(path)
        if (data['url']!=archive.url or data['sha256']!=digest
                or data['size_bytes']!=path.stat().st_size
                or (archive.size_bytes is not None and archive.size_bytes!=path.stat().st_size)
                or data.get('validators')!=archive.validators):
            raise ValueError('cache identity, content, or server validators differ')
        inspect_msl_archives(path)
        return ArchiveDownload(path,archive,digest,data['downloaded_at'])
    except (ValueError,KeyError) as exc:
        raise ValueError(f'Invalid cache entry {path}: {exc}; preserve it and choose a fresh cache directory') from exc


def download_msl_archives(plan, cache_dir, *, allow_large_download=False,
                          threshold_bytes=DEFAULT_THRESHOLD, client=None,
                          on_progress=None, sleep=time.sleep):
    """Stream validated archives; cache collisions never overwrite user files."""
    import hashlib
    import os
    import tempfile
    from datetime import datetime,timezone
    if not isinstance(threshold_bytes,(int,float)) or not math.isfinite(threshold_bytes) or threshold_bytes<=0:
        raise ValueError('Large-download threshold must be finite and positive')
    client=client or HTTPClient()
    cache=Path(cache_dir)
    for archive in plan.archives:
        if (not archive.name.lower().endswith('.zip') or re.search(r'[\\/<>:"|?*\x00-\x1f]',archive.name)
                or archive.name[-1:] in (' ','.')):
            raise ValueError(f'Unsafe cache archive filename: {archive.name!r}')
    cached=[_cached_download(a,cache) for a in plan.archives]
    missing=[a for a,c in zip(plan.archives,cached) if c is None]
    total=None if any(a.size_bytes is None for a in missing) else sum(a.size_bytes for a in missing)
    if missing and (total is None or total>threshold_bytes) and not allow_large_download:
        raise ValueError('Large or unknown-size download: inspect the plan and pass --allow-large-download to authorize')
    cache.mkdir(parents=True,exist_ok=True)
    if total is not None and shutil.disk_usage(cache).free<total+64*1024**2:
        raise ValueError('Insufficient disk space for archive downloads (plus 64 MiB reserve)')
    result=[]
    for archive,hit in zip(plan.archives,cached):
        if hit is not None:
            result.append(hit); continue
        target=cache/archive.name
        last_error=None
        for attempt in range(3):
            fd,tempname=tempfile.mkstemp(prefix='.'+archive.name+'.',suffix='.part',dir=cache)
            temp=Path(tempname)
            try:
                digest=hashlib.sha256(); count=0
                with os.fdopen(fd,'wb') as output, client.stream(archive.url) as response:
                    headers=_headers(response.headers)
                    if 'html' in headers.get('content-type','').lower():
                        raise ValueError('Archive download returned HTML')
                    expected=headers.get('content-length')
                    if expected is not None and not str(expected).isdigit():
                        raise ValueError('Invalid download Content-Length')
                    expected=int(expected) if expected else None
                    if archive.size_bytes is not None and expected is not None and archive.size_bytes!=expected:
                        raise ValueError('Download byte count changed after preflight; rebuild plan')
                    for key,value in archive.validators.items():
                        if headers.get(key) is not None and headers[key]!=value:
                            raise ValueError('Archive server validator changed after preflight; rebuild plan')
                    while True:
                        chunk=response.read(1024**2)
                        if not chunk: break
                        count+=len(chunk)
                        if (expected is not None and count>expected) or (archive.size_bytes is not None and count>archive.size_bytes):
                            raise ValueError('Download byte count exceeds advertised length')
                        if not allow_large_download and count>threshold_bytes:
                            raise ValueError('Download exceeds authorized threshold; use --allow-large-download')
                        output.write(chunk); digest.update(chunk)
                        if on_progress: on_progress(count,expected or archive.size_bytes)
                if (expected is not None and count!=expected) or (archive.size_bytes is not None and count!=archive.size_bytes):
                    raise ValueError('Download byte count does not match advertised length')
                inspect_msl_archives(temp)
                timestamp=datetime.now(timezone.utc).isoformat()
                # Exclusive publication prevents race-time overwrite on all platforms.
                os.link(temp,target)
                try:
                    receipt=target.with_suffix(target.suffix+'.json')
                    with receipt.open('x',encoding='utf-8') as handle:
                        json.dump({'url':archive.url,'size_bytes':count,'sha256':digest.hexdigest(),
                                   'downloaded_at':timestamp,'validators':archive.validators},handle,indent=2)
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
                result.append(ArchiveDownload(target,archive,digest.hexdigest(),timestamp))
                last_error=None
                break
            except (TimeoutError,ConnectionError,URLError,OSError,IncompleteRead) as exc:
                last_error=exc
                if isinstance(exc,FileExistsError) or attempt==2: raise
                sleep(min(2**attempt,4))
            finally:
                temp.unlink(missing_ok=True)
        if last_error: raise last_error
    return result


def select_msl_dem_rasters(archives, projects, work_dir):
    """Extract exactly attributed HFDEM products and exact companion metadata."""
    import zipfile
    selected=[]
    work=Path(work_dir)
    work.mkdir(parents=True,exist_ok=True)
    for downloaded in archives:
        entries=inspect_msl_archives(downloaded.path,max_expanded_bytes=shutil.disk_usage(work).free)
        names={e.filename:e for e in entries if not e.is_dir()}
        wanted=[]; other_project_hfdem=False
        for name in names:
            parts=name.split('/')
            if not name.lower().endswith(('.tif','.tiff')):
                continue
            is_hfdem=any(p.casefold()=='hfdem' for p in parts[:-1])
            if downloaded.archive.project:
                is_hfdem=True  # explicit official project Mosaics/HFDEM.zip only
            if not is_hfdem: continue
            project=downloaded.archive.project or parts[0]
            if project.casefold()=='quads':
                raise ValueError(f'HFDEM attribution is ambiguous for {name} in {downloaded.archive.url}; use an explicitly identified project mosaic')
            if project not in projects:
                other_project_hfdem=True
                continue
            wanted.append((name,project))
        if not wanted and other_project_hfdem:
            continue
        if not wanted:
            raise ValueError(f'No HFDEM for selected projects in {downloaded.archive.url}')
        # Unique directory per archive preserves duplicate quad filenames safely.
        destination=work/downloaded.sha256[:16]
        if destination.exists():
            raise FileExistsError(f'Extraction target already exists: {destination}')
        destination.mkdir()
        with zipfile.ZipFile(downloaded.path) as archive:
            for name,project in wanted:
                path=destination/name
                for member in (name,name+'.xml',name+'.aux.xml'):
                    if member not in names: continue
                    target=destination/member
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(member) as source,target.open('xb') as output:
                        shutil.copyfileobj(source,output,1024**2)
                selected.append(RasterSource(path,project,downloaded.archive.url,downloaded.sha256,name,
                                             downloaded.archive.quad,downloaded.downloaded_at))
    if not selected:
        raise ValueError('No HFDEM for selected projects in downloaded archives')
    return selected


def inventory_quality_evidence(record):
    """Publisher claims with exact field labels; no inferred units/confidence."""
    fields={f['name']:f for f in record.fields}
    evidence=[]
    for name,value in record.attributes.items():
        if value is None or not re.search(r'accuracy|rmse|pulse|quality|meets3dep',name,re.I): continue
        evidence.append({'field':name,'label':fields.get(name,{}).get('alias',name),'value':value,
            'raw_value':record.raw_attributes.get(name),'status':'publisher_reported',
            'units':'m' if name.casefold().endswith('_m') and 'density' not in name.casefold() else None,
            'confidence_level':None,'scope':'project-level; not a site-specific guarantee','source':record.source_url,
            'report_url':record.attributes.get('ReportLink'),'metadata_url':record.attributes.get('MetadataLink')})
    return evidence


@dataclass
class MSLResult:
    plan: DownloadPlan
    out_path: Path | None
    archives: list[ArchiveDownload]
    qa: object


def _publish_pair(staged, sidecar, out, *, overwrite):
    """Publish a prepared raster/JSON pair; restore old files on ordinary failure."""
    import os
    targets=[out,Path(str(out)+'.json')]
    sources=[staged,sidecar]
    backups={};published=[]
    try:
        for target in targets:
            if target.is_symlink(): raise ValueError(f'Refusing output symlink: {target}')
            if target.exists():
                if not target.is_file(): raise ValueError(f'Output target is not a regular file: {target}')
                if not overwrite: raise FileExistsError(f'Output exists: {target}')
                backup=staged.parent/(target.name+'.previous')
                os.replace(target,backup);backups[target]=backup
        for source,target in zip(sources,targets):
            # link is exclusive, unlike os.replace. Both paths are same-volume.
            os.link(source,target);published.append(target)
    except BaseException:
        for target in reversed(published): target.unlink(missing_ok=True)
        for target,backup in backups.items(): os.replace(backup,target)
        raise


def run_msl_download(*, bbox=None, aoi_path=None, geometry=None, out_path,
                     projects=(), cache_dir=None, source='quads', product='HFDEM',
                     overwrite=False, dry_run=False, download_only=False,
                     allow_large_download=False, threshold_bytes=DEFAULT_THRESHOLD,
                     output_crs=None, resolution=None, z_units='native',
                     client=None, on_progress=None, processor=None):
    """Shared CLI/Pro workflow. A download-only result is never labeled a DEM."""
    import os
    import tempfile
    from datetime import datetime,timezone
    from ..common.qa import QACollector,SEV_WARNING,SEV_INFO
    from .msl_raster import require_rasterio,process_msl_dem,Z_METERS
    aoi=resolve_msl_aoi(bbox=bbox,aoi_path=aoi_path,geometry=geometry)
    out=Path(out_path).absolute()
    if out.suffix.lower() not in ('.tif','.tiff'): raise ValueError('Output must be a GeoTIFF .tif or .tiff path')
    if product!='HFDEM': raise ValueError('Only HFDEM is supported')
    if z_units not in ('native',*Z_METERS): raise ValueError('Unsupported elevation units')
    if resolution is not None and (not math.isfinite(resolution) or resolution<=0):raise ValueError('Resolution must be finite and positive')
    if output_crs is not None and resolution is None:raise ValueError('Output CRS requires explicit output resolution in target CRS units')
    if not dry_run and not download_only:
        for path in (out,Path(str(out)+'.json')):
            if path.is_symlink(): raise ValueError(f'Refusing output symlink: {path}')
            if path.exists() and not path.is_file(): raise ValueError(f'Output target is not a regular file: {path}')
            if path.exists() and not overwrite: raise FileExistsError(f'Output exists: {path}; use --overwrite to replace')
        if processor is None:
            require_rasterio()
            if output_crs:
                from pyproj import CRS
                from pyproj.exceptions import CRSError
                try:
                    crs=CRS.from_user_input(output_crs)
                    if crs.is_compound or crs.is_vertical or len(crs.axis_info)!=2 or not (crs.is_projected or crs.is_geographic):raise ValueError('Output CRS must be horizontal; no vertical transformation is supported')
                except CRSError as exc:raise ValueError(f'Invalid output CRS: {output_crs}') from exc
            processor=process_msl_dem
    cache=Path(cache_dir).absolute() if cache_dir else out.parent/'.msl-cache'
    plan=build_msl_download_plan(aoi,projects=projects,cache_dir=cache,source=source,client=client)
    qa=QACollector()
    for warning in plan.warnings:qa.add(SEV_WARNING,'MSL_COVERAGE',warning)
    if dry_run:return MSLResult(plan,None,[],qa)
    archives=download_msl_archives(plan,cache,allow_large_download=allow_large_download,
        threshold_bytes=threshold_bytes,client=client,on_progress=on_progress)
    if download_only:
        qa.add(SEV_INFO,'MSL_DOWNLOAD_ONLY','Validated archives downloaded; no clipped DEM was produced')
        return MSLResult(plan,None,archives,qa)
    out.parent.mkdir(parents=True,exist_ok=True)
    lock=out.with_name('.'+out.name+'.msl.lock')
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix='.msl-',dir=out.parent) as temporary:
            work=Path(temporary)
            sources=select_msl_dem_rasters(archives,plan.selected_projects,work/'sources')
            # User's explicit project order is the documented overlap priority.
            selected_urls={s.archive_url for s in sources}
            for archive in archives:
                if archive.archive.url not in selected_urls:
                    qa.add(SEV_WARNING,'MSL_PROJECT_SELECTION',f'Archive contains only unselected-project HFDEM and was excluded: {archive.archive.url}')
            sources.sort(key=lambda s:(plan.selected_projects.index(s.project),s.quad or '',s.member))
            staged=work/'output.tif'
            processed=processor(sources,aoi,staged,output_crs=output_crs,resolution=resolution,z_units=z_units)
            if not staged.is_file() or staged.stat().st_size==0:raise ValueError('Raster processor did not produce a nonempty GeoTIFF')
            for warning in processed.get('warnings',[]):qa.add(SEV_WARNING,'MSL_RASTER_QA',warning)
            # Evidence links survive temporary extraction cleanup.
            for metadata in processed.get('sources',[]):
                source_item=next((s for s in sources if str(s.path)==metadata.get('path')),None)
                if source_item:
                    for evidence in metadata.get('vertical_evidence',[])+metadata.get('accuracy_evidence',[]):
                        local=evidence.get('source','')
                        suffix=local[len(str(source_item.path)):] if local.startswith(str(source_item.path)) else ''
                        evidence['source']=source_item.archive_url+'!'+source_item.member+suffix
                    metadata.pop('path',None)
            provenance={'source_agency':'Montana State Library','product':'HFDEM',
                'created_at':datetime.now(timezone.utc).isoformat(),'output_path':str(out),
                'output_sha256':_sha256(staged),'inventory':plan.to_dict(),'aoi':aoi,
                'archives':[{'url':a.archive.url,'sha256':a.sha256,'downloaded_at':a.downloaded_at,
                    'size_bytes':a.path.stat().st_size,'validators':a.archive.validators} for a in archives],
                **processed,'qa':[asdict(record) for record in qa.records],
                'accuracy_disclaimer':'Resolution is measured pixel spacing, not accuracy. Inventory/XML accuracy is publisher-reported, not independently verified; missing confidence and units remain unknown.'}
            side=work/'output.tif.json'
            side.write_text(json.dumps(provenance,indent=2,allow_nan=False),encoding='utf-8')
            _publish_pair(staged,side,out,overwrite=overwrite)
    finally:
        lock.unlink(missing_ok=True)
    return MSLResult(plan,out,archives,qa)
