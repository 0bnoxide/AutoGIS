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
