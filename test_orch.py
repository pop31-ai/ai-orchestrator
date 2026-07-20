import http.client, json, time

conn = http.client.HTTPConnection('127.0.0.1', 8080, timeout=400)
task = 'install python via winget, then create file hello.py with print(1+1) and run it'
body = json.dumps({'message': task, 'provider': 'local_tinyllama_q2'})
conn.request('POST', '/api/chat', body, {'Content-Type': 'application/json'})
resp = conn.getresponse()
print('Status:', resp.status)
t0 = time.time()
while True:
    line = resp.fp.readline()
    if not line:
        break
    line = line.decode('utf-8').strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except Exception:
        print('[RAW]', line[:200])
        continue
    if not isinstance(ev, dict):
        print('[NON-DICT]', ev)
        continue
    if ev.get('token'):
        print(ev['token'], end='', flush=True)
    elif ev.get('cmd'):
        print('\n>>> CMD:', ev['cmd'])
        print('>>> OUT:', ev['out'][:400])
    elif ev.get('round') is not None:
        print(f"\n[round {ev['round']} {ev['status']}]")
    elif ev.get('done'):
        print('\n[DONE]')
        break
    elif ev.get('error'):
        print('\n[ERROR]', ev['error'])
        break
print(f'\nTotal time: {time.time()-t0:.0f}s')
conn.close()
