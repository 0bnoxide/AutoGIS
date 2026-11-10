import io
import json
import zipfile
from pathlib import Path
import pytest
from autogis.core.envmon import msl_lidar as m
from tests.envmon.test_msl_lidar import Inventory, BBOX


def archive_bytes(members=None):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in (members or {'PROJECT_A/HFDEM/44107h1_HFDEM.tif':b'fake raster', 'PROJECT_A/DSM/44107h1_DSM.tif':b'not DEM'}).items(): z.writestr(name,data)
    return out.getvalue()

class Stream(io.BytesIO):
    def __init__(self,data):
        super().__init__(data); self.headers={'Content-Length':str(len(data))}
class Client(Inventory):
    def __init__(self,data): super().__init__(size=len(data)); self.data=data; self.gets=0
    def stream(self,url): self.gets+=1; return Stream(self.data)


def setup(data=None):
    client=Client(data or archive_bytes())
    plan=m.build_msl_download_plan(m.resolve_msl_aoi(bbox=BBOX),client=client)
    return client,plan


def test_stream_cache_and_exact_hfdem_selection(tmp_path):
    client,plan=setup()
    downloaded=m.download_msl_archives(plan,tmp_path/'cache',client=client)
    assert client.gets==1 and downloaded[0].sha256
    again=m.download_msl_archives(plan,tmp_path/'cache',client=client)
    assert client.gets==1 and again[0].sha256==downloaded[0].sha256
    rasters=m.select_msl_dem_rasters(downloaded,plan.selected_projects,tmp_path/'extract')
    assert len(rasters)==1 and rasters[0].project=='PROJECT_A'
    assert rasters[0].path.read_bytes()==b'fake raster'
    assert not list((tmp_path/'extract').rglob('*DSM*'))


def test_large_and_unknown_download_gates_before_get(tmp_path):
    client,plan=setup()
    with pytest.raises(ValueError,match='allow-large'): m.download_msl_archives(plan,tmp_path,client=client,threshold_bytes=1)
    plan.archives[0].size_bytes=None
    with pytest.raises(ValueError,match='allow-large'): m.download_msl_archives(plan,tmp_path,client=client)
    assert client.gets==0


def test_cache_collision_and_corruption_preserve_existing(tmp_path):
    client,plan=setup(); target=tmp_path/plan.archives[0].name; target.write_bytes(b'user file')
    with pytest.raises(FileExistsError): m.download_msl_archives(plan,tmp_path,client=client)
    assert target.read_bytes()==b'user file'
    target.unlink()
    m.download_msl_archives(plan,tmp_path,client=client)
    target.write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='cache'): m.download_msl_archives(plan,tmp_path,client=client)
    assert target.read_bytes()==b'corrupted'


@pytest.mark.parametrize('member',['../evil.tif','C:/evil.tif','folder/../evil.tif','folder\\evil.tif','AUX.txt','folder/x:stream','/evil.tif','foo./x'])
def test_zip_paths_rejected(tmp_path,member):
    data=archive_bytes({member:b'x'})
    if '\\' in member:  # zipfile normalizes Windows paths while constructing the fixture
        data=data.replace(b'folder/evil.tif',b'folder\\evil.tif')
    client,plan=setup(data)
    with pytest.raises(ValueError,match='Unsafe'): m.download_msl_archives(plan,tmp_path,client=client)
    assert not list(tmp_path.glob('*.zip')) and not list(tmp_path.glob('*.part'))


def test_corrupt_zip_and_case_collisions_rejected(tmp_path):
    for data in [b'not a zip',archive_bytes({'PROJECT_A/HFDEM/a.tif':b'a','project_a/hfdem/A.tif':b'b'})]:
        client,plan=setup(data)
        with pytest.raises(ValueError): m.download_msl_archives(plan,tmp_path,client=client)


def test_interrupted_stream_retries_and_validates_expected_bytes(tmp_path):
    client,plan=setup()
    good=client.stream
    class Broken(Stream):
        def read(self,*args): raise TimeoutError('interrupted')
    calls=[]
    def flaky(url):
        calls.append(1)
        return Broken(client.data) if len(calls)<3 else good(url)
    client.stream=flaky
    result=m.download_msl_archives(plan,tmp_path,client=client,sleep=lambda n:None)
    assert len(calls)==3 and result[0].path.exists()
    client,plan=setup(); plan.archives[0].size_bytes+=1
    with pytest.raises(ValueError,match='byte'): m.download_msl_archives(plan,tmp_path/'wrong',client=client,sleep=lambda n:None)
    assert not list((tmp_path/'wrong').glob('*.zip'))


def test_missing_hfdem_and_ambiguous_project_rejected(tmp_path):
    for i,members in enumerate([{'PROJECT_A/DSM/x.tif':b'x'},{'Quads/HFDEM/x.tif':b'x'}]):
        client,plan=setup(archive_bytes(members)); downloads=m.download_msl_archives(plan,tmp_path/str(i),client=client)
        with pytest.raises(ValueError,match='HFDEM|attribution'): m.select_msl_dem_rasters(downloads,plan.selected_projects,tmp_path/('extract'+str(i)))


def test_intersecting_quad_with_only_other_project_does_not_block_partial_result(tmp_path):
    client,plan=setup(archive_bytes({'PROJECT_A/HFDEM/a.tif':b'a'}))
    first=m.download_msl_archives(plan,tmp_path/'first',client=client)
    client,plan=setup(archive_bytes({'PROJECT_B/HFDEM/b.tif':b'b'}))
    second=m.download_msl_archives(plan,tmp_path/'second',client=client)
    sources=m.select_msl_dem_rasters(first+second,['PROJECT_A'],tmp_path/'sources')
    assert len(sources)==1 and sources[0].project=='PROJECT_A'


def test_final_cache_publication_cannot_leave_partial_zip(tmp_path,monkeypatch):
    client,plan=setup();target=tmp_path/plan.archives[0].name
    original=Path.open
    class Broken:
        def __enter__(self):
            self.handle=original(target,'xb');self.handle.write(b'partial');return self
        def __exit__(self,*args):self.handle.close()
        def write(self,data):raise OSError('simulated disk error')
    def opened(path,*args,**kwargs):
        if path==target and args and args[0]=='xb':return Broken()
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',opened)
    try:m.download_msl_archives(plan,tmp_path,client=client,sleep=lambda n:None)
    except OSError:assert not target.exists(), 'failed publication left a partial final cache file'
    if target.exists():assert zipfile.is_zipfile(target)


def test_http_incomplete_read_retries_but_network_attempts_stay_bounded(tmp_path,monkeypatch):
    from http.client import IncompleteRead
    client,plan=setup();original=client.stream;attempts=[]
    class Incomplete(Stream):
        def read(self,*args):raise IncompleteRead(b'partial',10)
    def stream(url):
        attempts.append(1)
        return Incomplete(client.data) if len(attempts)==1 else original(url)
    client.stream=stream
    assert m.download_msl_archives(plan,tmp_path/'incomplete',client=client,sleep=lambda n:None)
    assert len(attempts)==2
    calls=[]
    def unavailable(*args,**kwargs):
        from urllib.error import URLError
        calls.append(1);raise URLError('unreachable')
    monkeypatch.setattr(m,'urlopen',unavailable);monkeypatch.setattr(m.time,'sleep',lambda n:None)
    with pytest.raises(OSError):m.download_msl_archives(plan,tmp_path/'offline',client=m.HTTPClient(),sleep=lambda n:None)
    assert len(calls)==3
