"""DNS owner bundle 准备；不应用、不写入路由器。"""
from ..compiler.dns_intent import digest


class ScopeConflict(ValueError):
    pass


def combine_scopes(plans: list[dict]) -> dict:
    """相同 owner+shared scope 的域名意图冲突即阻塞，不做最后发布者覆盖。"""
    owners: dict[tuple[str, str, str], tuple[dict, dict]] = {}
    conflicts = []
    for plan in plans:
        scope = plan.get('dns_scope')
        owner = plan.get('owner_target')
        if scope != 'shared':
            continue
        for entry in plan.get('entries', []):
            key = (owner, scope, entry.get('domain', '').lower())
            if key in owners and owners[key][0]['resolver'] != entry.get('resolver'):
                conflicts.append({'domain': entry.get('domain'), 'variants': [
                    owners[key][1].get('variant_id'), plan.get('variant_id')]})
            else:
                owners[key] = (entry, plan)
    if conflicts:
        raise ScopeConflict(conflicts)
    entries = sorted(({'owner_target': key[0], **value} for key, value in owners.items()),
                     key=lambda item: (item['owner_target'], item['domain']))
    return {'schema': 'v1', 'shared_scope': 'combined', 'entries': entries,
            'digest': digest({'entries': entries})}


def prepare_bundle(client_artifacts: list[dict], owner_outputs: list[dict], *,
                   predecessor_sha: str | None) -> dict:
    """生成脱敏摘要与私密 output 引用；URL token 不进 manifest。"""
    routes = []
    private_outputs = []
    for artifact in client_artifacts:
        path = artifact.get('path', '')
        route_hash = digest({'path': path, 'body': bytes(artifact.get('body', b'')).hex(),
                             'kind': artifact.get('kind')})
        routes.append({'route_hash': route_hash,
                       'path_hash': digest(path)[:24], 'kind': artifact.get('kind')})
    for output in owner_outputs:
        private_outputs.append({'owner_target': output.get('owner_target'),
                                'output_sha256': bytes(output.get('output', b'')).hex()})
    safe_manifest = {'schema': 'v1', 'predecessor_sha': predecessor_sha,
                     'route_hashes': routes, 'owner_outputs': private_outputs}
    bundle_sha = digest({'manifest': safe_manifest, 'predecessor': predecessor_sha})
    return {'bundle_sha': bundle_sha, 'predecessor_sha': predecessor_sha,
            'state': 'prepared', 'safe_manifest': safe_manifest}
