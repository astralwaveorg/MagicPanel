"""纯恢复/排序 planner；不做 DB、网络或时钟副作用。"""
from datetime import timedelta

from .fingerprints import digest

GOOGLE_TIERS = ('US', 'SG', 'JP')
AI_SERVICES = ("chatgpt", "claude", "perplexity", "grok", "copilot")
# 只改已存在的精确集合规则，保留国内规则和其它规则的首个命中顺序。
SERVICE_RULES = {
    "netflix": ("netflix", "🎞️ 国际影音"),
    "primevideo": ("primevideo", "🎞️ 国际影音"),
    "spotify": ("spotify", "🎞️ 国际影音"),
    "twitch": ("twitch", "🎞️ 国际影音"),
    "bbc": ("bbc", "🎞️ 国际影音"),
    "biliintl": ("bilibili_intl", "🎞️ 国际影音"),
    "openai": ("chatgpt", "🧠 人工智能"),
    "anthropic": ("claude", "🤖 Claude"),
    "perplexity": ("perplexity", "🧠 人工智能"),
    "tiktok": ("tiktok", "🎵 TikTok"),
}
MEDIA_NAMES = {
    "netflix": "Netflix", "primevideo": "Prime Video", "spotify": "Spotify",
    "twitch": "Twitch", "bbc": "BBC", "bilibili_intl": "Bilibili 海外版",
}


def rank_ai(rows: list[dict]) -> list[str]:
    """覆盖→信誉→稳定会话→性能；成本与来源类型不进入 AI 排序。"""
    ordered = sorted((row for row in rows if row.get('eligible')), key=lambda row: (
        -int(row.get('coverage', 0)), -int(row.get('reputation', 0)),
        -int(row.get('stability', 0)), int(row.get('latency_ms', 10**9)),
        str(row.get('node_uid'))))
    return [row['node_uid'] for row in ordered]


def _proof_valid(proof: dict, country: str, scope_sha: str, now) -> bool:
    try:
        return (proof.get('country') == country and proof.get('scope_sha') == scope_sha and
                proof.get('complete') is True and proof.get('state') == 'all_failed' and
                proof.get('valid_until') > now.isoformat())
    except TypeError:
        return False


def select_google_tier(rows: list[dict], exhaustion: list[dict], *, evaluation_at) -> dict:
    """任一合格美国可用就用美国；unknown/限流不能证明整档耗尽。"""
    scope_sha = next((row.get('scope_sha') for row in rows if row.get('scope_sha')), 'google-scope')
    for index, country in enumerate(GOOGLE_TIERS):
        candidates = [row for row in rows if row.get('country') == country and
                      row.get('google_state') == 'observed-ok']
        if candidates:
            ordered = sorted(candidates, key=lambda row: (
                not (country == 'US' and row.get('origin_kind') == 'local'),
                int(row.get('latency_ms', 10**9)), str(row['node_uid'])))
            return {'tier': country, 'candidate_uids': [row['node_uid'] for row in ordered],
                    'state': 'usable', 'reason': f'{country}_available'}
        if not any(_proof_valid(proof, country, scope_sha, evaluation_at)
                   for proof in exhaustion):
            break
    if all(any(_proof_valid(proof, country, scope_sha, evaluation_at) for proof in exhaustion)
           for country in GOOGLE_TIERS):
        return {'tier': None, 'candidate_uids': [], 'state': 'all_failed',
                'reason': 'google_all_tiers_exhausted'}
    return {'tier': None, 'candidate_uids': [], 'state': 'needs_review',
            'reason': 'higher_tier_not_exhausted'}


# 名称也是客户端可用的匹配契约。只有具备正向能力证据的平台可进入此表。
SERVICE_ALIAS_NAMES = {
    "claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini",
    "perplexity": "Perplexity", "grok": "Grok", "copilot": "Copilot",
    **MEDIA_NAMES, "tiktok": "TikTok", "youtube_premium": "YouTube Premium",
    "disney": "Disney+", "hbo": "HBO Max",
}


def verified_service_ids(row: dict, *, earliest: int, latest: int) -> list[str]:
    checked = row.get("checked_at")
    if not row.get("qualified") or type(checked) is not int or not earliest <= checked <= latest:
        return []
    return [pid for pid in SERVICE_ALIAS_NAMES if _positive_result(row, pid)]


def _positive_result(row: dict, pid: str) -> bool:
    result = (row.get("probes") or {}).get(pid) or {}
    extra = result.get("extra") or {}
    status = result.get("status")
    if (result.get("state") != "unlocked" or type(status) is not int or not 200 <= status < 300
            or extra.get("reason") in {"challenge", "rate_limit", "unexplained_denial",
                                       "ip_block", "region", "upstream", "page_response"}):
        return False
    return pid != "netflix" or (extra.get("catalog") == "licensed_sample" and bool(result.get("region")))


def service_candidates(rows: list[dict], service: str, *, earliest: int,
                       latest: int | None = None, netflix_region: str = "JP") -> list[dict]:
    """候选与别名共用同一套正向判定。Netflix 选路要求确认日本片库。"""
    if service not in SERVICE_ALIAS_NAMES:
        return []
    candidates = []
    for row in rows:
        checked = row.get("checked_at")
        if (not row.get("qualified") or type(checked) is not int or checked < earliest
                or (latest is not None and checked > latest) or not _positive_result(row, service)):
            continue
        result = row["probes"][service]
        if service == "netflix" and result.get("region") != netflix_region:
            continue
        preferred = (service in AI_SERVICES and row.get("origin_kind") == "local"
                     and row.get("country") in ("US", "JP"))
        candidates.append((not preferred, result.get("latency_ms") or row.get("delay_ms") or 10**9, row))
    return [row for _, _, row in sorted(candidates, key=lambda item: (
        item[0], item[1], item[2].get("name", "")))]


def recovery_plan(snapshot: dict, *, evaluation_at) -> dict:
    """只返回建议；执行器必须 CAS、读回并记录回执。"""
    expected_revision = int(snapshot.get('current', {}).get('selection_revision', 0))
    current_ref = snapshot.get('current', {}).get('selected_ref')
    result = {
        'action': 'keep', 'reason': 'current_healthy',
        'expected_selection_revision': expected_revision,
        'expected_selected_ref': current_ref, 'proposed_ref': None,
        'scope_sha': snapshot.get('scope_sha', ''), 'evidence_refs': [],
        'expires_at': (evaluation_at + timedelta(minutes=30)).isoformat(),
    }
    if snapshot.get('manual_locks'):
        result.update(action='wait', reason='manual_lock')
        return result
    if snapshot.get('core_health') not in (None, 'healthy'):
        result.update(action='measurement_degraded', reason='control_or_core_degraded')
        return result
    if not snapshot.get('health', {}).get('confirmed_failure'):
        return result
    if snapshot.get('all_applicable_failed'):
        # 普通业务等待有界恢复；这里绝不携带 DNS/routes/DIRECT 变更。
        result.update(action='wait', reason='all_applicable_failed',
                      evidence_refs=['all_applicable_failed'])
        return result
    candidates = [ref for ref in snapshot.get('ordered_candidates', []) if ref != current_ref]
    if not candidates:
        result.update(action='probe_standby', reason='no_qualified_alternative')
        return result
    # 同档首备合格即停止；后续候选只保留为审计用途。
    proposed = candidates[0]
    result.update(action='switch', reason='confirmed_current_failure',
                  proposed_ref=proposed,
                  evidence_refs=[digest({'current': current_ref, 'proposed': proposed,
                                         'scope': snapshot.get('scope_sha')})])
    return result


def plan(snapshot: dict, *, evaluation_at) -> dict:
    """构建计划摘要；输入不含节点私密材料。"""
    nodes = snapshot.get('nodes', [])
    eligibility = snapshot.get('eligibility', {})
    candidates = rank_ai([{**node, **next((row for row in eligibility.get('eligible', [])
                                            if row['node_uid'] == node['node_uid']), {})}
                          for node in nodes])
    scope = {'variant_id': snapshot.get('variant_id'), 'target_id': snapshot.get('target_id'),
             'device_id': snapshot.get('device_id'), 'profile': snapshot.get('profile'),
             'node_keys': [{'node_uid': node['node_uid'], 'revision': node['revision']}
                           for node in nodes]}
    return {'plan_sha': digest({'scope': scope, 'candidates': candidates,
                                'evaluation_at': evaluation_at.isoformat()}),
            'eligibility_sha': eligibility.get('eligibility_sha', digest(eligibility)),
            'scope': scope, 'candidates': candidates, 'reasons': [],
            'excluded': [], 'coverage': {}, 'blockers': [],
            'expected_revisions': {node['node_uid']: node['revision'] for node in nodes}}
