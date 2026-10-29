"""Run controlled input-count experiments and align recovered camera centers.

All captures are synthetic. Similarity alignment uses training camera truth and
measures training pose recovery; it is not independent geometry validation.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys
import time
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scenetrace.pipeline import reconstruct
from scenetrace.media import save_json
from generate_sfm_fixture import generate


def aligned_camera_error(scene,truth):
    frames={f['image']:f for f in scene['manifest']['frames'] if f['decision']=='selected'}
    sources={s['id']:s for s in scene['manifest']['sources']}
    gt={c['name']:c for c in truth['cameras']}
    recovered=[];expected=[]
    for camera in scene['cameras']:
        original=sources[frames[camera['id']]['source_id']]['name']
        reference=gt[original]
        recovered.append(-np.array(camera['R']).T@np.array(camera['t']))
        expected.append(-np.array(reference['R']).T@np.array(reference['t']))
    a,b=np.array(recovered),np.array(expected)
    am,bm=a.mean(axis=0),b.mean(axis=0)
    ac,bc=a-am,b-bm
    u,s,vt=np.linalg.svd(ac.T@bc)
    sign=np.eye(3);sign[-1,-1]=np.linalg.det(u@vt)
    rotation=u@sign@vt
    scale=np.sum(s*np.diag(sign))/np.sum(ac**2)
    aligned=scale*ac@rotation+bm
    rmse=float(np.sqrt(np.mean(np.sum((aligned-b)**2,axis=1))))
    baseline=float(np.max(np.linalg.norm(b[:,None]-b[None,:],axis=2)))
    return {'camera_center_rmse_synthetic_units':rmse,'rmse_over_camera_baseline':rmse/max(baseline,1e-9),
            'alignment':'Similarity alignment fitted to the same registered training camera centers',
            'caveat':'Training-pose diagnostic, not held-out or real-world geometry accuracy.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,default=Path('data/experiment'));parser.add_argument('--report',type=Path,default=Path('docs/experiments/sparse-input.json'));args=parser.parse_args()
    args.work.mkdir(parents=True,exist_ok=True)
    captures=args.work/'captures';generate(captures)
    truth=json.loads((args.work/'captures-truth.json').read_text())
    results=[]
    for count in (4,6,9):
        source=args.work/f'input-{count}';source.mkdir()
        for index in np.linspace(0,8,count,dtype=int):shutil.copyfile(captures/f'capture-{index:02d}.png',source/f'capture-{index:02d}.png')
        started=time.monotonic()
        try:
            scene=reconstruct(source,args.work/f'result-{count}')
            results.append({'input_views':count,'status':'succeeded','metrics':scene['metrics'],'camera_alignment':aligned_camera_error(scene,truth)})
        except Exception as exc:
            results.append({'input_views':count,'status':'failed','error':str(exc),'elapsed_seconds':time.monotonic()-started})
        save_json(args.report,{'schema_version':1,'dataset':'Procedural textured 3D patches; synthetic, seed 21','counts':[4,6,9],
                             'input_control':'Same scene, fixed camera arc, evenly selected camera indices; no real media.',
                             'caveat':'Four/six views have no holdout; nine views exclude two captures from SfM and fitting. No held-out localization or geometry validation.',
                             'runs':results})
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
