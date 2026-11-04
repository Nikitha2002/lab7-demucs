# Lab 7 deployment guide (original implementation)

This project has been successfully tested end-to-end on both local Kubernetes (Kind) and Google Kubernetes Engine (GKE). The REST API, Redis queue, Demucs worker, and RustFS storage were verified. MP3 submission, separation into four tracks, track downloads, and track deletion were tested successfully. GKE deployment evidence is available in `evidence/gke-deployment.txt`.

## Architecture
Flask REST -> RustFS S3 storage + Redis `toWorkers` -> Demucs CPU worker -> RustFS four output MP3s. `failedJobs` retains failed job payloads for debugging; automatic retry is not implemented.

## Before deployment
- GKE is billable. Check budget and quota before creating a cluster. Stop/delete the cluster when done.
- The worker requests 6Gi memory; choose a node with enough allocatable RAM for all pods.
- Install the official RustFS Helm chart as instructed by your course tutorial (`06-rustfs`); copy `rustfs-config.example.yaml` to an **untracked** `rustfs-config.yaml`, replace credentials and check the available StorageClass.
- The instructor's original Redis manifests are in `redis/`.
- Create RustFS bucket `demucs-audio` before submitting songs.
- Publish both Docker images to an accessible registry, replace image placeholders in `k8s/rest.yaml` and `k8s/worker.yaml`.
- Create a Kubernetes secret in the **default namespace** with keys `S3_ACCESS_KEY` and `S3_SECRET_KEY` matching RustFS credentials. Example (do not paste secrets into chat or Git): `kubectl create secret generic rustfs-client-credentials --from-literal=S3_ACCESS_KEY=... --from-literal=S3_SECRET_KEY=...`

## Suggested deployment order (after connecting kubectl to your cluster)
1. Install RustFS Helm chart in `rustfs-ns` with your private values. Verify `kubectl get pods,svc,pvc -n rustfs-ns`.
2. Create the bucket using boto3 or the RustFS console via `kubectl port-forward -n rustfs-ns svc/rustfs-svc 9000:9000 9001:9001`. Do not expose object storage publicly.
3. `kubectl apply -f redis/redis-deployment.yaml -f redis/redis-service.yaml`
4. Create the app secret, then `kubectl apply -f k8s/config.yaml -f k8s/rest.yaml -f k8s/worker.yaml`
5. `kubectl get pods` and `kubectl logs deployment/demucs-worker`; `kubectl port-forward svc/rest-service 5000:5000`
6. In another terminal: `python tests/smoke_test.py data/short-dreams.mp3` (copy sample audio from official repository; it is not bundled here).

## Build and validate
`docker build -t lab7-rest:dev ./rest`
`docker build -t lab7-worker:cpu ./worker`
`docker run --rm lab7-worker:cpu python -m demucs.separate --help`
`python -m py_compile rest/rest-server.py worker/worker-server.py`

## Notes
- The REST `/apiv1/track/<hash>/base` route aliases the original uploaded MP3; `original` also works.
- The default model is `mdx_extra_q`; the worker runs on CPU. Model downloads may be large.
- Queue inspection shows *waiting* jobs, not in-progress jobs.
- `BLPOP` is at-most-once delivery. Failed payloads are copied to `failedJobs`, but abrupt pod death can lose an in-progress job. Improve with a processing queue for stronger guarantees.
- Ingress is intentionally not enabled; use port-forward for initial verification. Add ingress or GKE LoadBalancer after successful tests.
- No guarantees of points, runtime compatibility, or availability until tested on your actual cluster.
