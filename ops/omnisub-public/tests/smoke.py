import sys, json, urllib.parse, urllib.request, urllib.error, base64, secrets
assert len(sys.argv)>=2, 'Pass the base URL of your instance'
host=sys.argv[1]; secret='demo-'+secrets.token_hex(8); pw=secret.encode()
s=urllib.parse.urlunsplit(('hysteria2', secret+'@example.invalid:443', '', 'sni=example.invalid', 'Demo'))
def call(path,data=None):
 r=urllib.request.Request(host+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','User-Agent':'OmniSub-acceptance'})
 try:
  with urllib.request.urlopen(r,timeout=38) as resp:return resp.status,resp.read(),resp.headers
 except urllib.error.HTTPError as e:return e.code,e.read(),e.headers
for path,signature in [('/favicon.ico',b'\x00\x00\x01\x00'),('/favicon.svg',b'<svg'),('/apple-touch-icon.png',b'\x89PNG')]:
 code,body,h=call(path);assert code==200 and body.startswith(signature) and 'image/' in h['Content-Type']
assert call('/healthz')[:2]==(200,b'ok\n')
for t in ('clash','stash','surge','shadowrocket'):
 status,body,h=call('/api/links',{'sources':s,'target':t})
 assert status==200, (t,status,body[:150])
 x=json.loads(body);assert x['count']==1 and s not in x['path']
 a,raw,h=call(x['path']);assert a==200 and h['Cache-Control']=='no-store'
 if t=='clash':assert (b'password: '+pw) in raw and (b'auth: '+pw) not in raw and b'MATCH,' in raw
 if t=='stash':assert (b'auth: '+pw) in raw and (b'password: '+pw) not in raw
 if t=='surge':assert b'[Proxy]' in raw and (b'password='+pw) in raw and b'#!MANAGED-CONFIG' not in raw
 if t=='shadowrocket':assert (pw+b'@') in base64.b64decode(raw)
 print(t,a,h['Content-Disposition'],len(raw))
bad=[{'target':'stash','sources':s.replace(secret,'test%40test')},{'target':'stash','sources':s.replace('#','&pinSHA256=fixture#')},{'target':'clash','sources':s,'config':'unsupported'}]
for b in bad:assert call('/api/links',b)[0]==422
print('Protected inputs rejected; health, access controls, cache flags checked')

if len(sys.argv)>2:
 status,body,_=call('/api/links',{'sources':sys.argv[2],'target':'stash'});assert status==200 and json.loads(body)['count']==1
 assert b'auth: public-demo' in call(json.loads(body)['path'])[1];print('External HTTPS fixture, creation and refresh passed')
