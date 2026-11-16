"""普通管理读取的安全投影；原文仅由显式 reveal 入口返回。"""
import re

from .. import config, security


# 已知错误码 → 人话说明。这里只放结论，不放原文：
# 抓取异常里可能带订阅地址（含凭据），一律不回显。
ERROR_HINTS = {
    'mrs_magic_invalid': '规则集格式无效：.mrs 文件头不是合法的压缩帧',
    'mrs_behavior_invalid': '规则集行为类型与格式不匹配',
    'rule_body_invalid': '规则集内容为空或超出大小限制',
    'rule_format_invalid': '规则集格式不受支持',
    'yaml_parse_invalid': '规则集 YAML 解析失败',
    'yaml_structure_invalid': '规则集结构不符合要求',
    'html_rejected': '上游返回的是网页，不是规则集',
    'unsupported_scheme': '地址协议不受支持，只支持 http/https',
    'host_missing': '地址缺少主机名',
    'dns_failure': '域名解析失败',
    'redirect_loop': '重定向次数过多',
    'empty_body': '上游返回内容为空',
    'timeout': '连接超时',
    'tls_error': 'TLS 握手或证书校验失败',
    'core_unavailable': 'Mihomo 核心不可用',
}

_HTTP_RE = re.compile(r'HTTP (\d{3})')


def describe_error(value: str) -> str:
    """把内部错误翻译成能看懂的原因；不回显可能含凭据的原文。"""
    text = (value or '').strip()
    if not text:
        return ''
    tail = text.split('：')[-1].split(':')[-1].strip()
    if tail in ERROR_HINTS:
        return ERROR_HINTS[tail]
    for code, hint in ERROR_HINTS.items():
        if code in text:
            return hint
    match = _HTTP_RE.search(text)
    if match:
        return f'上游返回 HTTP {match.group(1)}'
    lowered = text.lower()
    if 'timeout' in lowered or 'timed out' in lowered or '超时' in text:
        return '连接超时'
    if 'certificate' in lowered or '证书' in text or 'ssl' in lowered:
        return 'TLS 握手或证书校验失败'
    if 'connection refused' in lowered:
        return '连接被拒绝'
    if 'connection reset' in lowered or 'reset by peer' in lowered:
        return '连接被重置'
    if '解析失败' in text or 'not known' in lowered or 'name resolution' in lowered:
        return '域名解析失败'
    if '重定向' in text:
        return '重定向次数过多'
    if '内容为空' in text:
        return '上游返回内容为空'
    if '不支持的协议' in text:
        return '地址协议不受支持，只支持 http/https'
    return '抓取失败，具体原因见审计日志'


def url_summary(value: str) -> str:
    try:
        return security.mask_url(value or "")
    except ValueError:
        return "已配置地址（原文需授权查看）" if value else ""


def error_summary(value: str) -> str:
    # 没有错误就是没有错误：空值必须原样返回空串。
    # 早先这里对空值兜底成「抓取失败」，于是每次抓取成功的规则来源
    # 在接口里都带着一句「抓取失败」，与 has_error=False 自相矛盾。
    text = (value or '').strip()
    if not text:
        return ''
    return describe_error(text) or "抓取失败"


def audit_public(row) -> dict:
    has_detail = bool(row["detail"])
    return {**{key: row[key] for key in ("id", "at", "actor", "action", "object_type", "object_id")},
            "detail": "", "has_detail": has_detail,
            "summary": "有详细记录，原文需授权查看" if has_detail else ""}


def rule_provider_public(row) -> dict:
    proxy = row["proxy_url_enc"] or ""
    return {
        **{key: row[key] for key in ("id", "name", "behavior", "format", "kind", "interval",
            "client_interval", "last_status", "last_fetched_at", "last_attempt_at", "repo_path",
            "sha256", "created_at", "updated_at")},
        "url": url_summary(row["url"]), "enabled": bool(row["enabled"]),
        "use_proxy": bool(proxy), "proxy_url_masked": url_summary(security.decrypt_text(proxy)) if proxy else "",
        "last_error": error_summary(row["last_error"]), "has_error": bool(row["last_error"]),
        "rule_count": None if (row["format"] or "yaml") in config.BINARY_FORMATS else row["rule_count"],
        "has_content": bool(row["content"]),
    }


def migration_public(row) -> dict:
    return {**{key: row[key] for key in ("id", "batch", "object_type", "object_id", "origin_kind",
        "origin_repo_path", "origin_behavior", "origin_enabled", "origin_content_sha", "origin_rule_count",
        "switched_at", "reverted_at")}, "origin_url": url_summary(row["origin_url"])}
