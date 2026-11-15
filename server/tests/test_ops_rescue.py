from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_restore_uses_old_digest_without_network(tmp_path):
    from scripts.ops.rescue import compose_image_override, restore_argv
    old = 'sha256:' + '1' * 64
    f = compose_image_override(tmp_path, old)
    assert old in f.read_text()
    argv = restore_argv('/opt/magicpanel', str(f))
    assert '--no-build' in argv and '--pull' in argv and 'never' in argv
    assert '--build' not in argv


def test_changed_rescue_file_blocks(tmp_path):
    from scripts.ops.rescue import build_rescue_manifest, verify_rescue_manifest
    f = tmp_path / 'image.tar'; f.write_bytes(b'fixture')
    m = build_rescue_manifest([f], {'kind': 'fixture'})
    f.write_bytes(b'changed')
    assert 'HASH_MISMATCH' in verify_rescue_manifest(tmp_path, m)


def test_manifest_rejects_escape_and_duplicate_names(tmp_path):
    from scripts.ops.rescue import build_rescue_manifest, verify_rescue_manifest
    assert 'UNSAFE_FILE' in verify_rescue_manifest(tmp_path, {'schema': 1, 'files': [{'path': '../key', 'sha256': '0'*64, 'size': 0}]})
    a = tmp_path/'a'; a.mkdir(); b = tmp_path/'b'; b.mkdir()
    (a/'key').write_text('a'); (b/'key').write_text('b')
    with pytest.raises(ValueError):
        build_rescue_manifest([a/'key', b/'key'], {})


def test_digest_cannot_inject_compose(tmp_path):
    from scripts.ops.rescue import compose_image_override
    with pytest.raises(ValueError):
        compose_image_override(tmp_path, 'latest\n build: .')


def test_verify_gate_requires_independent_path_and_rehearsal(tmp_path, capsys):
    import json
    from scripts.ops.rescue import main, build_rescue_manifest
    f = tmp_path/'image.tar'; f.write_bytes(b'fixture')
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps(build_rescue_manifest([f], {})))
    assert main(['verify', '--manifest', str(manifest)]) == 42
    out = capsys.readouterr().out
    assert 'INDEPENDENT_PATH_REQUIRED' in out and 'RESTORE_REHEARSAL_REQUIRED' in out


def test_failed_health_restores_actual_old_digest_without_build(tmp_path):
    import json
    from scripts.ops.rescue import build_rescue_manifest, offline_deploy
    old, new = 'sha256:'+'1'*64, 'sha256:'+'2'*64
    f = tmp_path/'image.tar'; f.write_bytes(b'offline')
    m = tmp_path/'manifest.json'
    m.write_text(json.dumps(build_rescue_manifest([f], {'image_id': new, 'architecture': 'amd64'})))
    state = {'image': old}; calls = []
    def run(argv):
        calls.append(argv)
        if argv[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([{'Id': argv[3], 'Architecture': 'amd64'}])
        if argv[:2] == ['docker', 'info']:
            return 'x86_64'
        if argv[:2] == ['docker', 'compose']:
            override = json.loads(Path(argv[5]).read_text())
            state['image'] = override['services']['magicpanel']['image']
            return ''
        if argv[3] == '{{.Image}}':
            return state['image']
        return 'unhealthy'
    with pytest.raises(ValueError, match='DEPLOY_FAILED_OLD_IMAGE_RESTORED'):
        offline_deploy(m, tmp_path, run=run, attempts=1, pause=0)
    assert state['image'] == old
    commands = [a for a in calls if a[:2] == ['docker', 'compose']]
    assert len(commands) == 2
    assert all('--no-build' in a and a[-2:] == ['--pull', 'never'] for a in commands)


def test_deploy_script_offline_dispatches_before_ssh():
    body = (Path(__file__).resolve().parents[2]/'scripts/deploy.sh').read_text(encoding='utf-8')
    assert '--image-manifest' in body
    assert body.index('scripts.ops.rescue deploy') < body.index('DIRTY=')
    assert 'IMAGE_TAG=' not in body


def test_rehearsal_requires_real_engine_and_keeps_evidence_blocked(tmp_path):
    from scripts.ops.rescue import rehearse_restore
    import subprocess
    def unavailable(argv):
        raise subprocess.CalledProcessError(1, argv)
    with pytest.raises(subprocess.SubprocessError):
        rehearse_restore(tmp_path, 'sha256:'+'1'*64, 'sha256:'+'2'*64, run=unavailable)
    assert not (tmp_path/'rehearsal.json').exists()


def test_signed_rescue_receipts_can_pass_and_tampering_blocks(tmp_path):
    import json, hashlib
    from scripts.ops.evidence import init_run, seal_artifact, canonical_bytes
    from scripts.ops.rescue import verify_rescue_receipts
    run = init_run(tmp_path/'proofs', {'role':'nas'}, phase='OFFLINE')
    proof = Path(run['proof_dir']); manifest = {'schema':1, 'metadata': {'image_id':'sha256:'+'2'*64, 'previous_image_id':'sha256:'+'1'*64, 'architecture':'amd64'}}
    sha = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    attachment = proof/'observation.txt';attachment.write_bytes(b'actual operator observation')
    attachment_sha = hashlib.sha256(attachment.read_bytes()).hexdigest()
    common = {'manifest_sha256':sha, 'evidence_hashes':{'observation.txt':attachment_sha}}
    bodies = {
        'rescue_path': {**common, 'proxy_dependency_disconnected':True, 'retrieval_transport':'cellular', 'management_transport':'lan', 'protected_management_vps':True, 'retrieved_manifest_sha256':sha},
        'rescue_resources': {**common, 'database_result_sha256':'3'*64, 'old_code_image_id':manifest['metadata']['previous_image_id'], 'old_code_readable':True, 'resources_restored':True},
        'rescue_rehearsal': {**common, 'architecture':'amd64', 'network_mode':'none', 'host_mounts':False, 'image_sequence':[manifest['metadata']['previous_image_id'],manifest['metadata']['image_id'],manifest['metadata']['previous_image_id']]},
    }
    for purpose,body in bodies.items():
        (proof/(purpose+'.receipt.json')).write_bytes(canonical_bytes(seal_artifact(proof,purpose=purpose,body=body)))
    assert verify_rescue_receipts(manifest, proof, database_result_sha256='3'*64) == []
    attachment.write_bytes(b'changed')
    assert 'RECEIPT_EVIDENCE_CHANGED' in verify_rescue_receipts(manifest, proof, database_result_sha256='3'*64)


def test_sqlite_snapshot_and_decryption_and_variant_validation(tmp_path):
    import sqlite3
    from cryptography.fernet import Fernet
    from scripts.ops.rescue import snapshot_database, validate_rescue_database
    key=Fernet.generate_key();(tmp_path/'secret.key').write_bytes(key)
    source=tmp_path/'source.db'
    with sqlite3.connect(source) as c:
        c.executescript('CREATE TABLE variants(id INTEGER PRIMARY KEY);INSERT INTO variants VALUES(0);CREATE TABLE rules(id INTEGER PRIMARY KEY,variant_id INTEGER,sort INTEGER,type TEXT,enabled INTEGER);INSERT INTO rules VALUES(1,0,10,"MATCH",1);CREATE TABLE proxy_groups(id INTEGER,variant_id INTEGER,sort INTEGER);CREATE TABLE sources(url_enc TEXT);')
        c.execute('INSERT INTO sources VALUES(?)',(Fernet(key).encrypt(b'private').decode(),))
    snapshot_database(source,tmp_path/'copy.db')
    result=validate_rescue_database(tmp_path/'copy.db',tmp_path/'secret.key')
    assert result['integrity']=='ok' and result['decrypted_values']==1 and result['variants']==1
    with sqlite3.connect(tmp_path/'copy.db') as c:c.execute('UPDATE rules SET variant_id=99')
    with pytest.raises(ValueError, match='VARIANT_REFERENCE_INVALID'):
        validate_rescue_database(tmp_path/'copy.db',tmp_path/'secret.key')


def test_resource_archive_rejects_traversal_before_write(tmp_path):
    import tarfile,io
    from scripts.ops.rescue import restore_resource_archive
    archive=tmp_path/'resources.tar'
    with tarfile.open(archive,'w') as t:
        m=tarfile.TarInfo('../escaped');m.size=1;t.addfile(m,io.BytesIO(b'x'))
    with pytest.raises(ValueError,match='UNSAFE_RESOURCE_ARCHIVE'):
        restore_resource_archive(archive,tmp_path/'restored')
    assert not (tmp_path/'escaped').exists()


def test_restore_preserves_inert_dependency_git_bytes(tmp_path):
    import tarfile,io
    from scripts.ops.rescue import restore_resource_archive
    archive=tmp_path/'resources.tar'
    with tarfile.open(archive,'w') as t:
        for name in ('deps/rule-repo/.git/HEAD','secret.key'):
            m=tarfile.TarInfo(name);m.size=1;t.addfile(m,io.BytesIO(b'x'))
    result=restore_resource_archive(archive,tmp_path/'restored')
    assert result['files']==2
    assert (tmp_path/'restored/deps/rule-repo/.git/HEAD').read_bytes()==b'x'


def test_saved_image_config_digest_blocks_wrong_archive(tmp_path):
    import tarfile,io,json,hashlib
    from scripts.ops.rescue import inspect_saved_image
    config=json.dumps({'architecture':'amd64','os':'linux','rootfs':{'diff_ids':['sha256:'+'3'*64]}}).encode()
    digest='sha256:'+hashlib.sha256(config).hexdigest()
    archive=tmp_path/'image.tar'
    with tarfile.open(archive,'w') as t:
        for name,data in [('config.json',config),('manifest.json',json.dumps([{'Config':'config.json','Layers':[]}]).encode())]:
            m=tarfile.TarInfo(name);m.size=len(data);t.addfile(m,io.BytesIO(data))
    assert inspect_saved_image(archive,digest)['config_digest']==digest
    with pytest.raises(ValueError,match='ARCHIVE_IMAGE_ID_MISMATCH'):
        inspect_saved_image(archive,'sha256:'+'0'*64)


def test_readiness_checks_full_inventory_architecture_and_receipt_binding(tmp_path,monkeypatch):
    from scripts.ops import rescue
    f=tmp_path/'artifact';f.write_bytes(b'real bytes')
    metadata={'architecture':'amd64','master_key_file':'artifact','assets':{role:['artifact'] for role in rescue._REQUIRED_ASSETS},'image_id':'sha256:'+'2'*64,'previous_image_id':'sha256:'+'1'*64}
    manifest=rescue.build_rescue_manifest([f],metadata)
    monkeypatch.setattr(rescue,'validate_rescue_database',lambda *a:{'integrity':'ok'})
    monkeypatch.setattr(rescue,'verify_rescue_receipts',lambda *a,**k:[])
    monkeypatch.setattr(rescue,'inspect_saved_image',lambda *a:{'architecture':'amd64','os':'linux'})
    assert rescue.verify_rescue_readiness(tmp_path,manifest,None,architecture='amd64')==[]
    assert 'ARCHITECTURE_MISMATCH' in rescue.verify_rescue_readiness(tmp_path,manifest,None,architecture='arm64')
    del metadata['assets']['router_nft']
    assert 'RESOURCE_INVENTORY_INCOMPLETE' in rescue.verify_rescue_readiness(tmp_path,manifest,None,architecture='amd64')


def test_resource_rehearsal_stops_before_docker_on_changed_source(tmp_path):
    import json
    from scripts.ops.rescue import rehearse_resources,build_rescue_manifest
    file=tmp_path/'resources.tar';file.write_bytes(b'original')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(build_rescue_manifest([file],{})))
    file.write_bytes(b'changed')
    def forbidden(argv):raise AssertionError('must not reach docker')
    with pytest.raises(ValueError,match='HASH_MISMATCH'):
        rehearse_resources(manifest,tmp_path/'restored',tmp_path/'proof',run=forbidden)


def test_verify_cli_can_pass_with_real_manifest_and_bound_receipts(tmp_path,capsys):
    import sqlite3,json,hashlib
    from cryptography.fernet import Fernet
    from scripts.ops import rescue
    from scripts.ops.evidence import init_run,seal_artifact,canonical_bytes
    key=Fernet.generate_key();(tmp_path/'key').write_bytes(key)
    with sqlite3.connect(tmp_path/'db') as c:
        c.executescript('CREATE TABLE variants(id INTEGER);INSERT INTO variants VALUES(0);CREATE TABLE rules(id INTEGER,variant_id INTEGER,sort INTEGER,type TEXT,enabled INTEGER);CREATE TABLE proxy_groups(id INTEGER,variant_id INTEGER,sort INTEGER);')
    (tmp_path/'bytes').write_bytes(b'frozen fixture resource')
    metadata={'architecture':'amd64','master_key_file':'key','assets':{r:['bytes'] for r in rescue._REQUIRED_ASSETS},'previous_image_id':'sha256:'+'1'*64,'image_id':'sha256:'+'2'*64}
    metadata['assets']['database']=['db']
    import tarfile,io
    for name,id_key in [('old_image','previous_image_id'),('new_image','image_id')]:
        config=json.dumps({'architecture':'amd64','os':'linux','rootfs':{'diff_ids':[]},'fixture':name}).encode()
        metadata[id_key]='sha256:'+hashlib.sha256(config).hexdigest()
        with tarfile.open(tmp_path/(name+'.tar'),'w') as t:
            for member,data in [('config.json',config),('manifest.json',b'[{"Config":"config.json","Layers":[]}]')]:
                m=tarfile.TarInfo(member);m.size=len(data);t.addfile(m,io.BytesIO(data))
        metadata['assets'][name]=[name+'.tar']
    manifest=rescue.build_rescue_manifest([tmp_path/'db',tmp_path/'key',tmp_path/'bytes',tmp_path/'old_image.tar',tmp_path/'new_image.tar'],metadata)
    (tmp_path/'manifest.json').write_bytes(canonical_bytes(manifest))
    sha=hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    directory=Path(init_run(tmp_path/'proofs',{'role':'nas'},phase='OFFLINE')['proof_dir'])
    (directory/'observation').write_bytes(b'test-only trusted observation')
    common={'manifest_sha256':sha,'evidence_hashes':{'observation':hashlib.sha256(b'test-only trusted observation').hexdigest()}}
    database_sha=hashlib.sha256(canonical_bytes(rescue.validate_rescue_database(tmp_path/'db',tmp_path/'key'))).hexdigest()
    bodies={
      'rescue_path':{**common,'proxy_dependency_disconnected':True,'retrieval_transport':'independent_wan','management_transport':'serial','protected_management_vps':True,'retrieved_manifest_sha256':sha},
      'rescue_resources':{**common,'database_result_sha256':database_sha,'old_code_image_id':metadata['previous_image_id'],'old_code_readable':True,'resources_restored':True},
      'rescue_rehearsal':{**common,'architecture':'amd64','network_mode':'none','host_mounts':False,'image_sequence':[metadata['previous_image_id'],metadata['image_id'],metadata['previous_image_id']]},
    }
    for purpose,body in bodies.items():(directory/(purpose+'.receipt.json')).write_bytes(canonical_bytes(seal_artifact(directory,purpose=purpose,body=body)))
    assert rescue.main(['verify','--manifest',str(tmp_path/'manifest.json'),'--proof-dir',str(directory),'--architecture','amd64'])==0
    assert '"blockers": []' in capsys.readouterr().out
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.evidence import verified_proofs
    plan={'operation':OPERATION_REGISTRY['nas.production.image_upgrade'],'plan_sha':'4'*64,'predecessor':'0'*64}
    plan_path=directory/'operation.plan.json';plan_path.write_bytes(canonical_bytes(seal_artifact(directory,purpose='operation_plan',body=plan)))
    for f in directory.iterdir():
        if f.is_file():f.chmod(0o600)
    assert rescue.main(['verify','--manifest',str(tmp_path/'manifest.json'),'--proof-dir',str(directory),'--architecture','amd64','--operation-plan',str(plan_path)])==0
    assert verified_proofs(directory,operation_id='nas.production.image_upgrade',plan_sha='4'*64,predecessor='0'*64)['rescue_verified'] is True
    from scripts.ops.evidence import EvidenceError
    (tmp_path/'bytes').write_bytes(b'changed after acceptance')
    with pytest.raises(EvidenceError,match='RESCUE_EVIDENCE_INVALID'):
        verified_proofs(directory,operation_id='nas.production.image_upgrade',plan_sha='4'*64,predecessor='0'*64)
    (tmp_path/'bytes').write_bytes(b'frozen fixture resource')


    bodies['rescue_path']['retrieval_transport']='same_proxy'
    (directory/'rescue_path.receipt.json').write_bytes(canonical_bytes(seal_artifact(directory,purpose='rescue_path',body=bodies['rescue_path'])))
    assert rescue.main(['verify','--manifest',str(tmp_path/'manifest.json'),'--proof-dir',str(directory),'--architecture','amd64'])==42


def test_readiness_rejects_invalid_saved_image_bytes(tmp_path,monkeypatch):
    from scripts.ops import rescue
    f=tmp_path/'artifact';f.write_bytes(b'not a saved image')
    metadata={'architecture':'amd64','master_key_file':'artifact','assets':{r:['artifact'] for r in rescue._REQUIRED_ASSETS},'image_id':'sha256:'+'2'*64,'previous_image_id':'sha256:'+'1'*64}
    monkeypatch.setattr(rescue,'validate_rescue_database',lambda *a:{'integrity':'ok'})
    monkeypatch.setattr(rescue,'verify_rescue_receipts',lambda *a,**k:[])
    assert 'IMAGE_ARCHIVE_INVALID' in rescue.verify_rescue_readiness(tmp_path,rescue.build_rescue_manifest([f],metadata),None,architecture='amd64')


def test_build_failure_is_inside_digest_rollback_trap():
    body=(Path(__file__).resolve().parents[2]/'scripts/deploy.sh').read_text(encoding='utf-8')
    assert "trap 'restore_previous' ERR" in body
    assert body.index("trap 'restore_previous' ERR") < body.index('if [ -n "${DEPLOY_PROXY:-}" ]')


@pytest.mark.skipif(sys.platform=='win32',reason='requires POSIX executable fixtures; also exercised in WSL')
def test_real_deploy_shell_with_fake_ssh_restores_digest_after_build_failure(tmp_path):
    import os,subprocess,json
    root=Path(__file__).resolve().parents[2]
    tools=tmp_path/'tools';tools.mkdir()
    old,new='sha256:'+'1'*64,'sha256:'+'2'*64
    state=tmp_path/'state';state.write_text(old)
    log=tmp_path/'commands'
    docker=tools/'docker'
    docker.write_text('''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:];s=Path(os.environ['FIXTURE_STATE'])
with open(os.environ['FIXTURE_LOG'],'a') as f:f.write(json.dumps(a)+'\\n')
if a[0]=='inspect':print(s.read_text())
elif a[0]=='compose':
 if '--build' in a:s.write_text('sha256:'+'2'*64);sys.exit(1)
 flags=[i for i,v in enumerate(a) if v=='-f']
 override=json.loads(Path(a[flags[-1]+1]).read_text())
 s.write_text(override['services']['magicpanel']['image'])
''')
    (tools/'ssh').write_text('#!/bin/bash\nbash -c "${@: -1}"\n')
    (tools/'rsync').write_text('#!/bin/bash\nexit 0\n')
    (tools/'git').write_text('#!/bin/bash\nif [ "$1" = "ls-files" ]; then printf "scripts/ops/rescue.py\\n"; fi\n')
    for f in tools.iterdir():f.chmod(0o755)
    environment={**os.environ,'PATH':str(tools)+':'+os.environ['PATH'],'NAS_HOST':'fixture','NAS_DIR':str(tmp_path/'nas'),'FIXTURE_STATE':str(state),'FIXTURE_LOG':str(log),'PYTHONPATH':str(root),'PYTHONUTF8':'1'}
    (tmp_path/'nas').mkdir()
    result=subprocess.run(['bash',str(root/'scripts/deploy.sh'),'--fast'],cwd=root,env=environment,capture_output=True,text=True)
    assert result.returncode==1,result.stdout+result.stderr
    assert state.read_text()==old
    commands=[json.loads(x) for x in log.read_text().splitlines()]
    restores=[a for a in commands if a[0]=='compose' and '--no-build' in a]
    assert len(restores)==1 and restores[0][-2:]==['--pull','never']


@pytest.mark.parametrize('manifest',[None,[],{'schema':1,'files':[None]}, {'schema':1,'files':[{'path':[]}]}])
def test_malformed_manifest_is_rejected_without_traceback(tmp_path,manifest):
    from scripts.ops.rescue import verify_rescue_manifest
    assert 'INVALID_MANIFEST' in verify_rescue_manifest(tmp_path,manifest)
