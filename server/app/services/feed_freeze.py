"""旧 feed 与引用子资源的加密冻结层。"""
import base64
import hashlib
import json
import os
from pathlib import Path

from .. import security


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _atomic_text(path: Path, text: str) -> None:
    temp = path.with_suffix(path.suffix + '.new')
    with temp.open('w', encoding='ascii', newline='\n') as handle:
        handle.write(text + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _route_hash(route: dict) -> str:
    return hashlib.sha256(_canonical({
        'path': route['path'], 'query': route['query'],
        'body_sha256': hashlib.sha256(route['body']).hexdigest(),
        'content_type': route['content_type'],
    })).hexdigest()


def prepare_freeze(data: dict, *, destination: Path) -> dict:
    """把最终 envelope 和递归引用字节写入私密目录；不生成任何公开清单。"""
    routes = data.get('routes')
    if not isinstance(routes, list) or not routes:
        raise ValueError('freeze_routes_missing')
    normalized = []
    seen = set()
    for route in routes:
        path = route.get('path')
        if not isinstance(path, str) or not path.startswith('/') or '..' in path:
            raise ValueError('freeze_path_invalid')
        query = route.get('query', '')
        if not isinstance(query, str):
            raise ValueError('freeze_query_invalid')
        body = route.get('body')
        if isinstance(body, str):
            body = body.encode('utf-8')
        if not isinstance(body, bytes):
            raise ValueError('freeze_body_invalid')
        references = route.get('references', [])
        if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
            raise ValueError('freeze_reference_invalid')
        key = (path, query)
        if key in seen:
            raise ValueError('freeze_route_duplicate')
        seen.add(key)
        normalized.append({**route, 'body': body})
    available = {(route['path'], route.get('query', '')) for route in normalized}
    missing = sorted({reference for route in normalized for reference in route['references']
                      if (reference, '') not in available})
    if missing:
        raise ValueError('freeze_reference_missing:' + ','.join(missing))
    destination.mkdir(parents=True, exist_ok=True)
    try:
        destination.chmod(0o700)
    except OSError:
        pass
    stored = []
    route_hashes = {}
    for route in normalized:
        route_hash = _route_hash(route)
        route_hashes[route_hash] = {
            'path': hashlib.sha256(route['path'].encode()).hexdigest()[:24],
            'query': route['query'], 'content_type': route['content_type'],
            'body_sha256': hashlib.sha256(route['body']).hexdigest(),
            'byte_length': len(route['body']),
            'references': route['references'],
        }
        body_file = destination / f'{route_hash}.body'
        body_file.write_bytes(security.encrypt_bytes(route['body']))
        try:
            body_file.chmod(0o600)
        except OSError:
            pass
        stored.append({'route_hash': route_hash, 'path': route['path'],
                       'query': route['query'], 'content_type': route['content_type'],
                       'references': route['references'],
                       'body_base64': base64.b64encode(route['body']).decode('ascii')})
    manifest = {
        'schema': 1, 'routes': stored, 'route_hashes': route_hashes, 'ready': all(
            (route['path'], route.get('query', '')) in available
            for route in normalized),
    }
    contract_sha = hashlib.sha256(_canonical(route_hashes)).hexdigest()
    manifest['contract_sha'] = contract_sha
    manifest_file = destination / 'manifest.enc'
    manifest_file.write_text(security.encrypt_text(_canonical(manifest).decode()), encoding='utf-8')
    try:
        manifest_file.chmod(0o600)
    except OSError:
        pass
    return {'contract_sha': contract_sha, 'state': 'prepared', 'ready': manifest['ready'],
            'route_hashes': route_hashes}


def _manifest(root: Path) -> tuple[dict, dict]:
    raw = json.loads(security.decrypt_text((root / 'manifest.enc').read_text(encoding='utf-8')))
    hashes = {route['route_hash']: route for route in raw['routes']}
    return raw, hashes


def _load(root: Path) -> tuple[dict, dict]:
    pointer = root / 'ACTIVE'
    if not pointer.exists():
        raise ValueError('freeze_not_armed')
    expected = pointer.read_text(encoding='ascii').strip()
    raw, hashes = _manifest(root)
    if raw.get('contract_sha') != expected:
        raise ValueError('freeze_pointer_mismatch')
    return raw, hashes


def verify_freeze(root: Path) -> dict:
    raw, routes = _load(root)
    for stored in raw['routes']:
        body_file = root / f"{stored['route_hash']}.body"
        body = security.decrypt_bytes(body_file.read_bytes())
        if hashlib.sha256(body).hexdigest() != raw['route_hashes'][stored['route_hash']]['body_sha256']:
            raise ValueError('freeze_body_hash_mismatch')
    return {'contract_sha': raw['contract_sha'], 'ready': raw['ready'],
            'routes': len(routes), 'state': 'armed'}


def arm_freeze(root: Path, *, expected_sha: str) -> dict:
    if not expected_sha:
        raise ValueError('freeze_expected_sha_missing')
    raw, routes = _manifest(root)
    if raw['contract_sha'] != expected_sha:
        raise ValueError('freeze_expected_sha_mismatch')
    for stored in raw['routes']:
        body = security.decrypt_bytes((root / f"{stored['route_hash']}.body").read_bytes())
        if hashlib.sha256(body).hexdigest() != raw['route_hashes'][stored['route_hash']]['body_sha256']:
            raise ValueError('freeze_body_hash_mismatch')
        referenced = {(item['path'], item.get('query', '')) for item in raw['routes']}
        if any((reference, '') not in referenced for reference in stored['references']):
            raise ValueError('freeze_reference_missing')
    _atomic_text(root / 'ACTIVE', expected_sha)
    return {'contract_sha': expected_sha, 'state': 'armed', 'routes': len(routes)}


def lookup_frozen(root: Path, *, path: str, query: str, method: str,
                  identity_ok: bool = True) -> dict | None:
    if not identity_ok or method not in ('GET', 'HEAD'):
        return None
    try:
        raw, routes = _load(root)
    except (ValueError, FileNotFoundError, OSError):
        return None
    candidates = [route for route in raw['routes']
                  if route['path'] == path and route['query'] == query]
    if len(candidates) != 1:
        return None
    route = candidates[0]
    body = security.decrypt_bytes((root / f"{route['route_hash']}.body").read_bytes())
    digest = hashlib.sha256(body).hexdigest()
    return {'body': body, 'content_type': route['content_type'],
            'etag': digest[:32], 'references': route['references']}


def release_freeze(root: Path, *, expected_sha: str, receipt: dict) -> dict:
    if not isinstance(receipt, dict) or receipt.get('contract_sha') != expected_sha:
        raise ValueError('freeze_receipt_mismatch')
    if not receipt.get('owner_load_receipts'):
        raise ValueError('freeze_owner_receipt_missing')
    raw, _ = _load(root)
    if raw['contract_sha'] != expected_sha:
        raise ValueError('freeze_expected_sha_mismatch')
    _atomic_text(root / 'RELEASED', json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                               separators=(',', ':')))
    (root / 'ACTIVE').unlink(missing_ok=True)
    return {'contract_sha': expected_sha, 'state': 'released',
            'receipt_sha256': hashlib.sha256(_canonical(receipt)).hexdigest()}
