import os,sys,time,base64,requests
host=os.getenv('REST','localhost:5000')
file=sys.argv[1] if len(sys.argv)>1 else 'data/short-dreams.mp3'
url=f'http://{host}'
print('Health:',requests.get(url+'/health',timeout=10).json())
with open(file,'rb') as f: encoded=base64.b64encode(f.read()).decode()
r=requests.post(url+'/apiv1/separate',json={'mp3':encoded,'model':'htdemucs'},timeout=60)
print('Submit:',r.status_code,r.text);r.raise_for_status();h=r.json()['hash']
for i in range(40):
    time.sleep(15)
    r=requests.get(url+f'/apiv1/track/{h}/vocals',timeout=30)
    if r.status_code==200:
        with open('vocals-test.mp3','wb') as f:f.write(r.content)
        print('SUCCESS: vocals-test.mp3',len(r.content),'bytes');break
    print('Waiting',i+1,r.status_code)
else: raise SystemExit('Timeout: check worker logs and failedJobs queue')
