"""固定镜像ID的离线救援；不连接SSH，不下载或构建镜像。"""
from __future__ import annotations
import argparse
import os
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sqlite3
from contextlib import closing
import time
import uuid
import tarfile
import gzip
import tempfile
from scripts.ops.evidence import canonical_bytes, private_path, private_write, verify_artifact, seal_artifact, write_proof, EvidenceError

_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')


def _image(value):
    if not isinstance(value, str) or not _IMAGE.fullmatch(value):
        raise ValueError('INVALID_IMAGE_DIGEST')
    return value


def _sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build_rescue_manifest(files: list[Path], metadata: dict) -> dict:
    entries = []
    seen = set()
    for file in files:
        file = Path(file)
        if file.is_symlink() or not file.is_file() or file.name in seen:
            raise ValueError('UNSAFE_FILE')
        seen.add(file.name)
        entries.append({'path': file.name, 'size': file.stat().st_size, 'sha256': _sha(file)})
    return {'schema': 1, 'files': entries, 'metadata': metadata}


def verify_rescue_manifest(root: Path, manifest: dict) -> list[str]:
    errors = []
    root = Path(root).resolve()
    if not isinstance(manifest,dict) or manifest.get('schema') != 1 or not isinstance(manifest.get('files'), list) or not manifest['files']:
        return ['INVALID_MANIFEST']
    seen = set()
    for entry in manifest['files']:
        if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):
            return ['INVALID_MANIFEST']
        name = entry.get('path', '')
        if not name or name in seen or '/' in name or '\\' in name or ':' in name or name in ('.', '..'):
            errors.append('UNSAFE_FILE'); continue
        seen.add(name)
        file = root / name
        if file.is_symlink() or not file.is_file():
            errors.append('MISSING_FILE'); continue
        if file.stat().st_size != entry.get('size') or _sha(file) != entry.get('sha256'):
            errors.append('HASH_MISMATCH')
    return sorted(set(errors))


def snapshot_database(source: Path, destination: Path) -> None:
    """SQLite backup API包含WAL已提交状态，绝不复制活动DB文件。"""
    destination = Path(destination)
    private_path(destination.parent)
    private_write(destination, b'')
    try:
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def validate_rescue_database(database: Path, key_path: Path) -> dict:
    from cryptography.fernet import Fernet, InvalidToken
    from server.app.services.backup_tables import ENCRYPTED_COLUMNS, ENCRYPTED_SETTINGS
    key = Path(key_path).read_bytes().strip()
    fernet = Fernet(key)
    decrypted = 0
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('DATABASE_INTEGRITY_FAILED')
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') OR upper(sql) LIKE 'CREATE VIRTUAL%'").fetchone():
            raise ValueError('DATABASE_EXECUTABLE_SCHEMA')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'variants', 'rules', 'proxy_groups'} <= tables:
            raise ValueError('VARIANT_TABLES_REQUIRED')
        variants = {r[0] for r in conn.execute('SELECT id FROM variants')}
        for table in ('rules', 'proxy_groups'):
            for variant, order in conn.execute(f'SELECT variant_id,sort FROM "{table}"'):
                if variant not in variants:
                    raise ValueError('VARIANT_REFERENCE_INVALID')
                if type(order) is not int or order < 0:
                    raise ValueError('POLICY_SORT_INVALID')
        for variant in variants:
            types = [r[0] for r in conn.execute('SELECT type FROM rules WHERE variant_id=? AND enabled=1 ORDER BY sort,id',(variant,))]
            if any(t in ('MATCH','FINAL') for t in types[:-1]):
                raise ValueError('MATCH_NOT_LAST')
        def check(value, codec):
            nonlocal decrypted
            if value is None or value == '':
                return
            if not isinstance(value, str):
                raise ValueError('CIPHERTEXT_INVALID')
            if codec == 'payload':
                if not value.startswith('enc:v1:'):
                    return
                value = value[len('enc:v1:'):]
            try:
                fernet.decrypt(value.encode('ascii'))
            except (InvalidToken, UnicodeError):
                raise ValueError('CIPHERTEXT_DECRYPT_FAILED') from None
            decrypted += 1
        for (table,column),codec in ENCRYPTED_COLUMNS.items():
            if table in tables and column in {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}:
                for row in conn.execute(f'SELECT "{column}" FROM "{table}"'):
                    check(row[0],codec)
        if 'settings' in tables:
            for key,value in conn.execute('SELECT key,value FROM settings'):
                if key in ENCRYPTED_SETTINGS:
                    check(value,ENCRYPTED_SETTINGS[key])
        return {'integrity':'ok', 'variants':len(variants), 'decrypted_values':decrypted,
                'rules':conn.execute('SELECT COUNT(*) FROM rules').fetchone()[0],
                'proxy_groups':conn.execute('SELECT COUNT(*) FROM proxy_groups').fetchone()[0]}


def daemon_identity(run) -> dict:
    raw=run(['docker','info','--format','{{.ID}}'])
    if not raw:
        raise ValueError('DAEMON_ID_REQUIRED')
    arch=run(['docker','info','--format','{{.Architecture}}'])
    os_type=run(['docker','info','--format','{{.OSType}}'])
    return {'id_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'architecture':{'x86_64':'amd64','aarch64':'arm64'}.get(arch,arch),'os_type':os_type}


def _binding(manifest, directory, daemon):
    run=json.loads((private_path(Path(directory))/'run.json').read_text(encoding='utf-8'))
    return {'manifest_sha256':hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
            'inventory_sha256':run['inventory_sha'],'daemon':daemon}


def _seal_machine_observation(directory, purpose, observation):
    directory=private_path(Path(directory))
    filename={'rescue_resources':'resources-observation.json','rescue_rehearsal':'compose-observation.json'}[purpose]
    private_write(directory/filename,canonical_bytes(observation))
    body={'schema':2,'manifest_sha256':observation['binding']['manifest_sha256'],
          'observation_file':filename,'evidence_hashes':{filename:_sha(directory/filename)}}
    private_write(directory/(purpose+'.receipt.json'),canonical_bytes(seal_artifact(directory,purpose=purpose,body=body)))
    return body


def _machine_observation(directory, purpose, body, manifest, database_sha, root):
    filename={'rescue_resources':'resources-observation.json','rescue_rehearsal':'compose-observation.json'}[purpose]
    if body.get('schema')!=2 or body.get('observation_file')!=filename or set(body['evidence_hashes'])!={filename}:
        raise ValueError('MACHINE_OBSERVATION_REQUIRED')
    observation=json.loads((directory/filename).read_text(encoding='utf-8'))
    if (not isinstance(observation,dict) or observation.get('schema')!=2 or
            set(observation)!={'schema','kind','binding','expected','observed','steps'}):
        raise ValueError('MACHINE_OBSERVATION_REQUIRED')
    metadata=manifest['metadata'];binding=observation.get('binding',{})
    inventory=metadata.get('target_inventory')
    target=metadata.get('target_daemon')
    run=json.loads((directory/'run.json').read_text(encoding='utf-8'))
    if (set(binding)!={'manifest_sha256','inventory_sha256','daemon'} or
            not isinstance(inventory,dict) or inventory.get('role')!='nas' or
            inventory.get('daemon_identity')!=target or
            not isinstance(target,dict) or set(target)!={'id_sha256','architecture','os_type'} or
            not re.fullmatch('[a-f0-9]{64}',str(target.get('id_sha256',''))) or
            target.get('os_type')!='linux' or target.get('architecture')!=metadata['architecture'] or
            binding.get('manifest_sha256')!=body['manifest_sha256'] or
            binding.get('inventory_sha256')!=hashlib.sha256(canonical_bytes(inventory)).hexdigest() or
            binding.get('inventory_sha256')!=run['inventory_sha'] or run['target_role']!='nas'):
        raise ValueError('MACHINE_TARGET_BINDING_REQUIRED')
    if binding.get('daemon')!=target:
        raise ValueError('TARGET_DAEMON_MISMATCH')
    if root is None:
        raise ValueError('MACHINE_SOURCE_BYTES_REQUIRED')
    root=Path(root);assets=metadata['assets'];expected=observation.get('expected',{});actual=observation.get('observed',{})
    old=metadata['previous_image_id'];new=metadata.get('image_id')
    if purpose=='rescue_resources':
        archive=root/assets['resources_archive'][0]
        catalog=resource_archive_catalog(archive)
        expected_fields={'old_image_id':old,'database_sha256':_sha(root/assets['database'][0]),
                         'resources_archive_sha256':_sha(archive)}
        if observation.get('kind')!='resource_restore' or expected!=expected_fields:
            raise ValueError('RESOURCE_OBSERVATION_MISMATCH')
        database=actual.get('database',{});old_code=actual.get('old_code',{})
        if (actual.get('runtime_image_id')!=old or actual.get('config_digest')!=inspect_saved_image(root/assets['old_image'][0],old)['config_digest'] or
                actual.get('resources')!=catalog or
                hashlib.sha256(canonical_bytes(database)).hexdigest()!=database_sha or
                set(old_code)!={'old_code_imported','integrity','decrypted_values','variants','local_runtime_image'} or
                old_code.get('old_code_imported') is not True or
                type(old_code.get('decrypted_values')) is not int or type(old_code.get('variants')) is not int or
                old_code.get('local_runtime_image')!=old or old_code.get('integrity')!='ok' or
                old_code.get('decrypted_values')!=database.get('decrypted_values') or
                old_code.get('variants')!=database.get('variants')):
            raise ValueError('RESOURCE_OBSERVATION_MISMATCH')
        steps=[{'action':'archive_verified','expected':expected_fields['resources_archive_sha256'],'observed':expected_fields['resources_archive_sha256']},
               {'action':'resources_restored','expected':catalog['resource_digest'],'observed':catalog['resource_digest']},
               {'action':'database_verified','expected':database_sha,'observed':database_sha},
               {'action':'old_code_read','expected':old,'observed':old}]
        if observation.get('steps')!=steps:
            raise ValueError('RESOURCE_STEPS_MISMATCH')
    else:
        infos=[inspect_saved_image(root/assets[role][0],image) for role,image in [('old_image',old),('new_image',new)]]
        if (observation.get('kind')!='image_restore' or expected!={'image_sequence':[old,new,old]} or
                actual.get('archives')!=infos or actual.get('network_mode')!='none' or actual.get('host_mounts') is not False):
            raise ValueError('IMAGE_OBSERVATION_MISMATCH')
        steps=observation.get('steps',[])
        if len(steps)!=6:
            raise ValueError('IMAGE_STEPS_MISMATCH')
        for step,info,image in zip(steps[:2],infos,[old,new]):
            if step!={'action':'load','archive_sha256':info['archive_sha256'],'expected_image_id':image,'observed_image_id':image}:
                raise ValueError('IMAGE_LOAD_OBSERVATION_MISMATCH')
        for step,image in zip(steps[2:5],[old,new,old]):
            if (set(step)!={'action','expected_image_id','observed_image_id','running','container_id_sha256'} or
                    step['action']!='switch' or step['expected_image_id']!=image or step['observed_image_id']!=image or
                    step['running'] is not True or not re.fullmatch('[a-f0-9]{64}',str(step['container_id_sha256']))):
                raise ValueError('IMAGE_RESTORE_OBSERVATION_MISMATCH')
        if steps[5]!={'action':'cleanup','remaining_container_ids':[]}:
            raise ValueError('IMAGE_CLEANUP_OBSERVATION_MISMATCH')
    return observation


def verify_rescue_receipts(manifest: dict, proof_dir: Path | None, *, database_result_sha256: str, root: Path | None=None) -> list[str]:
    """人工观察必须单独签名并附原件哈希；fixture收据不能替代整包实测。"""
    sha = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    metadata = manifest.get('metadata', {})
    errors=[]
    purposes = {'rescue_path':'INDEPENDENT_PATH_REQUIRED', 'rescue_resources':'RESOURCE_RESTORE_REQUIRED',
                'rescue_rehearsal':'RESTORE_REHEARSAL_REQUIRED'}
    for purpose,missing in purposes.items():
        if proof_dir is None:
            errors.append(missing); continue
        try:
            directory = private_path(Path(proof_dir))
            path = directory / (purpose + '.receipt.json')
            if path.is_symlink():
                raise ValueError('RECEIPT_UNSAFE')
            body = verify_artifact(directory,json.loads(path.read_text(encoding='utf-8')),purpose=purpose)
            if body.get('manifest_sha256') != sha:
                raise ValueError('RECEIPT_MANIFEST_MISMATCH')
            hashes=body.get('evidence_hashes')
            if not isinstance(hashes,dict) or not hashes:
                raise ValueError('RECEIPT_EVIDENCE_REQUIRED')
            for name,expected in hashes.items():
                if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',name):
                    raise ValueError('RECEIPT_UNSAFE')
                file=directory/name
                if file.is_symlink() or not file.is_file() or _sha(file)!=expected:
                    raise ValueError('RECEIPT_EVIDENCE_CHANGED')
            if purpose=='rescue_path':
                valid=(body.get('proxy_dependency_disconnected') is True and
                       body.get('retrieval_transport') in ('cellular','independent_wan') and
                       body.get('management_transport') in ('lan','serial') and
                       body.get('protected_management_vps') is True and
                       body.get('retrieved_manifest_sha256')==sha)
            else:
                _machine_observation(directory,purpose,body,manifest,database_result_sha256,root)
                valid=True
            if not valid:
                errors.append(missing)
        except FileNotFoundError:
            errors.append(missing)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            code=str(exc)
            errors.append(code if code.startswith(('RECEIPT_','PROOF_','MACHINE_','TARGET_','RESOURCE_','IMAGE_')) else 'RECEIPT_INVALID')
    return sorted(set(errors))


def restore_resource_archive(archive: Path, destination: Path) -> dict:
    """受限私密目录只还原常规字节，不执行脚本、钩子或二进制。"""
    destination=Path(destination)
    if destination.exists():
        raise ValueError('RESTORE_DESTINATION_EXISTS')
    allowed={'secret.key','builds','avatars','deps','bin','core-work','geoip.dat','geosite.dat','country.mmdb'}
    with tarfile.open(archive,'r:*') as source:
        members=source.getmembers();seen=set();total=0
        for member in members:
            name=member.name
            parts=Path(name).parts
            if (not name or name.startswith(('/','\\')) or '\\' in name or ':' in name or
                    '..' in parts or not parts or parts[0] not in allowed or
                    name.casefold() in seen or not(member.isfile() or member.isdir())):
                raise ValueError('UNSAFE_RESOURCE_ARCHIVE')
            seen.add(name.casefold());total+=member.size
            if total>4*1024**3 or len(members)>100000:
                raise ValueError('RESOURCE_ARCHIVE_TOO_LARGE')
        private_path(destination,create=True)
        hashes={};sizes={}
        for member in members:
            target=destination/member.name
            # 根目录已受限且全表拒绝链接；嵌套.git是惰性恢复字节，不调用Git。
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True,mode=0o700)
                target.chmod(0o700)
            else:
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with source.extractfile(member) as stream, target.open('xb') as out:
                    for block in iter(lambda:stream.read(1024*1024),b''):
                        out.write(block)
                target.chmod(0o600)
                hashes[member.name]=_sha(target);sizes[member.name]=member.size
    return {'files':len(hashes),'bytes':total,'resource_digest':hashlib.sha256(canonical_bytes(hashes)).hexdigest(),
            'file_hashes':hashes,'file_sizes':sizes}


def resource_archive_catalog(archive: Path) -> dict:
    hashes={};sizes={}
    with tarfile.open(archive,'r:*') as source:
        for member in source:
            if member.isfile():
                if member.name in hashes or member.size<0 or member.size>4*1024**3:
                    raise ValueError('RESOURCE_ARCHIVE_INVALID')
                h=hashlib.sha256()
                with source.extractfile(member) as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
                hashes[member.name]=h.hexdigest();sizes[member.name]=member.size
            elif not member.isdir():
                raise ValueError('RESOURCE_ARCHIVE_INVALID')
    return {'files':len(hashes),'bytes':sum(sizes.values()),'resource_digest':hashlib.sha256(canonical_bytes(hashes)).hexdigest(),
            'file_hashes':hashes,'file_sizes':sizes}


_REQUIRED_ASSETS=frozenset(('database','resources_archive','old_image','new_image','binaries','rules','providers',
                           'old_bundle','new_bundle','profiles','overlays','router_uci','router_agh',
                           'router_dnsmasq','router_raw','router_runtime','router_nft','router_route'))


def verify_rescue_readiness(root: Path, manifest: dict, proof_dir: Path | None, *, architecture: str) -> list[str]:
    errors=verify_rescue_manifest(root,manifest)
    if 'INVALID_MANIFEST' in errors:
        return errors
    try:
        private_path(Path(root))
    except EvidenceError:
        return ['PRIVATE_RESCUE_ROOT_REQUIRED']
    metadata=manifest.get('metadata',{})
    if not isinstance(metadata,dict):
        return ['INVALID_MANIFEST']
    if metadata.get('architecture') != architecture:
        errors.append('ARCHITECTURE_MISMATCH')
    assets=metadata.get('assets',{})
    names={f['path'] for f in manifest.get('files',[]) if isinstance(f,dict) and 'path' in f}
    if not isinstance(assets,dict) or any(not isinstance(assets.get(role),list) or not assets[role] or
            any(name not in names for name in assets[role]) for role in _REQUIRED_ASSETS):
        errors.append('RESOURCE_INVENTORY_INCOMPLETE')
    if 'RESOURCE_INVENTORY_INCOMPLETE' not in errors and not verify_rescue_manifest(root,manifest):
        for role,id_key in (('old_image','previous_image_id'),('new_image','image_id')):
            try:
                info=inspect_saved_image(Path(root)/assets[role][0],metadata[id_key])
                if info['architecture']!=metadata.get('architecture') or info['os']!='linux':
                    errors.append('ARCHITECTURE_MISMATCH')
            except (OSError,ValueError,KeyError,TypeError,tarfile.TarError):
                errors.append('IMAGE_ARCHIVE_INVALID')
    database_sha=''
    # 数据验读摘要必须来自同一份实际恢复副本，并由资源收据绑定。
    try:
        if 'RESOURCE_INVENTORY_INCOMPLETE' in errors or verify_rescue_manifest(root,manifest):
            raise ValueError('RESOURCE_INVENTORY_INCOMPLETE')
        database=Path(root)/assets['database'][0]
        key=Path(root)/metadata['master_key_file']
        if metadata['master_key_file'] not in names:
            raise ValueError('MASTER_KEY_NOT_IN_MANIFEST')
        result=validate_rescue_database(database,key)
        database_sha=hashlib.sha256(canonical_bytes(result)).hexdigest()
    except (OSError,ValueError,KeyError,IndexError,TypeError,sqlite3.Error):
        errors.append('DATABASE_RESTORE_REQUIRED')
    errors.extend(verify_rescue_receipts(manifest,proof_dir,database_result_sha256=database_sha,root=Path(root)))
    return sorted(set(errors))


def inspect_saved_image(archive: Path, expected: str) -> dict:
    expected=_image(expected)
    with tarfile.open(archive,'r:*') as source:
        members=source.getmembers()
        if len(members)>100000 or len({m.name for m in members})!=len(members):
            raise ValueError('INVALID_IMAGE_ARCHIVE')
        by_name={m.name:m for m in members}
        def member(name, limit=4*1024**3):
            m=by_name.get(name)
            if m is None or not m.isfile() or not 0<=m.size<=limit:
                raise ValueError('IMAGE_LAYER_MEMBER_INVALID')
            return m
        def read_json(name,limit=16*1024*1024):
            return json.load(source.extractfile(member(name,limit)))
        def raw_sha(name):
            h=hashlib.sha256()
            with source.extractfile(member(name)) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
            return 'sha256:'+h.hexdigest()
        manifest=read_json('manifest.json',1024*1024)
        if not isinstance(manifest,list) or len(manifest)!=1:
            raise ValueError('SINGLE_IMAGE_ARCHIVE_REQUIRED')
        config_name=manifest[0]['Config']
        config_digest=raw_sha(config_name)
        config=read_json(config_name)
        diffs=config['rootfs']['diff_ids'];layers=manifest[0]['Layers']
        if not isinstance(diffs,list) or not isinstance(layers,list) or len(diffs)!=len(layers) or len(layers)>256:
            raise ValueError('IMAGE_LAYER_COUNT_MISMATCH')
        observations=[]
        for name,diff in zip(layers,diffs):
            _image(diff)
            m=member(name)
            stored_sha=raw_sha(name)
            if name.startswith('blobs/sha256/') and stored_sha!='sha256:'+name.rsplit('/',1)[1]:
                raise ValueError('IMAGE_LAYER_STORED_DIGEST_MISMATCH')
            with source.extractfile(m) as raw:
                magic=raw.read(4);raw.seek(0)
                if magic==bytes.fromhex('28b52ffd'):
                    raise ValueError('IMAGE_LAYER_ZSTD_UNSUPPORTED')
                decoded=gzip.GzipFile(fileobj=raw) if magic[:2]==b'\x1f\x8b' else raw
                try:
                    with tempfile.SpooledTemporaryFile(max_size=16*1024*1024) as layer:
                        digest=hashlib.sha256();size=0
                        for block in iter(lambda:decoded.read(1024*1024),b''):
                            size+=len(block)
                            if size>4*1024**3:raise ValueError('IMAGE_LAYER_TOO_LARGE')
                            digest.update(block);layer.write(block)
                        if 'sha256:'+digest.hexdigest()!=diff:
                            raise ValueError('IMAGE_LAYER_DIFF_ID_MISMATCH')
                        if size<1024 or size%512:
                            raise ValueError('IMAGE_LAYER_TRUNCATED')
                        layer.seek(-1024,2)
                        if layer.read(1024)!=b'\0'*1024:
                            raise ValueError('IMAGE_LAYER_TRUNCATED')
                        layer.seek(0)
                        with tarfile.open(fileobj=layer,mode='r:') as inner:
                            for entry in inner:
                                if entry.offset_data+entry.size>size:
                                    raise ValueError('IMAGE_LAYER_TRUNCATED')
                except (OSError,EOFError,tarfile.TarError):
                    raise ValueError('IMAGE_LAYER_INVALID') from None
            observations.append({'path':name,'stored_sha256':stored_sha,'stored_bytes':m.size,
                                 'diff_id':diff,'uncompressed_bytes':size})
        # OCI目录中的每个可达描述符也按实际字节校验，不相信blob文件名。
        checked=set();identities={config_digest}
        def descriptor(d):
            digest=_image(d['digest']);name='blobs/sha256/'+digest[7:]
            m=member(name)
            if type(d.get('size')) is not int or m.size!=d['size'] or raw_sha(name)!=digest:
                raise ValueError('IMAGE_LAYER_DESCRIPTOR_MISMATCH')
            if digest in checked:return
            checked.add(digest)
            media=d.get('mediaType','')
            if 'image.index' in media or 'manifest.list' in media:
                for child in read_json(name).get('manifests',[]):descriptor(child)
            elif 'image.manifest' in media or 'manifest.v2' in media:
                doc=read_json(name);descriptor(doc['config'])
                for child in doc['layers']:descriptor(child)
                if (doc['config']['digest']==config_digest and
                        [d['digest'] for d in doc['layers']]==[o['stored_sha256'] for o in observations]):
                    identities.add(digest)
                else:
                    raise ValueError('IMAGE_LAYER_DESCRIPTOR_MAPPING_MISMATCH')
        if 'index.json' in by_name:
            for d in read_json('index.json').get('manifests',[]):descriptor(d)
        if expected not in identities:
            raise ValueError('ARCHIVE_IMAGE_ID_MISMATCH')
        return {'config_digest':config_digest,'image_identity':expected,'architecture':config['architecture'],'os':config['os'],
                'diff_ids':diffs,'layers':observations,'archive_sha256':_sha(Path(archive))}


def old_code_readability(restored: Path, runtime_image: str, *, run=None) -> dict:
    """仅加载镜像内旧代码，读副本，不运行仓库脚本/后台服务/迁移。"""
    if run is None:
        run=_run
    image=_image(runtime_image)
    _inspect_image(image,run)
    from server.app.services.backup_tables import ENCRYPTED_COLUMNS, ENCRYPTED_SETTINGS
    codecs=[[t,c,k] for (t,c),k in ENCRYPTED_COLUMNS.items()]
    script="""import sqlite3,json
from app import db,security
from app.compiler import render
conn=sqlite3.connect('file:/rescue/magicpanel.db?mode=ro',uri=True)
conn.execute('PRAGMA trusted_schema=OFF')
assert conn.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
count=0
tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def check(value,codec):
 global count
 if not value:return
 if codec=='payload':
  if not value.startswith('enc:v1:'):return
  value=value[len('enc:v1:'):]
 security.decrypt_text(value)
 count+=1
for table,column,codec in CODECS:
 if table in tables and column in {r[1] for r in conn.execute('PRAGMA table_info('+table+')')}:
  for row in conn.execute('SELECT '+column+' FROM '+table):check(row[0],codec)
if 'settings' in tables:
 for key,value in conn.execute('SELECT key,value FROM settings'):
  if key in SETTINGS:check(value,SETTINGS[key])
print(json.dumps({'old_code_imported':True,'integrity':'ok','decrypted_values':count,'variants':conn.execute('SELECT COUNT(*) FROM variants').fetchone()[0]}))
""".replace('CODECS',repr(codecs)).replace('SETTINGS',repr(ENCRYPTED_SETTINGS))
    argv=['docker','run','--rm','--pull','never','--network','none','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges:true','--mount',
          'type=bind,source='+str(Path(restored).resolve())+',target=/rescue,readonly',
          '--env','MAGICPANEL_DATA_DIR=/rescue','--entrypoint','python',image,'-c',script]
    result=json.loads(run(argv))
    if result.get('old_code_imported') is not True or result.get('integrity')!='ok':
        raise ValueError('OLD_CODE_READ_FAILED')
    return {**result,'local_runtime_image':image}


def rehearse_resources(manifest_path: Path, destination: Path, proof_dir: Path, *, run=None) -> dict:
    if run is None:
        run=_run
    manifest_path=Path(manifest_path)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    errors=verify_rescue_manifest(manifest_path.parent,manifest)
    if errors:
        raise ValueError(errors[0])
    metadata=manifest['metadata'];assets=metadata['assets'];root=manifest_path.parent
    def asset(role):
        name=assets[role][0]
        if name not in {f['path'] for f in manifest['files']}:
            raise ValueError('RESOURCE_NOT_IN_MANIFEST')
        return root/name
    expected=_image(metadata['previous_image_id'])
    runtime=_image(metadata.get('previous_runtime_image_id',expected))
    archived=inspect_saved_image(asset('old_image'),expected)
    daemon=daemon_identity(run)
    run(['docker','image','load','--input',str(asset('old_image'))])
    loaded=_inspect_image(runtime,run)
    if archived['architecture']!=metadata['architecture'] or loaded['Architecture']!=archived['architecture'] or loaded['RootFS']['Layers']!=archived['diff_ids']:
        raise ValueError('LOADED_IMAGE_CONTENT_MISMATCH')
    resources=restore_resource_archive(asset('resources_archive'),destination)
    snapshot_database(asset('database'),Path(destination)/'magicpanel.db')
    database=validate_rescue_database(Path(destination)/'magicpanel.db',Path(destination)/'secret.key')
    old=old_code_readability(destination,runtime,run=run)
    if old['decrypted_values']!=database['decrypted_values'] or old['variants']!=database['variants']:
        raise ValueError('OLD_CODE_DATABASE_MISMATCH')
    database_sha=hashlib.sha256(canonical_bytes(database)).hexdigest()
    expected_fields={'old_image_id':expected,'database_sha256':_sha(asset('database')),
                     'resources_archive_sha256':_sha(asset('resources_archive'))}
    observation={'schema':2,'kind':'resource_restore','binding':_binding(manifest,proof_dir,daemon),
                 'expected':expected_fields,
                 'observed':{'database':database,'resources':resources,'old_code':old,
                             'config_digest':archived['config_digest'],'runtime_image_id':runtime},
                 'steps':[{'action':'archive_verified','expected':expected_fields['resources_archive_sha256'],'observed':expected_fields['resources_archive_sha256']},
                          {'action':'resources_restored','expected':resources['resource_digest'],'observed':resources['resource_digest']},
                          {'action':'database_verified','expected':database_sha,'observed':database_sha},
                          {'action':'old_code_read','expected':expected,'observed':runtime}]}
    return _seal_machine_observation(proof_dir,'rescue_resources',observation)


def compose_image_override(root: Path, digest: str) -> Path:
    digest = _image(digest)
    root = private_path(Path(root), create=True)
    path = root / ('rescue-' + digest[7:] + '.json')
    body = canonical_bytes({'services': {'magicpanel': {'image': digest}}})
    if path.exists():
        if path.is_symlink() or path.read_bytes() != body:
            raise ValueError('OVERRIDE_CHANGED')
    else:
        with path.open('xb') as stream:
            stream.write(body)
    return path


def restore_argv(compose_dir: str, override_path: str) -> list[str]:
    return ['docker', 'compose', '-f', str(Path(compose_dir) / 'docker-compose.yml'),
            '-f', str(override_path), 'up', '-d', '--no-build', '--pull', 'never']


def _run(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=180).stdout.strip()


def _inspect_image(image, run):
    value = json.loads(run(['docker', 'image', 'inspect', _image(image)]))[0]
    if value['Id'] != image:
        raise ValueError('IMAGE_ID_MISMATCH')
    return value


def offline_deploy(manifest_path: Path, compose_dir: Path, *, run=_run, attempts=40, pause=3) -> dict:
    """已加载镜像校验后切换；任意启动/健康错误都按相同argv恢复旧ID。"""
    manifest_path = Path(manifest_path)
    private_path(manifest_path.parent)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    errors = verify_rescue_manifest(manifest_path.parent, manifest)
    if errors:
        raise ValueError(errors[0])
    metadata = manifest['metadata']
    target = _image(metadata['image_id'])
    info = _inspect_image(target, run)
    host_arch = run(['docker', 'info', '--format', '{{.Architecture}}'])
    aliases = {'x86_64': 'amd64', 'aarch64': 'arm64'}
    if info['Architecture'] != metadata['architecture'] or aliases.get(host_arch, host_arch) != info['Architecture']:
        raise ValueError('ARCHITECTURE_MISMATCH')
    previous = _image(run(['docker', 'inspect', '--format', '{{.Image}}', 'magicpanel']))
    _inspect_image(previous, run)
    def apply(image):
        override = compose_image_override(manifest_path.parent, image)
        run(restore_argv(str(compose_dir), str(override)))
        actual = run(['docker', 'inspect', '--format', '{{.Image}}', 'magicpanel'])
        if actual != image:
            raise ValueError('RESTORED_IMAGE_MISMATCH')
    try:
        apply(target)
        for i in range(attempts):
            if run(['docker', 'inspect', '--format', '{{.State.Health.Status}}', 'magicpanel']) == 'healthy':
                return {'restored_image_id': target, 'healthy': True}
            if i + 1 < attempts:
                time.sleep(pause)
        raise ValueError('HEALTH_FAILED')
    except (ValueError, subprocess.SubprocessError):
        apply(previous)
        raise ValueError('DEPLOY_FAILED_OLD_IMAGE_RESTORED') from None


def rehearse_restore(root: Path, old: str, new: str, *, run=_run, archives=None) -> dict:
    """从本包load后仅生成无网络/无宿主挂载的一次性Compose。"""
    old,new=_image(old),_image(new)
    if old==new:
        raise ValueError('DISTINCT_FIXTURE_IMAGES_REQUIRED')
    daemon=daemon_identity(run)
    if not isinstance(archives,list) or len(archives)!=2:
        raise ValueError('IMAGE_ARCHIVES_REQUIRED')
    infos=[inspect_saved_image(Path(archive),image) for archive,image in zip(archives,[old,new])]
    steps=[]
    for archive,image,info in zip(archives,[old,new],infos):
        run(['docker','image','load','--input',str(archive)])
        loaded=_inspect_image(image,run)
        if loaded['Architecture']!=info['architecture'] or loaded['RootFS']['Layers']!=info['diff_ids']:
            raise ValueError('LOADED_IMAGE_CONTENT_MISMATCH')
        steps.append({'action':'load','archive_sha256':info['archive_sha256'],
                      'expected_image_id':image,'observed_image_id':loaded['Id']})
    root=private_path(Path(root),create=True)
    sandbox=private_path(root/('fixture-'+uuid.uuid4().hex),create=True)
    service={'image':old,'network_mode':'none','read_only':True,'cap_drop':['ALL'],
             'security_opt':['no-new-privileges:true'],'user':'65534:65534',
             'entrypoint':['/bin/sh','-c'],'command':['sleep 120'],'restart':'no',
             'stop_grace_period':'1s','healthcheck':{'disable':True}}
    private_write(sandbox/'docker-compose.yml',canonical_bytes({
        'name':'mp-rescue-'+uuid.uuid4().hex,'services':{'magicpanel':service}}))
    base=['docker','compose','-f',str(sandbox/'docker-compose.yml')]
    try:
        for image in (old,new,old):
            override=compose_image_override(sandbox,image)
            run(restore_argv(str(sandbox),str(override)))
            container=run(base+['ps','-q','magicpanel'])
            if not container or not re.fullmatch(r'[a-f0-9]{12,64}',container):
                raise ValueError('FIXTURE_CONTAINER_MISSING')
            actual=run(['docker','inspect','--format','{{.Image}}',container])
            running=run(['docker','inspect','--format','{{.State.Running}}',container])
            if actual!=image or running!='true':
                raise ValueError('FIXTURE_IMAGE_RESTORE_FAILED')
            steps.append({'action':'switch','expected_image_id':image,'observed_image_id':actual,
                          'running':True,'container_id_sha256':hashlib.sha256(container.encode()).hexdigest()})
    finally:
        run(base+['down','--volumes','--remove-orphans'])
    remaining=run(base+['ps','-aq'])
    if remaining:
        raise ValueError('FIXTURE_CLEANUP_FAILED')
    steps.append({'action':'cleanup','remaining_container_ids':[]})
    observation={'schema':2,'kind':'image_restore','daemon':daemon,
                 'expected':{'image_sequence':[old,new,old]},
                 'observed':{'archives':infos,'network_mode':'none','host_mounts':False},'steps':steps}
    private_write(sandbox/'rehearsal.json',canonical_bytes(observation))
    return observation


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare', allow_abbrev=False)
    prepare.add_argument('--root', type=Path, required=True)
    prepare.add_argument('--metadata', type=Path, required=True)
    prepare.add_argument('--file', type=Path, action='append', required=True)
    for command in ('verify', 'rehearse', 'deploy'):
        child = sub.add_parser(command, allow_abbrev=False)
        child.add_argument('--manifest', type=Path, required=True)
        child.add_argument('--proof-dir', type=Path)
        if command == 'verify':
            child.add_argument('--architecture', choices=['amd64','arm64'])
            child.add_argument('--operation-plan',type=Path)
        if command != 'verify':
            child.add_argument('--compose-dir', type=Path, required=True)
        if command == 'rehearse':
            child.add_argument('--mode',choices=['images','resources'],default='images')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            root = private_path(args.root, create=True)
            for file in args.file:
                if file.resolve().parent != root:
                    raise ValueError('FILES_MUST_BE_IN_PRIVATE_ROOT')
            manifest = build_rescue_manifest(args.file, json.loads(args.metadata.read_text(encoding='utf-8')))
            private_write(root/'rescue-manifest.json', canonical_bytes(manifest))
            result = {'manifest_sha256': hashlib.sha256(canonical_bytes(manifest)).hexdigest(), 'blockers': []}
        elif args.command == 'verify':
            manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
            import platform
            arch=args.architecture or {'AMD64':'amd64','x86_64':'amd64','aarch64':'arm64','ARM64':'arm64'}.get(platform.machine(),platform.machine())
            blockers = verify_rescue_readiness(args.manifest.parent,manifest,args.proof_dir,architecture=arch)
            result = {'blockers': sorted(set(blockers))}
            if not blockers and args.operation_plan:
                from scripts.ops.contracts import OPERATION_REGISTRY
                directory=private_path(args.proof_dir)
                plan=verify_artifact(directory,json.loads(args.operation_plan.read_text(encoding='utf-8')),purpose='operation_plan')
                operation=plan['operation']
                if operation!=OPERATION_REGISTRY.get(operation.get('id')):
                    raise ValueError('OPERATION_DEFINITION_MISMATCH')
                body=canonical_bytes(manifest)
                manifest_name='accepted-rescue-manifest.json'
                private_write(directory/manifest_name,body)
                private_write(directory/'rescue-binding.json',canonical_bytes({'root':str(args.manifest.parent.resolve()),'architecture':arch}))
                hashes={manifest_name:_sha(directory/manifest_name),'rescue-binding.json':_sha(directory/'rescue-binding.json')}
                for purpose in ('rescue_path','rescue_resources','rescue_rehearsal'):
                    filename=purpose+'.receipt.json'
                    artifact=json.loads((directory/filename).read_text(encoding='utf-8'))
                    receipt=verify_artifact(directory,artifact,purpose=purpose)
                    hashes[filename]=_sha(directory/filename)
                    hashes.update(receipt['evidence_hashes'])
                write_proof(directory,'rescue_acceptance',operation_id=operation['id'],plan_sha=plan['plan_sha'],
                            predecessor=plan['predecessor'],claims={'rescue_verified':True},evidence_hashes=hashes)
                result['rescue_verified']=True

        else:
            if args.command == 'rehearse':
                if args.mode=='resources':
                    if not args.proof_dir:
                        raise ValueError('PROOF_DIRECTORY_REQUIRED')
                    result=rehearse_resources(args.manifest,args.compose_dir,args.proof_dir)
                    print(json.dumps({'resource_receipt_sha256':hashlib.sha256(canonical_bytes(result)).hexdigest()}))
                    return 0
                manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
                errors = verify_rescue_manifest(args.manifest.parent, manifest)
                if errors:
                    raise ValueError(errors[0])
                metadata = manifest['metadata']
                archives=[args.manifest.parent/metadata['assets'][role][0] for role in ('old_image','new_image')]
                receipt = rehearse_restore(args.compose_dir, metadata['previous_image_id'], metadata['image_id'],archives=archives)
                if args.proof_dir:
                    receipt['binding']=_binding(manifest,args.proof_dir,receipt.pop('daemon'))
                    _seal_machine_observation(args.proof_dir,'rescue_rehearsal',receipt)
                print(json.dumps({'rehearsal_sha256': hashlib.sha256(canonical_bytes(receipt)).hexdigest()}))
                return 0
            result = offline_deploy(args.manifest, args.compose_dir)
        print(json.dumps(result, sort_keys=True))
        return 42 if result.get('blockers') else 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({'blockers': ['RESCUE_OPERATION_FAILED']}))
        return 42


if __name__ == '__main__':
    raise SystemExit(main())
