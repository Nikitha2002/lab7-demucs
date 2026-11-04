import os, json, time, tempfile, subprocess, logging
from pathlib import Path
import boto3, redis, requests
from botocore.config import Config
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
R=redis.Redis(host=os.getenv('REDIS_HOST','redis'),port=int(os.getenv('REDIS_PORT','6379')),decode_responses=True,socket_connect_timeout=5)
S=boto3.client('s3',endpoint_url=os.getenv('S3_ENDPOINT','http://rustfs-svc.rustfs-ns.svc.cluster.local:9000'),aws_access_key_id=os.getenv('S3_ACCESS_KEY'),aws_secret_access_key=os.getenv('S3_SECRET_KEY'),region_name='us-east-1',config=Config(signature_version='s3v4'))
BUCKET=os.getenv('S3_BUCKET','demucs-audio'); QUEUE='toWorkers'; FAILED='failedJobs'
TRACKS=('bass','drums','vocals','other')
def process(job):
    h=job['hash']; model=job.get('model','mdx_extra_q')
    if not (len(h)==32 and all(c in '0123456789abcdef' for c in h)): raise ValueError('Invalid hash')
    if model not in ('mdx_extra_q','htdemucs','htdemucs_ft'): raise ValueError('Invalid model')
    with tempfile.TemporaryDirectory() as tmp:
        inp=Path(tmp)/f'{h}.mp3'; out=Path(tmp)/'output'
        S.download_file(BUCKET,job['object_key'],str(inp))
        cmd=['python','-m','demucs.separate','-n',model,'--mp3','-d','cpu','--out',str(out),str(inp)]
        subprocess.run(cmd,check=True,timeout=1800)
        trackdir=out/model/h
        for stem in TRACKS:
            f=trackdir/(stem+'.mp3')
            if not f.is_file(): raise FileNotFoundError(str(f))
            S.upload_file(str(f),BUCKET,f'{h}/{stem}.mp3',ExtraArgs={'ContentType':'audio/mpeg'})
    callback=job.get('callback')
    if isinstance(callback,dict) and callback.get('url'):
        try: requests.post(callback['url'],json=callback.get('data',{}),timeout=5)
        except requests.RequestException as e: logging.warning('Callback failed: %s',e)
    logging.info('Completed %s',h)

def main():
    logging.info('Worker ready')
    while True:
        try:
            entry=R.blpop(QUEUE,timeout=5)
            if entry is None: continue
            payload=entry[1]
            try: process(json.loads(payload))
            except Exception:
                logging.exception('Job failed; preserving in failedJobs')
                R.rpush(FAILED,payload)
        except redis.RedisError:
            logging.exception('Redis unavailable; retrying')
            time.sleep(5)
if __name__=='__main__': main()
