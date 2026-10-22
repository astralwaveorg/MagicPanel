#!/usr/bin/env python3
"""NAS explicit proxy manager. Run as root; never changes gateways or DNS.

这里的 10.0.1.8 是 Mac mini（家里跑 Stash / Surge 的那台机器）的内网地址：
NAS 要通过它出网，所以只能写内网地址，写 127.0.0.1 等于让 NAS 连自己。
端口 6152 / 6153 是 Surge 的「允许来自局域网的连接」端口。
详见 docs/reference/环境与地址.md。
"""
import argparse, contextlib, fcntl, hashlib, json, os, re, shutil, socket, subprocess, sys, time, urllib.request
from pathlib import Path

BASE = Path('/opt/proxy-switch')
ENV = Path('/etc/nas-proxy/proxy.env')
STATE = BASE / 'state.json'
REGISTRY = BASE / 'registry.json'
NO_PROXY = 'localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'

def run(args, **kw):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=90, **kw).stdout

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(path, data, mode=None):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    old = path.stat() if path.exists() else None
    tmp = path.with_name(path.name + '.proxy-switch-tmp')
    tmp.write_bytes(data)
    os.chmod(tmp, mode or (old.st_mode & 0o777 if old else 0o644))
    if old: os.chown(tmp, old.st_uid, old.st_gid)
    os.replace(tmp, path)

def inspect():
    ids = run(['docker', 'ps', '-aq']).split()
    return json.loads(run(['docker','inspect',*ids])) if ids else []

def check(profile):
    hp, sp = profile['http'], profile['socks']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': hp, 'https': hp}))
    for url in ['https://www.google.com/generate_204','https://www.gstatic.com/generate_204']:
        with opener.open(url, timeout=15) as r:
            if r.status != 204: raise RuntimeError('HTTP proxy probe did not return 204')
    from urllib.parse import urlsplit
    p=urlsplit(sp)
    with socket.create_connection((p.hostname,p.port),timeout=8) as s:
        s.sendall(b'\x05\x01\x00')
        if s.recv(2)!=b'\x05\x00': raise RuntimeError('SOCKS5 negotiation failed')
        host=b'www.google.com';s.sendall(b'\x05\x01\x00\x03'+bytes([len(host)])+host+b'\x01\xbb')
        reply=s.recv(32)
        if len(reply)<2 or reply[1]!=0:raise RuntimeError('SOCKS5 CONNECT failed')
    print('PASS: HTTPS CONNECT / Google / gstatic / SOCKS5 CONNECT', flush=True)

def compose_args(group):
    # archon's defaults were the original source of inherited proxy variables.
    # This also restores those variables when rolling back pre-env_file Compose.
    args=['docker','--config','/home/archon/.docker','compose','--project-directory',group['directory']]
    if group.get('project'):args += ['--project-name',group['project']]
    for p in group['files']: args += ['-f',p]
    return args

def daemon_restart():
    if run(['docker','info','--format','{{.LiveRestoreEnabled}}']).strip()!='true':
        raise RuntimeError('Docker live-restore must be enabled before switching')
    # fnOS ExecStop explicitly stops all containers, overriding live-restore.
    # Clear it only for this controlled daemon restart; restore the unit immediately.
    runtime=Path('/run/systemd/system/docker.service.d/99-proxy-switch-restart.conf')
    if runtime.exists():raise RuntimeError('Another restart override already exists')
    save(runtime,b'[Service]\nExecStop=\n',0o644)
    try:
        run(['systemctl','daemon-reload'])
        run(['systemctl','restart','docker'])
        for _ in range(20):
            try:run(['docker','info','--format','{{.ServerVersion}}']);break
            except Exception:time.sleep(1)
        else:raise RuntimeError('Docker daemon did not recover')
    finally:
        runtime.unlink(missing_ok=True)
        run(['systemctl','daemon-reload'])

def activate(registry, daemon_changed=True):
    if daemon_changed: daemon_restart()
    for group in registry['compose']:
        print('Updating:',','.join(group['services']),flush=True)
        run(compose_args(group)+['up','-d','--no-deps','--no-build','--pull','never','--force-recreate',*group['services']],cwd=group['directory'])
    cron=registry.get('cron')
    if cron:
        content=Path(cron['source']).read_text()
        # Single-file bind mounts retain the old inode after atomic host writes.
        run(['docker','exec','-i',cron['container'],'sh','-c','cat > /crons.conf'],input=content)
        run(['docker','exec','-i',cron['container'],'crontab','-'],input=content)

def verify_runtime(profile, registry):
    wanted={s for g in registry['compose'] for s in g['services']}
    for c in inspect():
        service=(c['Config'].get('Labels') or {}).get('com.docker.compose.service')
        if service not in wanted:continue
        env=dict(x.split('=',1) for x in c['Config'].get('Env',[]) if '=' in x)
        if c['State']['Status']!='running':raise RuntimeError('Container is not running: '+c['Name'])
        for key in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:
            if env.get(key)!=profile['http']:raise RuntimeError('Stale container proxy: '+c['Name']+' '+key)
    pid=run(['systemctl','show','docker','--property=MainPID','--value']).strip()
    env=Path('/proc',pid,'environ').read_bytes().split(b'\0')
    if ('HTTP_PROXY='+profile['http']).encode() not in env:raise RuntimeError('Stale Docker daemon proxy')
    cron=registry.get('cron')
    if cron and profile['http'] not in run(['docker','exec',cron['container'],'crontab','-l']):raise RuntimeError('Stale replication cron proxy')
    print('PASS: daemon / managed containers / replication cron',flush=True)

def restore(snap):
    manifest=json.loads((snap/'manifest.json').read_text())
    for ent in manifest['files']:
        p=Path(ent['path'])
        if ent['exists']:
            save(p,(snap/ent['backup']).read_bytes(),ent['mode']);os.chown(p,ent['uid'],ent['gid'])
        else:p.unlink(missing_ok=True)

def switch(profile, registry):
    check(profile)
    old=json.loads(STATE.read_text()) if STATE.exists() else {'http':'http://10.0.1.8:6152','socks':'socks5h://10.0.1.8:6153'}
    changes={}
    pairs=[(old['http'],profile['http']),(old['socks'],profile['socks']),
           (old['socks'].replace('socks5h://','socks5://'),profile['socks'].replace('socks5h://','socks5://')),
           ('http://10.0.1.8:6152',profile['http']),('socks5://10.0.1.8:6153',profile['socks'].replace('socks5h://','socks5://')),
           ('socks5h://10.0.1.8:6153',profile['socks'])]
    for p in registry['files']:
        path=Path(p)
        if not path.exists():continue
        data=path.read_bytes();new=data
        for before,after in pairs:new=new.replace(before.encode(),after.encode())
        if new!=data:changes[p]=new
    env='\n'.join(k+'='+profile['http'] for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','PROXY_HOST'])+'\n'
    changes[str(ENV)]=env.encode()
    changes[str(STATE)]=(json.dumps(profile,indent=2)+'\n').encode()
    # Make the daemon consume the same authoritative HTTP endpoint.
    drop=Path('/etc/systemd/system/docker.service.d/proxy.conf')
    changes[str(drop)]=('[Service]\nEnvironmentFile='+str(ENV)+'\nEnvironment="NO_PROXY='+NO_PROXY+',.svc,.cluster.local"\n').encode()
    # Preserve registry auth and all unrelated Docker client settings.
    for p in ['/root/.docker/config.json','/home/archon/.docker/config.json']:
        data=json.loads(Path(p).read_text()) if Path(p).exists() else {}
        data.setdefault('proxies',{})['default']={'httpProxy':profile['http'],'httpsProxy':profile['http'],'noProxy':NO_PROXY}
        changes[p]=(json.dumps(data,indent=2)+'\n').encode()
    # Keep per-service no_proxy values intact, add a shared env_file for persistence.
    for group in registry['compose']:
        p=group['files'][0];text=changes.get(p,Path(p).read_bytes()).decode()
        for service in group['services']:
            match=re.search(r'^  '+re.escape(service)+r':\s*\n',text,re.M)
            if not match:raise RuntimeError('Cannot locate compose service '+service)
            start=match.end();next_service=re.search(r'^  [\w.-]+:\s*$',text[start:],re.M)
            end=start+next_service.start() if next_service else len(text)
            block=text[start:end]
            if str(ENV) in block:continue
            scalar=re.search(r'^    env_file:\s*(\S+)\s*$',block,re.M)
            if scalar:
                block=block[:scalar.start()]+'    env_file:\n      - '+scalar.group(1)+'\n      - '+str(ENV)+block[scalar.end():]
            elif re.search(r'^    env_file:',block,re.M):
                raise RuntimeError('Unsupported existing env_file list; inspect '+p)
            else:block='    env_file:\n      - '+str(ENV)+'\n'+block
            text=text[:start]+block+text[end:]
        changes[p]=text.encode()
    changes={p:d for p,d in changes.items() if not Path(p).exists() or Path(p).read_bytes()!=d}
    if not changes:
        if (BASE/'pending').exists():
            activate(registry);check(profile);verify_runtime(profile,registry);(BASE/'pending').unlink()
        else:verify_runtime(profile,registry)
        print('Already configured; no files changed.');return
    stamp=time.strftime('%Y%m%d-%H%M%S');snap=BASE/'backups'/stamp;snap.mkdir(parents=True,mode=0o700)
    manifest={'files':[],'profile':profile}
    for i,(p,data) in enumerate(changes.items()):
        path=Path(p);ent={'path':p,'exists':path.exists(),'after_sha256':digest(data)}
        if path.exists():
            st=path.stat();ent.update(mode=st.st_mode & 0o777,uid=st.st_uid,gid=st.st_gid,backup=str(i));shutil.copy2(path,snap/str(i));os.chmod(snap/str(i),0o600)
        manifest['files'].append(ent)
    (snap/'manifest.json').write_text(json.dumps(manifest,indent=2));os.chmod(snap/'manifest.json',0o600)
    try:
        for p,data in changes.items():save(p,data,0o600 if p==str(STATE) or p.endswith('/.docker/config.json') else None)
        for group in registry['compose']:run(compose_args(group)+['config','--quiet'],cwd=group['directory'])
    except Exception:
        restore(snap);raise
    print('Backup:',snap,flush=True)
    (BASE/'pending').write_text(stamp)
    daemon_changed=any('/docker.service.d/' in p or p==str(ENV) for p in changes)
    restart_paths={f for g in registry['compose'] for f in g['files']}|{
        '/vol1/1000/docker/moviepilot/.env','/vol1/1000/docker/vertex/data/data/setting/proxy.json',registry['cron']['source']}
    if daemon_changed or any(p in restart_paths for p in changes):activate(registry,daemon_changed)
    # fnOS may rewrite root's Docker HttpHeaders while reconnecting its manager.
    # Merge proxy defaults again without replacing newly issued headers.
    root_config=Path('/root/.docker/config.json')
    data=json.loads(root_config.read_text())
    data.setdefault('proxies',{})['default']={'httpProxy':profile['http'],'httpsProxy':profile['http'],'noProxy':NO_PROXY}
    save(root_config,(json.dumps(data,indent=2)+'\n').encode(),0o600)
    for ent in manifest['files']:
        if ent['path']==str(root_config):ent['after_sha256']=digest(root_config.read_bytes())
    (snap/'manifest.json').write_text(json.dumps(manifest,indent=2))
    check(profile)
    verify_runtime(profile,registry)
    (BASE/'pending').unlink(missing_ok=True)
    print('DONE:',profile['name'],'—',len(changes),'files; backup',stamp,flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','check','stash','surge','rollback'])
    parser.add_argument('backup',nargs='?')
    parser.add_argument('--host',default='10.0.1.8',help='Proxy server hostname or IPv4 address')
    parser.add_argument('--http-port',type=int,help='Override the profile HTTP port')
    parser.add_argument('--socks-port',type=int,help='Override the profile SOCKS5 port')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Use sudo')
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=open(BASE/'lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    registry=json.loads(REGISTRY.read_text())
    current=json.loads(STATE.read_text()) if STATE.exists() else {'name':'surge','http':'http://10.0.1.8:6152','socks':'socks5h://10.0.1.8:6153'}
    if args.action=='status':
        print(json.dumps(current,ensure_ascii=False,indent=2))
        for c in inspect():
            env=[x for x in c['Config'].get('Env',[]) if x.split('=',1)[0].lower() in ['http_proxy','https_proxy','all_proxy','proxy_host']]
            if env:print(c['Name'],*env)
    elif args.action=='check':check(current);verify_runtime(current,registry)
    elif args.action=='rollback':
        if not args.backup or not re.fullmatch(r'\d{8}-\d{6}',args.backup):parser.error('Specify a backup timestamp')
        snap=BASE/'backups'/args.backup;manifest=json.loads((snap/'manifest.json').read_text())
        for e in manifest['files']:
            p=Path(e['path'])
            if not p.exists() or digest(p.read_bytes())!=e['after_sha256']:raise RuntimeError('File changed since backup; refusing overwrite: '+str(p))
        # Check the old endpoint before taking a working proxy offline.
        state_entry=next((e for e in manifest['files'] if e['path']==str(STATE)),None)
        old=json.loads((snap/state_entry['backup']).read_text()) if state_entry and state_entry['exists'] else {'name':'surge','http':'http://10.0.1.8:6152','socks':'socks5h://10.0.1.8:6153'}
        check(old);restore(snap);activate(registry);(BASE/'pending').unlink(missing_ok=True);print('Restored',args.backup)
    else:
        if not re.fullmatch(r'[A-Za-z0-9.-]+',args.host):parser.error('Invalid proxy hostname')
        hp=args.http_port or (7890 if args.action=='stash' else 6152);sp=args.socks_port or (7890 if args.action=='stash' else 6153)
        if not (1<=hp<=65535 and 1<=sp<=65535):parser.error('Invalid proxy port')
        p={'name':args.action,'http':f'http://{args.host}:{hp}','socks':f'socks5h://{args.host}:{sp}'}
        switch(p,registry)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('ERROR:',str(e),file=sys.stderr)
        if isinstance(e,subprocess.CalledProcessError):print((e.stderr or '')[-2000:],file=sys.stderr)
        sys.exit(1)
