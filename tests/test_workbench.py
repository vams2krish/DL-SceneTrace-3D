import hashlib
import io
import json
from pathlib import Path
import zipfile
from types import SimpleNamespace

import numpy as np
import cv2
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from scenetrace.media import inventory
from scenetrace.gaussian import basis, fit, render, look_at
from scenetrace import server


def picture(path, seed=1):
    pixels = np.random.default_rng(seed).integers(0,256,(64,64,3),dtype=np.uint8)
    Image.fromarray(pixels).save(path)


def test_original_integrity_duplicate_and_blur(tmp_path):
    source=tmp_path/'input';source.mkdir()
    picture(source/'a.png');(source/'b.png').write_bytes((source/'a.png').read_bytes())
    Image.new('RGB',(64,64)).save(source/'c.png')
    before={p.name:p.read_bytes() for p in source.iterdir()}
    manifest=inventory(source,tmp_path/'result')
    assert [f['decision'] for f in manifest['frames']]==['selected','duplicate','blur']
    for entry in manifest['sources']:
        assert entry['sha256']==hashlib.sha256(before[entry['name']]).hexdigest()
        assert (source/entry['name']).read_bytes()==before[entry['name']]
    assert len(list((tmp_path/'result'/'images').glob('*.png')))==1
    with pytest.raises(FileExistsError):inventory(source,tmp_path/'result')


def test_inventory_rejects_nested_output(tmp_path):
    with pytest.raises(ValueError):inventory(tmp_path,tmp_path/'result')


def test_video_frame_selection_and_timestamps(tmp_path):
    source=tmp_path/'video';source.mkdir()
    video=source/'clip.avi'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,64))
    assert writer.isOpened()
    for i in range(30):writer.write(np.random.default_rng(i).integers(0,256,(64,64,3),dtype=np.uint8))
    writer.release()
    manifest=inventory(source,tmp_path/'frames',interval=.5,max_frames=4)
    assert len(manifest['frames'])==4
    assert [f['timestamp_seconds'] for f in manifest['frames']]==[0,.5,1,1.5]
    assert all(f['decision']=='selected' for f in manifest['frames'])


def test_corrupt_source_is_recorded(tmp_path):
    source=tmp_path/'in';source.mkdir();(source/'bad.png').write_bytes(b'not an image')
    manifest=inventory(source,tmp_path/'out')
    assert manifest['sources'][0]['status']=='decode failed'
    assert manifest['frames']==[]


def test_camera_focal_prior_survives_derivative_conversion(tmp_path):
    source=tmp_path/'input';source.mkdir()
    exif=Image.Exif();exif[271]='Test camera';exif[272]='Model A';exif[34665]={41989:25}
    image=Image.fromarray(np.random.default_rng(11).integers(0,256,(64,64,3),dtype=np.uint8))
    image.save(source/'capture.jpeg',exif=exif)
    result=inventory(source,tmp_path/'output')
    assert result['sources'][0]['camera']['focal_35mm_equivalent']==25
    assert result['sources'][0]['camera']['model']=='Model A'


def test_gaussian_opacity_and_rgb_fit():
    r,t=look_at([0,1,4]);camera={'R':r.tolist(),'t':t.tolist(),'intrinsics':[20,20,12,12]}
    scene={'positions':[[-.25,.4,0],[.25,.7,.1]],'colors':[[.8,.2,.1],[.1,.8,.4]],'scales':[.2,.2],'opacity':[.8,.8]}
    matrix,trans=basis(scene['positions'],scene['scales'],scene['opacity'],camera,24,24)
    assert np.allclose(np.asarray(matrix.sum(axis=1)).ravel()+trans,1,atol=1e-6)
    target=render(scene,camera,24,24)
    initial=dict(scene,colors=[[.3,.3,.3],[.3,.3,.3]])
    result,metrics=fit(initial,[camera],[target],24,24)
    assert metrics['train_mse_after']<metrics['train_mse_before']*.001
    assert np.allclose(result['colors'],scene['colors'],atol=.01)


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path/'jobs');monkeypatch.setattr(server,'busy',False)
    monkeypatch.setattr(server.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*1024**3))
    with TestClient(server.app) as client:yield client


def test_boundary_and_resource_limits(client):
    assert client.get('/api/health').json()['mode']=='local-single-user'
    assert client.post('/api/jobs').status_code==403
    assert client.post('/api/jobs',headers={'x-scenetrace':'local-workbench','origin':'https://evil.example','content-length':'0'}).status_code==403
    assert client.get('/api/health',headers={'host':'evil.example'}).status_code==403
    assert client.get('/api/jobs/not-a-uuid').status_code==404
    assert client.get('/').headers['x-content-type-options']=='nosniff'
    assert client.post('/api/jobs',headers={'x-scenetrace':'local-workbench'},files=[('files',('x.png',b'x'))]).status_code==422


def test_job_success_and_traversal(client,monkeypatch):
    async def fake_worker(path):
        (path/'result').mkdir();(path/'result'/'scene.json').write_text('{"schema_version":1}')
        server.save_json(path/'status.json',{'id':path.name,'status':'succeeded'})
        server.busy=False
    monkeypatch.setattr(server,'run_job',fake_worker)
    response=client.post('/api/jobs',headers={'x-scenetrace':'local-workbench'},files=[('files',(f'../../{i}.png',b'fake')) for i in range(4)])
    assert response.status_code==202
    job=response.json()['id']
    assert client.get(f'/api/jobs/{job}').json()['status']=='succeeded'
    assert client.get(f'/api/jobs/{job}/assets/scene.json').status_code==200
    assert client.get(f'/api/jobs/{job}/assets/%2e%2e%2fsubmitted-names.json').status_code==404
    bundle=client.get(f'/api/jobs/{job}/bundle')
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert 'scene.json' in archive.namelist()
        assert not any('originals' in p for p in archive.namelist())
    retry=client.post(f'/api/jobs/{job}/retry',headers={'x-scenetrace':'local-workbench'},content=b'')
    assert retry.status_code==202
    assert retry.json()['id']!=job
    assert retry.json()['retry_of']==job
    assert (server.STORE/retry.json()['id']/'originals'/'source-0000.png').read_bytes()==b'fake'


def test_failed_job_releases_queue(client,monkeypatch):
    response=client.post('/api/jobs',headers={'x-scenetrace':'local-workbench'},files=[('files',(f'{i}.exe',b'x')) for i in range(4)])
    assert response.status_code==415
    assert server.busy is False
    assert list(server.STORE.iterdir())==[]


def test_128_photo_intake_is_not_truncated(client,monkeypatch):
    async def worker(path):
        assert len(list((path/'originals').glob('*.jpeg')))==128
        server.save_json(path/'status.json',{'id':path.name,'status':'succeeded'})
        server.busy=False
    monkeypatch.setattr(server,'run_job',worker)
    response=client.post('/api/jobs',headers={'x-scenetrace':'local-workbench'},files=[('files',(f'capture-{i}.jpeg',b'unit-test-only')) for i in range(128)])
    assert response.status_code==202
    assert client.get('/api/jobs/'+response.json()['id']).json()['status']=='succeeded'


def test_low_disk_rejects_without_job_creation(client,monkeypatch):
    monkeypatch.setattr(server.shutil,'disk_usage',lambda path:SimpleNamespace(free=100))
    response=client.post('/api/jobs',headers={'x-scenetrace':'local-workbench'},files=[('files',(f'{i}.png',b'x')) for i in range(4)])
    assert response.status_code==507
    assert server.busy is False
