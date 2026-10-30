"""Single-user loopback service. Never expose this service as a public backend."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import io
import json
import os
import shutil
import sys
import uuid
import zipfile

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from .media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, save_json

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get("SCENETRACE_DATA", ROOT / "data")).resolve()
TASKS = set()
busy = False


@asynccontextmanager
async def lifespan(app):
    STORE.mkdir(parents=True, exist_ok=True)
    # A server restart is explicit failure, never a permanently running phantom job.
    for path in STORE.glob("*/status.json"):
        status = json.loads(path.read_text())
        if status.get("status") in ("queued", "running"):
            save_json(path, dict(status, status="failed", error="Server interrupted; submit a new job"))
    yield
    for task in list(TASKS):
        task.cancel()
    await asyncio.gather(*TASKS, return_exceptions=True)


app = FastAPI(title="SceneTrace Crime Scene Department local workbench", version="0.3.0", lifespan=lifespan)


@app.middleware("http")
async def boundary(request: Request, call_next):
    host = request.url.hostname
    if host not in ("127.0.0.1", "localhost", "testserver"):
        return Response("Loopback host required", status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-scenetrace") != "local-workbench":
            return Response("Same-origin workbench header required", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return Response("Cross-origin mutation denied", status_code=403)
        length = request.headers.get("content-length")
        if length is None or not length.isdigit() or int(length) > 1100 * 1024 * 1024:
            return Response("Content-Length required; maximum request 1100 MiB", status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response


def job_path(job_id):
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Unknown job")
    path = STORE / job_id
    if not (path / "status.json").exists():
        raise HTTPException(404, "Unknown job")
    return path


async def run_job(path):
    global busy
    proc = None
    save_json(path / "status.json", {"id": path.name, "status": "running"})
    try:
        with open(path / "worker.log", "wb") as log:
            proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "scenetrace.cli", "reconstruct", str(path / "originals"), str(path / "result"), "--max-frames", "200", stdout=log, stderr=log, cwd=ROOT)
            await asyncio.wait_for(proc.wait(), timeout=1800)
        if proc.returncode:
            failure = path / "result" / "failure.json"
            message = json.loads(failure.read_text())["error"] if failure.exists() else "Worker failed; inspect worker.log locally"
            save_json(path / "status.json", {"id": path.name, "status": "failed", "error": message})
        else:
            save_json(path / "status.json", {"id": path.name, "status": "succeeded", "scene": f"/api/jobs/{path.name}/assets/scene.json"})
    except (TimeoutError, asyncio.CancelledError):
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        save_json(path / "status.json", {"id": path.name, "status": "failed", "error": "Worker timed out or server stopped"})
    except Exception as exc:
        save_json(path / "status.json", {"id": path.name, "status": "failed", "error": str(exc)[:500]})
    finally:
        busy = False


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "local-single-user", "version": "0.3.0", "busy": busy,
            "public_test":(STORE/'crossrow'/'latest-job.json').exists()}


@app.get("/api/public-test")
def public_test():
    result=STORE/'crossrow'/'calibration-rerun'
    if (result/'scene.json').exists():
        metrics=json.loads((result/'metrics.json').read_text())
        poor=metrics['registered_cameras']<4 or metrics['registered_cameras']/max(1,metrics['sfm_input_views'])<0.5
        return {'id':'local-calibration-rerun','status':'succeeded','quality':'insufficient_coverage' if poor else 'unvalidated',
                'scene':'/api/public-test/assets/scene.json','asset_base':'/api/public-test/assets/',
                'dataset':'CrossRow: Multimodal Spatial Indoor Crime Scene Dataset','license':'CC BY-NC-ND 4.0'}
    pointer=STORE/'crossrow'/'latest-job.json'
    if not pointer.exists():
        raise HTTPException(404,"No public-photo experiment has been run locally")
    record=json.loads(pointer.read_text())
    path=job_path(record['id'])
    return dict(json.loads((path/'status.json').read_text()),dataset=record['dataset'],license=record['license'])


@app.get('/api/public-test/assets/{asset:path}')
def public_test_asset(asset: str):
    root=(STORE/'crossrow'/'calibration-rerun').resolve()
    target=(root/asset).resolve()
    if root not in target.parents or not target.is_file() or target.suffix not in ('.json','.png'):
        raise HTTPException(404,'Unknown experiment artifact')
    return FileResponse(target)


@app.post("/api/jobs", status_code=202)
async def create_job(files: list[UploadFile] = File(...)):
    global busy
    if busy:
        raise HTTPException(409, "A reconstruction is already running")
    has_video = any(Path(f.filename or "").suffix.lower() in VIDEO_EXTENSIONS for f in files)
    if not 1 <= len(files) <= 200 or (len(files) < 4 and not has_video):
        raise HTTPException(422, "Submit 4–200 photos, or 1–200 files including a video")
    if shutil.disk_usage(STORE).free < 3*1024**3:
        raise HTTPException(507, "At least 3 GiB free disk space required")
    busy = True
    path = STORE / str(uuid.uuid4())
    (path / "originals").mkdir(parents=True)
    total = 0
    try:
        names = []
        for index, upload in enumerate(files):
            extension = Path(upload.filename or "").suffix.lower()
            if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                raise HTTPException(415, "Supported: JPEG, PNG, WEBP, MP4, MOV, AVI, WEBM")
            safe_name = f"source-{index:04d}{extension}"
            names.append({"stored_name": safe_name, "submitted_name": (upload.filename or "")[:250]})
            with open(path / "originals" / safe_name, "wb") as out:
                while chunk := await upload.read(1024*1024):
                    total += len(chunk)
                    if total > 1024*1024*1024:
                        raise HTTPException(413, "Total source limit is 1 GiB")
                    out.write(chunk)
        save_json(path / "submitted-names.json", names)
        save_json(path / "status.json", {"id": path.name, "status": "queued"})
        task = asyncio.create_task(run_job(path))
        TASKS.add(task)
        task.add_done_callback(TASKS.discard)
        return {"id": path.name, "status": "queued"}
    except BaseException:
        busy = False
        shutil.rmtree(path)
        raise
    finally:
        for upload in files:
            await upload.close()


@app.get("/api/jobs/{job_id}")
def status(job_id: str):
    return json.loads((job_path(job_id) / "status.json").read_text())


@app.post("/api/jobs/{job_id}/retry",status_code=202)
async def retry_job(job_id: str):
    """Reuse preserved originals without uploading hundreds of MiB again."""
    global busy
    previous=job_path(job_id)
    previous_status=json.loads((previous/'status.json').read_text())
    if busy or previous_status['status'] in ('queued','running'):
        raise HTTPException(409,'Wait for the current reconstruction to finish')
    path=STORE/str(uuid.uuid4())
    (path/'originals').mkdir(parents=True)
    busy=True
    try:
        for original in (previous/'originals').iterdir():
            if original.is_file():
                # Same-volume hardlinks preserve bytes and avoid data duplication.
                os.link(original,path/'originals'/original.name)
        shutil.copyfile(previous/'submitted-names.json',path/'submitted-names.json')
        save_json(path/'status.json',{'id':path.name,'status':'queued','retry_of':job_id})
        task=asyncio.create_task(run_job(path));TASKS.add(task);task.add_done_callback(TASKS.discard)
        return {'id':path.name,'status':'queued','retry_of':job_id}
    except BaseException:
        busy=False
        shutil.rmtree(path)
        raise


@app.get("/api/jobs/{job_id}/assets/{asset:path}")
def asset(job_id: str, asset: str):
    root = job_path(job_id) / "result"
    target = (root / asset).resolve()
    if root not in target.parents or not target.is_file() or target.suffix not in (".json", ".png"):
        raise HTTPException(404, "Unknown artifact")
    return FileResponse(target)


@app.get("/api/jobs/{job_id}/bundle")
def bundle(job_id: str):
    path = job_path(job_id)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "config.json", "metrics.json", "scene.json", "failure.json"):
            file = path / "result" / name
            if file.exists():
                archive.write(file, name)
        archive.write(path / "submitted-names.json", "submitted-names.json")
        archive.write(path / "status.json", "status.json")
    return Response(stream.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="scenetrace-review.zip"'})


app.mount("/", StaticFiles(directory=ROOT / "demo" / "dist", html=True), name="demo")
