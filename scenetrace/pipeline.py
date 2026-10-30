"""COLMAP adapter with recorded camera recovery and honest failed-job behavior."""
from pathlib import Path
import importlib.metadata
import time

import numpy as np
from PIL import Image
from .media import inventory, save_json, digest
from .gaussian import scene_from_points, fit, render


def reconstruct(source, output, *, interval=1.0, max_frames=160):
    import pycolmap
    output = Path(output)
    started = time.monotonic()
    manifest = inventory(source, output, interval=interval, max_frames=max_frames)
    selected = [f for f in manifest["frames"] if f["decision"] == "selected"]
    if len(selected) < 4:
        raise ValueError("At least four distinct sharp views are required; add overlapping viewpoints")
    # Deterministic holdout; all training and SfM image lists exclude these views.
    heldout = selected[::5] if len(selected) >= 8 else []
    training = [f for f in selected if f not in heldout]
    source_map={s['id']:s for s in manifest['sources']}
    priors=[source_map[f['source_id']].get('camera') for f in training]
    shared=all(priors) and len({(p['make'],p['model'],p['focal_35mm_equivalent']) for p in priors})==1 and len({(f['width'],f['height']) for f in training})==1
    config = {"camera_model": "SIMPLE_PINHOLE", "camera_mode": "SINGLE" if shared else "PER_IMAGE", "device": "cpu",
              "focal_prior":"EXIF 35mm equivalent / 36 * long image side" if shared else "COLMAP generic default",
              "holdout": [f["image"] for f in heldout], "training": [f["image"] for f in training],
              "max_gaussians": 1600, "fit_resolution": 96,
              "matching": "sequential overlap 12" if len(training)>40 else "exhaustive",
              "max_features": 2048, "fit_view_budget": 20,
              "versions": {p: importlib.metadata.version(p) for p in ["pycolmap", "numpy", "scipy", "Pillow"]}}
    save_json(output / "config.json", config)
    database = output / "colmap.db"
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_PINHOLE"
    if shared:
        reader.default_focal_length_factor=priors[0]['focal_35mm_equivalent']/36
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.num_threads = 4
    extraction.sift.max_num_features = 2048
    pycolmap.extract_features(database_path=str(database), image_path=str(output / "images"),
                             image_names=config["training"], camera_mode=pycolmap.CameraMode.SINGLE if shared else pycolmap.CameraMode.PER_IMAGE,
                             reader_options=reader, extraction_options=extraction, device=pycolmap.Device.cpu)
    matching = pycolmap.FeatureMatchingOptions()
    matching.num_threads = 4
    if len(training)>40:
        pairs=pycolmap.SequentialPairingOptions()
        pairs.overlap=12
        pairs.quadratic_overlap=True
        pycolmap.match_sequential(database_path=str(database), matching_options=matching, pairing_options=pairs, device=pycolmap.Device.cpu)
    else:
        pycolmap.match_exhaustive(database_path=str(database), matching_options=matching, device=pycolmap.Device.cpu)
    sparse_path = output / "sparse"
    sparse_path.mkdir()
    mapping=pycolmap.IncrementalPipelineOptions()
    mapping.num_threads=4
    mapping.random_seed=17
    models = pycolmap.incremental_mapping(database_path=str(database), image_path=str(output / "images"), output_path=str(sparse_path), options=mapping)
    if not models:
        raise ValueError("COLMAP could not recover a connected scene. More overlap and texture are needed.")
    model = max(models.values(), key=lambda m: m.num_reg_images())
    points = [p for p in model.points3D.values() if p.error < 3.0]
    scene = scene_from_points([p.xyz for p in points], [np.asarray(p.color)/255 for p in points])
    cameras, targets, source_views = [], [], []
    registered=sorted(model.images.values(),key=lambda image:image.name)
    fit_names={registered[i].name for i in np.linspace(0,len(registered)-1,min(20,len(registered)),dtype=int)}
    fit_cameras=[]
    for image in registered:
        camera = model.cameras[image.camera_id]
        # SIMPLE_PINHOLE is distortion-free; size is explicitly rescaled for fitting.
        intrinsic = camera.calibration_matrix().copy()
        with Image.open(output / "images" / image.name) as original:
            target = original.convert("RGB")
            target = target.resize((96, 96))
        intrinsic[0] *= 96/camera.width
        intrinsic[1] *= 96/camera.height
        pose = image.cam_from_world()
        entry = {"id": image.name, "R": pose.rotation.matrix().tolist(), "t": pose.translation.tolist(),
                 "intrinsics": [intrinsic[0, 0], intrinsic[1, 1], intrinsic[0, 2], intrinsic[1, 2]]}
        cameras.append(entry)
        if image.name in fit_names:
            fit_cameras.append(entry)
            targets.append(np.asarray(target)/255)
        source_views.append({"id": image.name, "image": "images/"+image.name, "split": "train", "used_for_rgb_fit":image.name in fit_names})
    scene, metrics = fit(scene, fit_cameras, targets, 96, 96)
    metrics.update(registered_cameras=model.num_reg_images(), selected_views=len(selected),
                   quality_status='insufficient_coverage' if model.num_reg_images()<4 or model.num_reg_images()/len(training)<0.5 else 'unvalidated',
                   triangulated_points=len(points), rgb_fit_views=len(fit_cameras), sfm_input_views=len(training),
                   heldout_source_views=len(heldout), source_files=len(manifest['sources']),
                   matching=config['matching'], elapsed_seconds=time.monotonic()-started,
                   heldout_evaluation="Not available: held-out views are excluded from SfM; independent localization is not implemented.",
                   geometry_evaluation="Not available: no independent scale reference supplied.")
    scene.update(kind="reconstructed", label="Uploaded scene · unvalidated research reconstruction", cameras=cameras,
                 views=source_views, metrics=metrics, manifest=manifest,
                 limitations=["Fixed isotropic geometry and opacity; only RGB is fitted.", "Scale is arbitrary; no forensic measurement claim.", "No independent held-out localization or geometry validation."])
    save_json(output / "scene.json", scene)
    for i, camera in enumerate(cameras[:3]):
        Image.fromarray((render(scene, camera, 96, 96)*255).astype("uint8")).save(output / f"render-{i}.png")
    metrics["scene_sha256"] = digest(output / "scene.json")
    save_json(output / "metrics.json", metrics)
    return scene
