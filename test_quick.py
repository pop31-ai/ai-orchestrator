import http.client, json, time

conn = http.client.HTTPConnection('127.0.0.1', 8080, timeout=400)
task = 'what is 2+2? reply in one short sentence'
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
        continue
    if not isinstance(ev, dict):
        continue
    if ev.get('token'):
        print(ev['token'], end='', flush=True)
    elif ev.get('round') is not None:
        print(f"\n[round {ev['round']} {ev['status']}]")
    elif ev.get('done'):
        print('\n[DONE]')
        break
    elif ev.get('error'):
        print('\n[ERROR]', ev['error'])
        break
print(f'\nTime: {time.time()-t0:.0f}s')
conn.close()
