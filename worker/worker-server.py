import os
import json
import time
import tempfile
import subprocess
from pathlib import Path

import boto3
import redis
import requests
from botocore.config import Config

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
QUEUE_KEY = "toWorkers"

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_BUCKET = os.getenv("S3_BUCKET", "demucs-audio")

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True
)

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
    aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
    region_name="us-east-1",
    config=Config(signature_version="s3v4")
)

TRACKS = ["bass", "drums", "vocals", "other"]


def process_job(job):
    songhash = job["hash"]
    model = job.get("model", "mdx_extra_q")
    object_key = job["object_key"]
    callback = job.get("callback")

    # Restrict model names to known Demucs models.
    if model not in {"mdx_extra_q", "htdemucs", "htdemucs_ft"}:
        raise ValueError("Unsupported Demucs model")

    print(f"Processing song: {songhash}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        input_file = workdir / f"{songhash}.mp3"
        output_dir = workdir / "output"

        s3.download_file(
            S3_BUCKET,
            object_key,
            str(input_file)
        )

        command = [
            "python", "-m", "demucs.separate",
            "-n", model,
            "--mp3",
            "--out", str(output_dir),
            str(input_file)
        ]

        subprocess.run(
            command,
            check=True,
            timeout=1800
        )

        track_dir = output_dir / model / songhash

        for track in TRACKS:
            track_file = track_dir / f"{track}.mp3"

            if not track_file.exists():
                raise FileNotFoundError(
                    f"Missing separated track: {track}"
                )

            s3.upload_file(
                str(track_file),
                S3_BUCKET,
                f"{songhash}/{track}.mp3",
                ExtraArgs={"ContentType": "audio/mpeg"}
            )

        if isinstance(callback, dict) and callback.get("url"):
            try:
                requests.post(
                    callback["url"],
                    json=callback.get("data", {}),
                    timeout=5
                )
            except requests.RequestException as exc:
                print(f"Callback failed: {exc}", flush=True)

    print(f"Completed song: {songhash}", flush=True)


def main():
    print("Demucs worker started", flush=True)

    while True:
        try:
            item = redis_client.blpop(QUEUE_KEY, timeout=5)

            if item is None:
                continue

            _, payload = item
            job = json.loads(payload)

            try:
                process_job(job)
            except Exception as exc:
                print(f"Job failed: {exc}", flush=True)

        except redis.RedisError as exc:
            print(f"Redis connection error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
