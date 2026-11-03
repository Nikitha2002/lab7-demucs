FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    demucs \
    boto3 \
    redis \
    requests

COPY worker-server.py /app/worker-server.py

CMD ["python", "-u", "/app/worker-server.py"]
