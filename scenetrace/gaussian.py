"""CPU reference backend: fixed isotropic geometry, fitted RGB Gaussian splats.

This intentionally small backend uses depth-sorted front-to-back alpha compositing.
It fits appearance with sparse bounded least squares. It does not learn geometry,
covariance, opacity, spherical harmonics, or perform adaptive densification.
"""
import numpy as np
from scipy import sparse
from scipy.optimize import lsq_linear
from scipy.spatial import cKDTree


def look_at(eye, target=(0, 0.5, 0)):
    eye, target = np.asarray(eye, dtype=float), np.asarray(target, dtype=float)
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    rotation = np.stack([right, -up, forward])
    return rotation, -rotation @ eye


def basis(points, scales, opacity, camera, width, height):
    """Sparse per-pixel contributions; OpenCV camera (+z forward, +y down)."""
    points, scales, opacity = np.asarray(points), np.asarray(scales), np.asarray(opacity)
    xyz = points @ np.asarray(camera["R"]).T + np.asarray(camera["t"])
    fx, fy, cx, cy = camera["intrinsics"]
    rows, cols, values = [], [], []
    transmittance = np.ones(width * height)
    for index in np.argsort(xyz[:, 2]):
        x, y, z = xyz[index]
        if z <= 0.05:
            continue
        u, v = fx * x / z + cx, fy * y / z + cy
        sigma = max(0.4, (fx + fy) * 0.5 * scales[index] / z)
        radius = min(3 * sigma, max(width, height))
        left, right = max(0, int(np.floor(u - radius))), min(width, int(np.ceil(u + radius)) + 1)
        top, bottom = max(0, int(np.floor(v - radius))), min(height, int(np.ceil(v + radius)) + 1)
        if left >= right or top >= bottom:
            continue
        xx, yy = np.meshgrid(np.arange(left, right), np.arange(top, bottom))
        pixels = (yy * width + xx).ravel()
        alpha = np.clip(opacity[index] * np.exp(-0.5 * (((xx-u)/sigma)**2 + ((yy-v)/sigma)**2)), 0, 0.99).ravel()
        contribution = transmittance[pixels] * alpha
        keep = contribution > 1e-6
        rows.extend(pixels[keep]); cols.extend([int(index)] * int(keep.sum())); values.extend(contribution[keep])
        transmittance[pixels] *= 1 - alpha
    matrix = sparse.csr_matrix((values, (rows, cols)), shape=(width * height, len(points)))
    return matrix, transmittance


def render(scene, camera, width, height):
    matrix, transmittance = basis(scene["positions"], scene["scales"], scene["opacity"], camera, width, height)
    color = matrix @ np.asarray(scene["colors"]) + transmittance[:, None] * np.asarray(scene.get("background", [0.025, 0.035, 0.055]))
    return np.clip(color.reshape(height, width, 3), 0, 1)


def fit(scene, cameras, targets, width, height):
    matrices, values = [], []
    background = np.asarray(scene.get("background", [0.025, 0.035, 0.055]))
    for camera, target in zip(cameras, targets):
        matrix, transmittance = basis(scene["positions"], scene["scales"], scene["opacity"], camera, width, height)
        matrices.append(matrix)
        values.append(np.asarray(target).reshape(-1, 3) - transmittance[:, None] * background)
    design = sparse.vstack(matrices)
    target = np.concatenate(values)
    initial = np.asarray(scene["colors"])
    before = float(np.mean((design @ initial - target)**2))
    # Small prior stabilizes weakly observed Gaussians; no held-out target enters fit.
    design_reg = sparse.vstack([design, 0.01 * sparse.eye(len(initial))]).tocsr()
    target_reg = np.concatenate([target, 0.01 * initial])
    fits = [lsq_linear(design_reg, target_reg[:, c], bounds=(0, 1), tol=1e-5, max_iter=30, lsmr_maxiter=120) for c in range(3)]
    colors = np.stack([result.x for result in fits], axis=1)
    after = float(np.mean((design @ colors - target)**2))
    result = dict(scene, colors=colors.tolist())
    return result, {"train_mse_before": before, "train_mse_after": after,
                    "solver_success": [bool(r.success) for r in fits],
                    "backend": "cpu-fixed-isotropic-gaussian-rgb-v1",
                    "optimized": ["RGB"], "fixed": ["positions", "isotropic scales", "opacity"]}


def scene_from_points(points, colors, *, limit=1600):
    points, colors = np.asarray(points), np.asarray(colors)
    if len(points) < 8:
        raise ValueError("Insufficient triangulated points for Gaussian initialization")
    if len(points) > limit:
        selected = np.linspace(0, len(points)-1, limit, dtype=int)
        points, colors = points[selected], colors[selected]
    distances = cKDTree(points).query(points, k=2)[0][:, 1]
    positive = distances[distances > 1e-8]
    floor = float(np.median(positive)) if len(positive) else 0.01
    scales = np.clip(distances * 0.6, floor * 0.2, floor * 4)
    return {"schema_version": 1, "positions": points.tolist(), "colors": colors.tolist(),
            "scales": scales.tolist(), "opacity": [0.8]*len(points), "background": [0.025, 0.035, 0.055]}
