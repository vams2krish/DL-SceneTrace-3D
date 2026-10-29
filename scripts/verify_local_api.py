"""Exercise the live failure path with intentionally duplicate synthetic inputs."""
from pathlib import Path
import json
import time
import httpx


def main():
    client=httpx.Client(base_url='http://127.0.0.1:8765',timeout=20)
    image=Path('demo/dist/sample/views/source-00.png').read_bytes()
    response=client.post('/api/jobs',headers={'X-SceneTrace':'local-workbench'},
                         files=[('files',(f'duplicate-{i}.png',image,'image/png')) for i in range(4)])
    response.raise_for_status();job=response.json()['id']
    for _ in range(30):
        status=client.get(f'/api/jobs/{job}').json()
        if status['status'] in ('failed','succeeded'):break
        time.sleep(1)
    assert status['status']=='failed',status
    assert 'four distinct sharp views' in status['error']
    assert client.get('/api/health').json()['busy'] is False
    report={'test':'Live subprocess failure on duplicate media','status':'passed','job_status':status['status'],
            'error':status['error'],'queue_released':True,'placeholder_scene_substitution':False}
    Path('docs/experiments/api-failure.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
