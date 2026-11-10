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


def require_rasterio():
    try:
        import rasterio
        import pyproj
    except ImportError as exc:
        raise RuntimeError('Clipped headless DEM processing requires pip install "autogis[msl]"; use --download-only for archives, or use the ArcGIS Pro toolbox') from exc
    return rasterio


def process_msl_dem(sources, aoi, out_path, *, output_crs=None, resolution=None, z_units='native'):
    """Windowed mosaic/mask preserving native grids unless resampling is explicit.

    First source wins overlaps; provenance quantifies overlap and discrepancies.
    Working memory is bounded to one 512x512 block per input and output.
    """
    import numpy as np
    import shutil
    from contextlib import ExitStack
    from dataclasses import asdict
    from .msl_lidar import resolve_msl_aoi
    rasterio=require_rasterio()
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from rasterio.features import geometry_mask, bounds
    from rasterio.transform import Affine
    from rasterio.warp import transform_geom, Resampling
    from rasterio.vrt import WarpedVRT
    aoi=resolve_msl_aoi(geometry=aoi)
    out=Path(out_path)
    if out.exists(): raise FileExistsError(f'Output already exists: {out}')
    with ExitStack() as stack:
        datasets=[stack.enter_context(rasterio.open(source.path)) for source in sources]
        metadata=[]
        for source,ds in zip(sources,datasets):
            if ds.crs is None: raise ValueError(f'Raster CRS missing: {source.path}')
            if ds.transform.b or ds.transform.d or ds.transform.a<=0 or ds.transform.e>=0:
                raise ValueError('Rotated/flipped source grids require explicit preprocessing')
            horizontal=CRS.from_wkt(ds.crs.to_wkt()).to_2d()
            metadata.append({**asdict(source),'path':str(source.path),
                'horizontal_crs':horizontal.to_wkt(),'resolution':list(ds.res),
                'resolution_units':horizontal.axis_info[0].unit_name if horizontal.axis_info else None,
                'origin':[ds.transform.c,ds.transform.f], 'dtype':ds.dtypes[0], 'bands':ds.count,
                'nodata':ds.nodata if ds.nodata is None or math.isfinite(ds.nodata) else 'NaN',
                **inspect_vertical_metadata(source.path,ds.crs.to_wkt())})
        compatibility=validate_raster_compatibility(metadata,output_crs=output_crs,resolution=resolution,z_units=z_units)
        try:
            target_crs=CRS.from_user_input(output_crs or metadata[0]['horizontal_crs'])
        except CRSError as exc:
            raise ValueError(f'Invalid output CRS: {output_crs}') from exc
        if target_crs.is_compound or target_crs.is_vertical:
            raise ValueError('Specify a horizontal output CRS; vertical datum transformation is unsupported')
        target_geom=transform_geom('EPSG:4326',target_crs.to_wkt(),aoi,precision=-1)
        left,bottom,right,top=bounds(target_geom)
        rx,ry=(resolution,resolution) if resolution is not None else metadata[0]['resolution']
        origin_x,origin_y=metadata[0]['origin'] if output_crs is None else (0,0)
        left=origin_x+math.floor((left-origin_x)/rx+1e-8)*rx
        right=origin_x+math.ceil((right-origin_x)/rx-1e-8)*rx
        bottom=origin_y+math.floor((bottom-origin_y)/ry+1e-8)*ry
        top=origin_y+math.ceil((top-origin_y)/ry-1e-8)*ry
        width=round((right-left)/rx);height=round((top-bottom)/ry)
        if width<1 or height<1: raise ValueError('AOI is smaller than the output grid')
        dtype='float64' if any(m['dtype'] in ('float64','int32','uint32') for m in metadata) else 'float32'
        bytes_needed=width*height*np.dtype(dtype).itemsize
        disk=out.parent
        while not disk.exists():disk=disk.parent
        if bytes_needed+64*1024**2>shutil.disk_usage(disk).free:
            raise ValueError('Insufficient disk space for uncompressed output raster and processing reserve')
        transform=Affine(rx,0,left,0,-ry,top)
        resampling=Resampling.nearest if output_crs is None and resolution is None else Resampling.bilinear
        vrts=[stack.enter_context(WarpedVRT(ds,src_crs=metadata[i]['horizontal_crs'],crs=target_crs.to_wkt(),transform=transform,width=width,height=height,
                nodata=float('nan'),dtype=dtype,resampling=resampling)) for i,ds in enumerate(datasets)]
        profile={'driver':'GTiff','width':width,'height':height,'count':1,'dtype':dtype,
            'crs':target_crs.to_wkt(),'transform':transform,'nodata':float('nan'),
            'tiled':True,'blockxsize':512,'blockysize':512,'compress':'deflate','BIGTIFF':'IF_SAFER'}
        out.parent.mkdir(parents=True,exist_ok=True)
        aoi_cells=valid_cells=overlap_cells=0;max_difference=0.0
        try:
            with rasterio.open(out,'w',**profile) as dst:
                for _,window in dst.block_windows(1):
                    shape=(int(window.height),int(window.width))
                    mask=geometry_mask([target_geom],out_shape=shape,transform=dst.window_transform(window),invert=True,all_touched=False)
                    merged=np.full(shape,np.nan,dtype=dtype)
                    overlap=np.zeros(shape,dtype=bool)
                    for vrt,factor in zip(vrts,compatibility['scale_factors']):
                        values=vrt.read(1,window=window,masked=True).astype(dtype)*factor
                        usable=mask & ~np.ma.getmaskarray(values) & np.isfinite(values.data)
                        both=usable & np.isfinite(merged)
                        if both.any():
                            max_difference=max(max_difference,float(np.max(np.abs(values.data[both]-merged[both]))))
                        overlap |= both
                        take=usable & ~np.isfinite(merged)
                        merged[take]=values.data[take]
                    aoi_cells+=int(mask.sum());valid_cells+=int(np.isfinite(merged).sum());overlap_cells+=int(overlap.sum())
                    dst.write(merged,1,window=window)
            if not aoi_cells: raise ValueError('AOI contains no output pixel centers; choose an explicit finer resolution if appropriate')
            if not valid_cells: raise ValueError('No valid HFDEM cells cover the AOI; output not published')
        except BaseException:
            out.unlink(missing_ok=True)
            raise
    warnings=[]
    if valid_cells<aoi_cells:warnings.append(f'Incomplete raster coverage: {aoi_cells-valid_cells} of {aoi_cells} AOI pixel centers are NoData')
    if any(m['vertical_datum'] is None or m['z_units'] is None for m in metadata):
        warnings.append('Artifact vertical datum or elevation units are unknown; native values preserved, accuracy not independently assessed')
    if overlap_cells:warnings.append(f'{overlap_cells} overlapping cells; first selected source wins; largest difference {max_difference:g} output Z units')
    return {'sources':metadata,'output':{'horizontal_crs':target_crs.to_wkt(),'resolution':[rx,ry],
        'resolution_units':target_crs.axis_info[0].unit_name if target_crs.axis_info else None,
        'width':width,'height':height,'dtype':dtype,'nodata':'NaN',**compatibility},
        'coverage':{'aoi_cells':aoi_cells,'valid_cells':valid_cells,'fraction':valid_cells/aoi_cells,
            'complete':valid_cells==aoi_cells,'method':'output pixel centers inside true AOI polygon',
            'overlap_cells':overlap_cells,'max_overlap_difference':max_difference},
        'operations':[{'operation':'mosaic','priority':[s.project+':'+s.member for s in sources],'method':'first valid'},
            {'operation':'clip','geometry':aoi,'all_touched':False},
            {'operation':'horizontal_resampling','method':resampling.name,'explicit':output_crs is not None or resolution is not None},
            {'operation':'elevation_unit_conversion','scale_factors':compatibility['scale_factors'],'vertical_datum_transformation':False}],
        'warnings':warnings,'backend':f'rasterio {rasterio.__version__}'}
