"""普通管理读取的安全投影；原文仅由显式 reveal 入口返回。"""
from .. import config, security


def url_summary(value: str) -> str:
    try:
        return security.mask_url(value or "")
    except ValueError:
        return "已配置地址（原文需授权查看）" if value else ""


def error_summary(value: str) -> str:
    return "抓取失败，详情需授权查看" if value else ""


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
