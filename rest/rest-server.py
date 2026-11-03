import os
import io
import json
import uuid
import base64
import binascii

import boto3
import redis
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "rustfsadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "rustfsadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "demucs-audio")

QUEUE_KEY = "toWorkers"

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=3
)

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1"
)


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "Music Separation as a Service",
        "status": "running"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


@app.route("/apiv1/separate", methods=["POST"])
def separate():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "JSON request body required"}), 400

    encoded_mp3 = data.get("mp3")
    model = data.get("model", "mdx_extra_q")
    callback = data.get("callback")

    if not isinstance(encoded_mp3, str) or not encoded_mp3:
        return jsonify({"error": "Missing mp3 data"}), 400

    if not isinstance(model, str) or not model:
        return jsonify({"error": "Invalid model"}), 400

    if callback is not None and not isinstance(callback, dict):
        return jsonify({"error": "Invalid callback"}), 400

    try:
        mp3_bytes = base64.b64decode(
            encoded_mp3, validate=True
        )
    except (binascii.Error, ValueError):
        return jsonify({"error": "Invalid Base64 encoding"}), 400

    if not mp3_bytes:
        return jsonify({"error": "Empty MP3 data"}), 400

    songhash = uuid.uuid4().hex
    object_key = f"{songhash}/original.mp3"

    job = {
        "hash": songhash,
        "model": model,
        "object_key": object_key,
        "callback": callback
    }

    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=object_key,
            Body=mp3_bytes,
            ContentType="audio/mpeg"
        )

        redis_client.rpush(
            QUEUE_KEY,
            json.dumps(job)
        )

    except (
        redis.RedisError,
        BotoCoreError,
        ClientError,
        OSError
    ) as exc:
        app.logger.error("Failed to enqueue job: %s", exc)
        return jsonify({
            "error": "Storage or queue unavailable"
        }), 503

    return jsonify({
        "hash": songhash,
        "reason": "Song enqueued for separation"
    }), 200


@app.route("/apiv1/queue", methods=["GET"])
@app.route("/apiv1/queue/", methods=["GET"])
def get_queue():
    try:
        entries = redis_client.lrange(QUEUE_KEY, 0, -1)
        hashes = []

        for entry in entries:
            try:
                job = json.loads(entry)
                hashes.append(job["hash"])
            except (ValueError, KeyError, TypeError):
                hashes.append(entry)

        return jsonify({"queue": hashes}), 200

    except redis.RedisError as exc:
        app.logger.error("Redis queue error: %s", exc)
        return jsonify({"error": "Redis unavailable"}), 503


@app.route("/apiv1/track/<songhash>/<track>", methods=["GET"])
def get_track(songhash, track):
    allowed = {"bass", "drums", "vocals", "other", "original"}

    if track not in allowed:
        return jsonify({"error": "Invalid track"}), 400

    object_key = f"{songhash}/{track}.mp3"

    try:
        response = s3.get_object(
            Bucket=S3_BUCKET,
            Key=object_key
        )

        audio = response["Body"].read()

        return send_file(
            io.BytesIO(audio),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{track}.mp3"
        )

    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")

        if code in ("NoSuchKey", "404"):
            return jsonify({"error": "Track not found"}), 404

        app.logger.error("Storage error: %s", exc)
        return jsonify({"error": "Storage unavailable"}), 503

    except (BotoCoreError, OSError) as exc:
        app.logger.error("Storage error: %s", exc)
        return jsonify({"error": "Storage unavailable"}), 503


@app.route("/apiv1/remove/<songhash>/<track>",
           methods=["GET", "DELETE"])
def remove_track(songhash, track):
    allowed = {"bass", "drums", "vocals", "other", "original"}

    if track not in allowed:
        return jsonify({"error": "Invalid track"}), 400

    object_key = f"{songhash}/{track}.mp3"

    try:
        s3.delete_object(
            Bucket=S3_BUCKET,
            Key=object_key
        )

        return jsonify({
            "hash": songhash,
            "track": track,
            "status": "removed"
        }), 200

    except (ClientError, BotoCoreError, OSError) as exc:
        app.logger.error("Delete error: %s", exc)
        return jsonify({"error": "Storage unavailable"}), 503


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
