"""Artifact metadata and optional rasterio processing for MSL HFDEM data.

Inventory native delivery units are never a substitute for distributed raster
metadata. Quality levels and reported accuracy are evidence, not guarantees.
"""
from __future__ import annotations
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

Z_METERS = {'m':1.0,'int-ft':0.3048,'us-ft':1200/3937}


def _unit(name):
    name=re.sub(r'[_\s-]+',' ',name.strip().casefold())
    if name in ('meter','meters','metre','metres','m'): return 'm'
    if name in ('foot','feet','international foot','international feet','int feet','ft'): return 'int-ft'
    if name in ('us survey foot','us survey feet','foot us','us feet','feet us','ftus'): return 'us-ft'
    return None


def _datum(name):
    compact=re.sub('[^a-z0-9]','',name.casefold())
    if 'navd88' in compact or 'northamericanverticaldatum1988' in compact: return 'NAVD88'
    if 'ngvd29' in compact or 'nationalgeodeticverticaldatum1929' in compact: return 'NGVD29'
    return name.strip() or None


def _vertical_wkt(wkt):
    # Only parse a vertical CRS subtree, never the horizontal UNIT token.
    found=[]
    for match in re.finditer(r'\b(?:VERTCS|VERT_CS|VERTCRS)\s*\[',wkt,re.I):
        depth=1; quoted=False; end=match.end()
        for end in range(match.end(),len(wkt)):
            char=wkt[end]
            if char=='"': quoted=not quoted
            if quoted: continue
            if char=='[':depth+=1
            if char==']':depth-=1
            if depth==0:break
        block=wkt[match.start():end+1]
        datum=re.search(r'(?:VERT_DATUM|VDATUM)\s*\[\s*"([^"]+)"',block,re.I)
        unit=re.search(r'(?:LENGTHUNIT|UNIT)\s*\[\s*"([^"]+)"\s*,\s*([0-9.eE+-]+)',block,re.I)
        if datum and unit:
            factor=float(unit.group(2))
            units=next((k for k,v in Z_METERS.items() if math.isclose(v,factor,rel_tol=1e-10)),None)
            if units is None: raise ValueError(f'Unsupported vertical length unit: {unit.group(1)}')
            found.append((_datum(datum.group(1)),units))
    return found


def inspect_vertical_metadata(path, crs_wkt):
    path=Path(path)
    evidence=[]; references=[]; accuracy=[]
    for datum,units in _vertical_wkt(crs_wkt or ''):
        references.append((datum,units)); evidence.append({'source':str(path),'kind':'raster_vertical_crs','datum':datum,'z_units':units})
    for xmlpath in (path.with_suffix(path.suffix+'.xml'),path.with_suffix(path.suffix+'.aux.xml')):
        if not xmlpath.exists(): continue
        if xmlpath.stat().st_size>32*1024**2: raise ValueError('Raster metadata XML exceeds 32 MiB safety limit')
        raw=xmlpath.read_bytes()
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError(f'Unsafe XML declaration in {xmlpath}')
        try: root=ET.fromstring(raw)
        except ET.ParseError as exc: raise ValueError(f'Invalid raster metadata XML: {xmlpath}') from exc
        tags={}
        for node in root.iter():
            tag=node.tag.rsplit('}',1)[-1].casefold()
            text=' '.join(' '.join(node.itertext()).split())
            if text: tags.setdefault(tag,[]).append(text)
            if tag in ('vertacc','horizacc','posacc','lineage') and text:
                # Keep report prose intact; do not manufacture a statistic/unit/confidence.
                accuracy.append({'source':str(xmlpath),'element':tag,'text':text,'status':'publisher_reported'})
        datums=tags.get('altdatum',[])
        units=tags.get('altunits',[])
        for datum in datums:
            for unit in units:
                normalized=_unit(unit)
                if normalized:
                    pair=(_datum(datum),normalized); references.append(pair)
                    evidence.append({'source':str(xmlpath),'kind':'FGDC_altitude','datum':pair[0],'z_units':pair[1]})
        # ArcGIS distribution metadata can carry the only compound CRS in its
        # DefineProjection history. Retain that lower-level source explicitly.
        for datum,unit in _vertical_wkt(' '.join(root.itertext())):
            references.append((datum,unit)); evidence.append({'source':str(xmlpath),'kind':'metadata_vertical_wkt','datum':datum,'z_units':unit})
    unique=set(references)
    if len(unique)>1:
        raise ValueError(f'Vertical metadata conflict for {path}: {sorted(unique)}')
    datum,units=next(iter(unique)) if unique else (None,None)
    return {'vertical_datum':datum,'z_units':units,'vertical_evidence':evidence,'accuracy_evidence':accuracy,
            'confidence':'not independently assessed','vertical_metadata_status':'artifact_reported' if unique else 'unknown'}


def validate_raster_compatibility(metadata, *, output_crs=None, resolution=None, z_units='native'):
    if not metadata: raise ValueError('No HFDEM rasters to process')
    if z_units not in ('native',*Z_METERS): raise ValueError('Unsupported output Z units')
    if resolution is not None and (not isinstance(resolution,(int,float)) or not math.isfinite(resolution) or resolution<=0):
        raise ValueError('Output resolution must be finite and positive')
    if any(m.get('bands')!=1 or m.get('dtype') not in ('float32','float64','int16','int32','uint16','uint32') for m in metadata):
        raise ValueError('HFDEM rasters must be single-band numeric elevation rasters')
    if any(not m.get('horizontal_crs') or len(m.get('resolution',[]))!=2 or any(not math.isfinite(v) or v<=0 for v in m['resolution']) for m in metadata):
        raise ValueError('HFDEM horizontal CRS/resolution is missing or invalid')
    datums={m.get('vertical_datum') for m in metadata}
    units={m.get('z_units') for m in metadata}
    projects={m['project'] for m in metadata}
    if len(datums)>1: raise ValueError('Incompatible vertical datum metadata; no vertical transformation is performed')
    if len(projects)>1 and (None in datums or None in units):
        raise ValueError('Cross-project mosaic has unknown vertical reference; verify source metadata first')
    if len(units)>1: raise ValueError('Incompatible source elevation units; normalize verified sources separately')
    if z_units!='native' and None in units:
        raise ValueError('Cannot convert unknown elevation units; verify artifact metadata first')
    first=metadata[0]
    if output_crs is None and any(m['horizontal_crs']!=first['horizontal_crs'] for m in metadata):
        raise ValueError('Different horizontal CRSs require explicit output CRS and resolution')
    if output_crs is not None and resolution is None:
        raise ValueError('Horizontal reprojection requires explicit output resolution in target CRS units')
    if resolution is None:
        for m in metadata:
            if not all(math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-8) for a,b in zip(m['resolution'],first['resolution'])):
                raise ValueError('Different native resolution requires explicit output resolution')
            for origin,base,size in zip(m['origin'],first['origin'],first['resolution']):
                cells=(origin-base)/size
                if not math.isclose(cells,round(cells),abs_tol=1e-5):
                    raise ValueError('Different native grid alignment requires explicit output resolution')
    output_units=first.get('z_units') if z_units=='native' else z_units
    factor=1.0 if z_units=='native' else Z_METERS[first['z_units']]/Z_METERS[z_units]
    return {'z_units':output_units,'vertical_datum':first.get('vertical_datum'),'scale_factors':[factor]*len(metadata),
            'vertical_transformation':None}
