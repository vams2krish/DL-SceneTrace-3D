# Operating boundaries

## Delivery model

The hosted Site is a static review application. It renders a committed synthetic Gaussian scene, shows its actual experiment metrics and source hashes, hashes selected local media with Web Crypto, stores review notes in browser local storage, imports scene JSON, and exports review JSON. No hosted media upload, remote reconstruction, telemetry, external fonts, or third-party JavaScript is used.

The Python service is a **single-user loopback research workbench**, not a public multiuser API. `scenetrace serve` binds only to `127.0.0.1`. Do not place it behind a public reverse proxy or change its bind address without implementing authentication, authorization, quotas, request-body limits at the ingress, isolated workers, and operational review.

## Controls implemented

- Loopback Host allowlist, same-origin mutation check, and required custom workbench header; CORS is not enabled.
- Up to 200 source files / 1 GiB total, file extension checks, source-byte and image-pixel limits, a 3 GiB free-space check on the job volume, a single active worker, and a thirty-minute subprocess deadline. The request body limit is 1100 MiB to allow multipart overhead.
- Generated storage names and UUID job IDs; artifact paths must resolve inside the selected job result directory.
- Source hashes before decoding, separate derivatives, deterministic frame candidate selection, recorded sharpness/duplicate decisions, and immutable source bytes.
- Worker failures and interrupted jobs are persisted. No demo artifact replaces a failed reconstruction.
- Local and static-host security headers. No secret is required to run the demo.
- Scene JSON size, array counts, numeric bounds, and text insertion checks in the viewer. Imported JSON cannot provide remote media URLs.
- Browser notes have per-scene fingerprints; exports include both observation and hypothesis layers.

These controls reduce accidental exposure; they are not a completed security audit. Media codecs and COLMAP parse untrusted binary content. A production service needs OS/container isolation and a resource-enforcing worker supervisor. Header body-length checks alone are not an adversarial streaming upload boundary. Do not process hostile or sensitive evidence through the public demo.

## Local data lifecycle

`data/<job-id>/originals/` contains uploaded source bytes under generated names. `submitted-names.json` maps those names to the submitted names. `result/` contains derivatives, COLMAP artifacts, manifests, configuration, metrics, and scene JSON. `worker.log` records backend output. All are ignored by Git. There is no automatic retention deletion; choose and document retention policies before real use. Stop the server before moving an entire job folder to protected storage.

The downloadable worker ZIP includes JSON review artifacts, status, and the submitted-name mapping. It intentionally omits original media, image derivatives, logs, and COLMAP binary files; relative image references need those local artifacts to display. Use the job directory for complete internal reproducibility. Names and hashes can be sensitive even without the media.

## Recovery

1. Read the job status and `result/failure.json` when a job fails.
2. Inspect `worker.log` locally for registration errors; never paste case-bearing logs into public issues.
3. Keep failed artifacts; submit a fresh job after improving overlap, sharpness, or frame selection. Output directories are not silently overwritten.
4. A restart marks queued/running jobs failed. The in-flight child is killed on graceful shutdown or timeout; an abrupt OS kill may require manual process cleanup.

5. `POST /api/jobs/<uuid>/retry` creates a new job from preserved originals using same-volume hardlinks. It requires the same local workbench header as upload. Previous outputs and failure records are retained. These linked source bytes must remain immutable.

## Public research-photo experiment

CrossRow's iPhone JPEG resource is licensed CC BY-NC-ND 4.0. The downloader and runner keep source photographs, derivative frames, camera geometry, and fitted output under ignored `data/`. The public report records only source attribution, checksums, counts, numerical metrics, and actual failure reasons. Do not copy the local scene artifact or screenshots containing its adapted output into public Site assets or the GitHub README. The separate procedural synthetic demo is the hosted reference scene.

`data/crossrow/latest-job.json` identifies the local experiment. The read-only `/api/public-test` endpoint resolves that UUID through the normal job access/path checks. The local `?dataset=crossrow` URL reads the actual job status and loads an artifact only after success. It never silently replaces a failed experiment with the synthetic model.

## Production release gates still open

Authentication and per-case authorization; encrypted managed storage and retention; verified acquisition and chain-of-custody procedures; sandboxed worker infrastructure; backups; monitoring; independent source/geometry datasets; held-out camera localization; calibrated scale and uncertainty; full covariance/geometry optimization and densification; larger scene performance; accessibility and security audit; qualified forensic review. This release must not be described as a certified or production-ready forensic system.
