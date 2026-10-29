"""Generate a license-independent, seeded synthetic Gaussian fitting experiment."""
from pathlib import Path
import time
import numpy as np
from PIL import Image
from .gaussian import look_at, render, fit
from .media import save_json, digest


def generate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "views").mkdir(exist_ok=True)
    started = time.monotonic()
    rng = np.random.default_rng(17)
    points, colors, scales = [], [], []

    def surface(origin, a, b, nx, ny, base, scale=0.065):
        for i in range(nx):
            for j in range(ny):
                point = np.array(origin) + np.array(a)*i/(nx-1) + np.array(b)*j/(ny-1)
                tint = 0.78 + 0.22 * ((i+j) % 2)
                points.append(point.tolist()); colors.append((np.array(base)*tint).tolist()); scales.append(scale)

    # Open dollhouse / staged archive room. Units are synthetic, never real measurements.
    surface([-2, 0, -1.5], [4, 0, 0], [0, 0, 3], 25, 19, [.35, .42, .48], .095)
    surface([-2, 0, -1.5], [4, 0, 0], [0, 2.4, 0], 25, 15, [.30, .53, .58], .105)
    surface([-2, 0, -1.5], [0, 0, 3], [0, 2.4, 0], 19, 15, [.25, .37, .46], .105)
    surface([-.9, .8, -.45], [1.8, 0, 0], [0, 0, 1.1], 16, 10, [.72, .45, .22], .075)
    for x in [-.8, .8]:
        for z in [-.35, .55]:
            surface([x, .05, z], [.04, 0, 0], [0, .72, 0], 2, 8, [.55, .32, .16], .065)
    surface([.1, .86, -.1], [.46, 0, 0], [0, 0, .36], 6, 5, [.92, .79, .45], .045)
    for shelf in [.35, .9, 1.45, 2.0]:
        surface([.65, shelf, -1.28], [1.05, 0, 0], [0, 0, .2], 12, 3, [.63, .39, .19], .065)
        for book in range(8):
            color = [[.72, .31, .22], [.22, .56, .63], [.68, .62, .36]][book % 3]
            surface([.72+book*.12, shelf+.06, -1.18], [.05, 0, 0], [0, .32, 0], 2, 4, color, .045)
    true_scene = {"schema_version": 1, "positions": points, "scales": scales, "colors": colors,
                  "opacity": [.83]*len(points), "background": [.025, .035, .055]}
    cameras, targets, views = [], [], []
    width, height = 160, 120
    for index, angle in enumerate(np.linspace(-.65, .65, 8)):
        eye = [4.9*np.sin(angle)+1.0, 3.0, 4.9*np.cos(angle)]
        rotation, translation = look_at(eye)
        camera = {"id": f"view-{index:02d}", "R": rotation.tolist(), "t": translation.tolist(),
                  "intrinsics": [140, 140, width/2, height/2], "eye": eye}
        target = render(true_scene, camera, width, height)
        filename = f"views/source-{index:02d}.png"
        Image.fromarray(np.round(target*255).astype("uint8")).save(destination / filename)
        # Use the stored 8-bit observation for optimization and evaluation.
        targets.append(np.asarray(Image.open(destination / filename))/255)
        cameras.append(camera)
        views.append({"id": camera["id"], "image": filename, "sha256": digest(destination / filename),
                      "split": "held-out" if index in (2, 6) else "train", "camera": camera})
    initial = dict(true_scene, colors=np.clip(np.asarray(colors)*.45 + rng.uniform(0, .35, (len(points), 3)), 0, 1).tolist())
    train_indices = [i for i in range(8) if i not in (2, 6)]
    trained, metrics = fit(initial, [cameras[i] for i in train_indices], [targets[i] for i in train_indices], width, height)
    heldout = []
    for index in (2, 6):
        predicted = render(trained, cameras[index], width, height)
        mse = float(np.mean((predicted-targets[index])**2))
        psnr = float(-10*np.log10(max(mse, 1e-12)))
        filename = f"views/render-{index:02d}.png"
        Image.fromarray(np.round(predicted*255).astype("uint8")).save(destination / filename)
        views[index]["render"] = filename
        heldout.append({"view": cameras[index]["id"], "mse": mse, "psnr_db": psnr})
    metrics.update(heldout=heldout, heldout_psnr_db=float(np.mean([m["psnr_db"] for m in heldout])),
                   training_views=6, heldout_views=2, gaussians=len(points), seed=17,
                   elapsed_seconds=round(time.monotonic()-started, 2),
                   geometry_evaluation="Known synthetic geometry supplied, not estimated; no real-scene geometry benchmark.",
                   evaluation_caveat="Same renderer generates and fits targets; this is an optimizer smoke test, not an independent photogrammetry benchmark.")
    trained.update(kind="synthetic", label="Archive room · synthetic fitting experiment", cameras=cameras, views=views,
                   metrics=metrics, manifest={"schema_version": 1, "kind": "synthetic", "seed": 17,
                   "sources": [{"id": v["id"], "name": v["image"], "sha256": v["sha256"], "origin": "procedural Gaussian renderer"} for v in views]},
                   limitations=["Synthetic capture: camera poses and geometry are supplied, not recovered from photos.",
                                "Only RGB is optimized; geometry, scales, and opacity are fixed.",
                                "Training and testing share the same renderer; scores do not predict real-scene performance.",
                                "No measurement or forensic accuracy claim."])
    save_json(destination / "scene.json", trained)
    save_json(destination / "metrics.json", metrics)
    return metrics
