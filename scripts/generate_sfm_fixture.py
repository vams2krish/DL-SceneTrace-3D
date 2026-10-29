"""Create deterministic textured 3D patches and perspective captures for SfM QA.

This is synthetic test data, not a real crime scene or historical reconstruction.
Run from the repository root: python scripts/generate_sfm_fixture.py data/sfm-input
"""
import sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scenetrace.gaussian import look_at
from scenetrace.media import save_json


def generate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(21)
    patches = []
    for ix in range(9):
        for iy in range(7):
            center = np.array([(ix-4)*.45, (iy-3)*.4+.5, rng.uniform(-.45,.45)])
            corners = center + np.array([[-.19,-.17,0],[.19,-.17,0],[.19,.17,0],[-.19,.17,0]])
            texture = rng.integers(40,230,(18,18,3),dtype=np.uint8)
            texture = cv2.resize(texture,(108,108),interpolation=cv2.INTER_NEAREST)
            cv2.putText(texture,f'{ix}{iy}',(18,69),cv2.FONT_HERSHEY_SIMPLEX,1.3,(255,255,255),3)
            patches.append((corners,texture))
    intrinsics = np.array([[580,0,320],[0,580,240],[0,0,1]],dtype=float)
    cameras=[]
    for i, x in enumerate(np.linspace(-.65,.65,9)):
        rotation, translation = look_at([x, .6+.12*np.sin(i), 4.0],target=[0,.5,0])
        canvas = np.full((480,640,3),18,dtype=np.uint8)
        ordered = sorted(patches,key=lambda p:float((p[0].mean(axis=0)@rotation.T+translation)[2]),reverse=True)
        for corners,texture in ordered:
            xyz=corners@rotation.T+translation
            projected=xyz@intrinsics.T
            uv=(projected[:,:2]/projected[:,2:]).astype(np.float32)
            homography=cv2.getPerspectiveTransform(np.float32([[0,0],[107,0],[107,107],[0,107]]),uv)
            warped=cv2.warpPerspective(texture,homography,(640,480))
            mask=cv2.warpPerspective(np.full((108,108),255,dtype=np.uint8),homography,(640,480))
            canvas[mask>0]=warped[mask>0]
        Image.fromarray(canvas).save(destination/f'capture-{i:02d}.png')
        cameras.append({'name':f'capture-{i:02d}.png','R':rotation.tolist(),'t':translation.tolist(),'intrinsics':intrinsics.tolist()})
    # Store fixture truth outside the media folder, so it cannot enter training.
    save_json(destination.parent/(destination.name+'-truth.json'),{'kind':'synthetic-sfm-fixture','seed':21,'cameras':cameras})


if __name__=='__main__':
    generate(sys.argv[1])
