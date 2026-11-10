import json
from pathlib import Path
from click.testing import CliRunner
import pytest
from autogis.adapters.cli import autogis
from autogis.core.envmon import msl_lidar as m
from tests.envmon.test_msl_archives import Client,archive_bytes
from tests.envmon.test_msl_lidar import BBOX


def test_cli_help_and_unchanged_opentopo():
    result=CliRunner().invoke(autogis,['envmon','download-msl-dem','--help'])
    assert result.exit_code==0 and '--project' in result.output
    assert '--allow-large-download' in result.output and '--z-units' in result.output
    assert CliRunner().invoke(autogis,['envmon','download-dem','--help']).exit_code==0


def test_dry_run_reports_accuracy_and_creates_nothing(tmp_path):
    client=Client(archive_bytes());out=tmp_path/'new'/'out.tif'
    result=m.run_msl_download(bbox=BBOX,out_path=out,client=client,dry_run=True)
    assert result.plan.total_bytes>0 and result.out_path is None
    assert not out.parent.exists() and client.gets==0
    assert result.plan.to_dict()['projects'][0]['quality_evidence']


def test_download_only_is_not_a_dem(tmp_path):
    client=Client(archive_bytes())
    result=m.run_msl_download(bbox=BBOX,out_path=tmp_path/'out.tif',cache_dir=tmp_path/'cache',client=client,download_only=True)
    assert result.out_path is None and len(result.archives)==1
    assert not (tmp_path/'out.tif').exists()


def test_output_provenance_and_processing_failure_preserves_pair(tmp_path):
    client=Client(archive_bytes());out=tmp_path/'out.tif'
    def processor(sources,aoi,path,**kw):
        path.write_bytes(b'processed raster')
        return {'output':{'z_units':None},'coverage':{'complete':False},'warnings':['unknown units'],'sources':[]}
    result=m.run_msl_download(bbox=BBOX,out_path=out,cache_dir=tmp_path/'cache',client=client,processor=processor)
    side=Path(str(out)+'.json');metadata=json.loads(side.read_text())
    assert metadata['source_agency']=='Montana State Library'
    assert metadata['archives'][0]['sha256']
    assert metadata['inventory']['projects'][0]['quality_evidence'][0]['status']=='publisher_reported'
    assert result.qa.records and out.read_bytes()==b'processed raster'
    old_side=side.read_bytes()
    def bad(*a,**k):raise RuntimeError('processing failed')
    with pytest.raises(RuntimeError,match='processing failed'):
        m.run_msl_download(bbox=BBOX,out_path=out,cache_dir=tmp_path/'cache',client=client,processor=bad,overwrite=True)
    assert out.read_bytes()==b'processed raster' and side.read_bytes()==old_side
    with pytest.raises(FileExistsError):m.run_msl_download(bbox=BBOX,out_path=out,client=client,processor=processor)


def test_cli_dry_run_and_mutual_exclusion(monkeypatch,tmp_path):
    client=Client(archive_bytes());monkeypatch.setattr(m,'HTTPClient',lambda:client)
    args=['envmon','download-msl-dem','--bbox',*map(str,BBOX),'--out',str(tmp_path/'out.tif'),'--dry-run']
    result=CliRunner().invoke(autogis,args)
    assert result.exit_code==0,result.output
    assert '44107h1' in result.output and 'dry run' in result.output.lower()
    assert not (tmp_path/'out.tif').exists()


def test_backend_preflight_before_download(monkeypatch,tmp_path):
    from autogis.core.envmon import msl_raster
    client=Client(archive_bytes())
    def missing():raise RuntimeError('pip install autogis[msl]')
    monkeypatch.setattr(msl_raster,'require_rasterio',missing)
    with pytest.raises(RuntimeError,match='pip install'):m.run_msl_download(bbox=BBOX,out_path=tmp_path/'out.tif',client=client)
    assert client.gets==0
