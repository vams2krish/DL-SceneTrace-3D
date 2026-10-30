"""Submit the 128 downloaded originals to the live loopback API and record output.

This report contains numerical results and source checksums only; no licensed
photographs, thumbnails, geometry, or adapted scene artifacts are published.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import time
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8765');parser.add_argument('--retry');args=parser.parse_args()
    source=Path('data/crossrow/originals')
    provenance=json.loads(Path('data/crossrow/download-provenance.json').read_text())
    paths=sorted(source.glob('*.jpeg'))
    assert len(paths)==128 and len({s['sha256'] for s in provenance['sources']})==128
    client=httpx.Client(base_url=args.url,timeout=180)
    if args.retry:
        response=client.post(f'/api/jobs/{args.retry}/retry',headers={'X-SceneTrace':'local-workbench'},content=b'')
    else:
        with ExitStack() as stack:
            files=[('files',(p.name,stack.enter_context(p.open('rb')),'image/jpeg')) for p in paths]
            response=client.post('/api/jobs',headers={'X-SceneTrace':'local-workbench'},files=files)
    response.raise_for_status();job=response.json()['id']
    pointer={'id':job,'dataset':provenance['dataset'],'license':provenance['license']}
    Path('data/crossrow/latest-job.json').write_text(json.dumps(pointer),encoding='utf-8')
    print('Submitted 128 original camera JPEGs; live job '+job,flush=True)
    last=None
    for _ in range(370):
        status=client.get(f'/api/jobs/{job}').json()
        if status['status']!=last:
            print(json.dumps(status),flush=True);last=status['status']
        if status['status'] in ('failed','succeeded'):break
        time.sleep(5)
    report={k:provenance[k] for k in ['dataset','doi','creators','origin','license','source_archive_url','source_etag','selection','integrity','count']}
    report.update(distinct_original_sha256=128,source_bytes=sum(s['bytes'] for s in provenance['sources']),
                  api_status=status['status'],publication='Numerical report only; source images and reconstruction remain local',
                  original_source_hashes=[{'name':s['name'],'sha256':s['sha256']} for s in provenance['sources']])
    if status['status']=='succeeded':
        metrics=client.get(f'/api/jobs/{job}/assets/metrics.json');metrics.raise_for_status()
        report['metrics']=metrics.json()
        report['observed_limitations']=['Camera registration can cover only a subset of the 128 originals.',
             'RGB is fitted on up to 20 registered views; geometry/scales/opacity stay fixed.',
             'Withheld views are not independently localized; no held-out PSNR or surveyed geometry score.',
             'These are photographs of a staged scene, not real criminal-case evidence.']
    else:
        report['failure']=status.get('error','Run incomplete; inspect local job')
    Path('docs/experiments/crossrow-128.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='original_source_hashes'},indent=2),flush=True)


if __name__=='__main__':main()
