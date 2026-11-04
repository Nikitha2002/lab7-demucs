import os, io, json, uuid, base64, binascii, logging
import boto3, redis
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
R = redis.Redis(host=os.getenv('REDIS_HOST','redis'), port=int(os.getenv('REDIS_PORT','6379')), decode_responses=True, socket_connect_timeout=3)
S = boto3.client('s3', endpoint_url=os.getenv('S3_ENDPOINT','http://rustfs-svc.rustfs-ns.svc.cluster.local:9000'), aws_access_key_id=os.getenv('S3_ACCESS_KEY'), aws_secret_access_key=os.getenv('S3_SECRET_KEY'), region_name='us-east-1', config=Config(signature_version='s3v4',connect_timeout=3,retries={'max_attempts':2}))
BUCKET=os.getenv('S3_BUCKET','demucs-audio')
QUEUE='toWorkers'
TRACKS={'bass','base','drums','vocals','other','original'}

def storage_key(songhash,track):
    if not (len(songhash)==32 and all(c in '0123456789abcdef' for c in songhash)):
        return None
    if track not in TRACKS: return None
    return f'{songhash}/'+('original' if track in ('base','original') else track)+'.mp3'

@app.get('/')
def home(): return jsonify(service='Music Separation as a Service',status='running')

@app.get('/health')
def health(): return jsonify(status='healthy')

@app.post('/apiv1/separate')
def separate():
    data=request.get_json(silent=True)
    if not isinstance(data,dict): return jsonify(error='JSON object required'),400
    encoded=data.get('mp3'); model=data.get('model','mdx_extra_q'); callback=data.get('callback')
    if not isinstance(encoded,str) or not encoded: return jsonify(error='Missing mp3'),400
    if model not in ('mdx_extra_q','htdemucs','htdemucs_ft'): return jsonify(error='Unsupported model'),400
    if callback is not None and (not isinstance(callback,dict) or not isinstance(callback.get('url'),str)):
        return jsonify(error='Invalid callback'),400
    try: audio=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error): return jsonify(error='Invalid Base64'),400
    if not audio: return jsonify(error='Empty audio'),400
    songhash=uuid.uuid4().hex; key=f'{songhash}/original.mp3'
    job={'hash':songhash,'model':model,'object_key':key,'callback':callback}
    try:
        S.put_object(Bucket=BUCKET,Key=key,Body=audio,ContentType='audio/mpeg')
        R.rpush(QUEUE,json.dumps(job))
    except Exception:
        app.logger.exception('Unable to save or queue song')
        return jsonify(error='Storage or queue unavailable'),503
    return jsonify(hash=songhash,reason='Song enqueued for separation')

@app.get('/apiv1/queue')
@app.get('/apiv1/queue/')
def queue():
    try:
        result=[]
        for x in R.lrange(QUEUE,0,-1):
            try: result.append(json.loads(x)['hash'])
            except (ValueError,KeyError,TypeError): result.append(x)
        return jsonify(queue=result)
    except redis.RedisError: return jsonify(error='Redis unavailable'),503

@app.get('/apiv1/track/<songhash>/<track>')
def get_track(songhash,track):
    key=storage_key(songhash,track)
    if not key: return jsonify(error='Invalid songhash or track'),400
    try:
        obj=S.get_object(Bucket=BUCKET,Key=key)
        return send_file(io.BytesIO(obj['Body'].read()),mimetype='audio/mpeg',as_attachment=True,download_name=track+'.mp3')
    except ClientError as e:
        if e.response.get('Error',{}).get('Code') in ('NoSuchKey','404','NotFound'): return jsonify(error='Track not found'),404
        app.logger.exception('Storage error'); return jsonify(error='Storage unavailable'),503
    except Exception:
        app.logger.exception('Storage error'); return jsonify(error='Storage unavailable'),503

@app.route('/apiv1/remove/<songhash>/<track>',methods=['GET','DELETE'])
def remove_track(songhash,track):
    key=storage_key(songhash,track)
    if not key: return jsonify(error='Invalid songhash or track'),400
    try:
        S.delete_object(Bucket=BUCKET,Key=key)
        return jsonify(hash=songhash,track=track,status='removed')
    except Exception:
        app.logger.exception('Storage error'); return jsonify(error='Storage unavailable'),503

if __name__=='__main__': app.run(host='0.0.0.0',port=5000)
