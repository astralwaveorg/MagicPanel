"""设备独立配置分发。

令牌即凭据：任何持有完整订阅地址的人都可下载配置，撤销只影响后续下载。
HTTP 200 只代表下载成功，不代表客户端已加载或策略已生效。
"""
from fastapi import APIRouter, Request
from fastapi.responses import Response

import base64
import json
import urllib.parse

from .. import config, db, security
from ..services import base_config as base_config_service
from ..compiler import render, validate
from ..services import tester
from .builds import artifact_file

router = APIRouter(prefix="/feed", tags=["feed"])

YAML_HEADERS = {
    "Cache-Control": "private, no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _resolve_device(conn, token: str):
    if not token or len(token) < 20:
        return None
    return db.one(
        conn, "SELECT * FROM devices WHERE token_hash=?",
        (security.sha256_text(token),),
    )


def _base_url(request: Request, conn) -> str:
    base = db.get_setting(conn, "base_url", "").rstrip("/")
    return base or str(request.base_url).rstrip("/")


def _respond(request: Request, text: str, etag: str, extra: dict | None = None,
             record=None, data: bytes | None = None,
             allow_304: bool = True) -> Response:
    headers = dict(YAML_HEADERS)
    quoted = f'"{etag}"'
    headers["ETag"] = quoted
    if extra:
        headers.update(extra)
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    if allow_304:
        if_none = request.headers.get("if-none-match", "")
        candidates = [t.strip() for t in if_none.split(",") if t.strip()]
        if quoted in candidates or etag in candidates or "*" in candidates:
            return Response(status_code=304, headers=headers)
    if record:
        record()
    if data is not None:
        # 二进制内容（MRS 规则集）：按原始字节下发
        return Response(data, media_type="application/octet-stream", headers=headers)
    return Response(
        text, media_type="text/yaml; charset=utf-8", headers=headers,
    )


def _device_overlay(conn, device) -> str:
    """取该设备的独立配置（设备作用域），没有则为空。"""
    target = db.one(conn, "SELECT engine, platform FROM targets WHERE id=?",
                    (device["target_id"],))
    if not target:
        return ""
    row = db.one(conn, "SELECT content FROM base_configs "
                       "WHERE engine=? AND platform=? AND device_id=? LIMIT 1",
                 (target["engine"], target["platform"], device["id"]))
    if not row:
        return ""
    try:
        doc = base_config_service.parse_content(row["content"])
    except ValueError:
        return ""
    return base_config_service.to_yaml(doc)


def _device_build(conn, device):
    """取该设备所在环境当前生效的构建。

    设备订阅环境（production / testing）直接对应构建的生命周期状态：
    生效版本由 builds.status 唯一确定。
    """
    status = ("PRODUCTION" if device["env"] == "production" else "TESTING")
    build = db.one(conn, "SELECT * FROM builds WHERE status=? LIMIT 1", (status,))
    target = db.one(conn, "SELECT * FROM targets WHERE id=?", (device["target_id"],))
    return build, target


@router.api_route("/{token}/config.yaml", methods=["GET", "HEAD"])
def device_config(token: str, request: Request, preview: bool = False,
                  variant: str = ""):
    # 预览模式（?preview=1）：给门户的「看配置源码」用。
    # 与正常下发**内容一致**，但三件事不同：
    #   1. 不记拉取——预览是人在看，不是客户端在更新，不能污染「配置时效」；
    #   2. 不加 #SUBSCRIBED——那是给客户端的更新提示行，不是配置内容；
    #   3. Content-Disposition 用 inline——新标签页打开时直接显示文本，
    #      而不是触发下载。
    # ?variant=<方案名>：选择分流方案。方案产物是同一构建里的另一份文件
    # （{device}@方案.yaml / {target}@方案.yaml），下发逻辑与默认方案完全一致。
    # 不带参数 = 默认方案 = 历史路径，老订阅链接不受任何影响。
    # read 用只读连接：设备拉取是高频请求，不能每次都抢 SQLite 的写锁
    with db.connect() as conn:
        device = _resolve_device(conn, token)
        if not device:
            return Response("not found", status_code=404)
        build, target = _device_build(conn, device)
        if not build or not target:
            return Response("no release", status_code=503)
        # 设备有专属策略组 / 规则时，构建会单独产出一份设备专属产物；
        # 没有就用该引擎平台的共享产物。方案产物同理：先找设备专属的，
        # 没有再找引擎平台的共享方案产物。
        artifact = device["name"]
        if variant:
            row = db.one(conn, "SELECT name FROM variants WHERE name=?", (variant,))
            if not row:
                return Response(f"variant not found: {variant}", status_code=404)
            artifact += f"@{row['name']}"
        path = artifact_file(build["id"], artifact)
        if not path.exists() and variant:
            path = artifact_file(build["id"], f"{target['name']}@{row['name']}")
        if not path.exists():
            if not variant:
                path = artifact_file(build["id"], target["name"])
            if not path.exists():
                if variant:
                    return Response(
                        f"当前版本没有方案“{variant}”的产物，请先在后台构建发布",
                        status_code=404)
                return Response("artifact missing", status_code=503)
        feed_base = f"{_base_url(request, conn)}/feed/{token}"
        raw = path.read_text(encoding="utf-8")
        # 设备专属配置：叠加在该设备目标产物之上（结构键受保护）
        overlay = _device_overlay(conn, device)
        if overlay:
            try:
                raw = render.apply_device_overlay(raw, overlay)
            except ValueError as exc:
                return Response(str(exc), status_code=500)
            # 设备覆盖从未参与构建期校验：下发前再校验一次，
            # 坏配置不能因为"只影响一台设备"就悄悄下发。
            problems = validate.validate_rendered(raw, target["engine"])
            if problems:
                return Response(
                    "设备独立配置导致产物校验失败：" + "；".join(problems),
                    status_code=500,
                )
        text = render.substitute_feed(raw, feed_base)
        subscribe_url = f"{feed_base}/config.yaml"
        # Stash 保存订阅时会自己补一行 #SUBSCRIBED，服务端再补一行就会重复；
        # 浏览器下载（门户「下载配置」）仍需要这行，导入后客户端才知道从哪更新。
        agent = (request.headers.get("user-agent") or "").lower()
        if not preview and "stash" not in agent:
            text = f"#SUBSCRIBED {subscribe_url}\n" + text
        # ETag 必须覆盖最终正文：正文会随 base_url、User-Agent、
        # 设备覆盖变化，只用 build_id 会让客户端拿到 304 却仍是旧内容。
        etag = security.sha256_text(text)[:32]
        interval = db.get_setting(conn, "profile_update_interval", "12")
        # Content-Disposition 仅允许 ASCII；中文名经 RFC 5987 编码
        ascii_name = device["name"].encode("ascii", "ignore").decode() or "config"
        quoted_name = urllib.parse.quote(device["name"])
        extra = {
            "profile-update-interval": interval,
            "Content-Disposition":
                f"attachment; filename=\"{ascii_name}.yaml\"; "
                f"filename*=UTF-8''{quoted_name}.yaml",
        }
        if preview:
            extra["Content-Disposition"] = f'inline; filename="{ascii_name}.yaml"'
            # 预览不进浏览器缓存：缓存的 ETag 会让第二次预览拿到 304 空响应。
            extra["Cache-Control"] = "no-store"

        def record():
            # 计数与审计放在独立短事务里，避免长时间占着写锁
            with db.tx() as wconn:
                wconn.execute(
                    "UPDATE devices SET last_pull_at=?, last_pull_ip=?, "
                    "last_config_at=?, pull_count=pull_count+1 WHERE id=?",
                    (db.now(), request.client.host if request.client else "",
                     db.now(), device["id"]),
                )

        if preview:
            # 不记拉取；也不做 304 协商（预览正文与客户端下发正文不同）
            return _respond(request, text, etag, extra, allow_304=False)
        return _respond(request, text, etag, extra, record=record)


@router.api_route("/{token}/res/provider/{name}", methods=["GET", "HEAD"])
def provider_resource(token: str, name: str, request: Request):
    with db.connect() as conn:
        device = _resolve_device(conn, token)
        if not device:
            return Response("not found", status_code=404)
        source = db.one(conn, "SELECT * FROM sources WHERE name=?", (name,))
        # 停用不等于删除：快照还在就继续下发。产物不可变、只移动指针，
        # 客户端手上的配置可能仍写着这个来源的下发地址，此时回 404 会让
        # 客户端反复重试，并把整个订阅更新判为失败（Stash 会一直刷
        # "artifact refresh failed ... HTTP 404"，配置再也更新不进来）。
        if not source or not source["snapshot_enc"]:
            return Response("not found", status_code=404)
        text = security.decrypt_text(source["snapshot_enc"])
        # 开启过滤时只分发测试通过的节点；失败节点对设备不可见
        if source["filter_unavailable"]:
            results = json.loads(source["test_results"] or "{}")
            failed = {k for k, v in results.items() if v < 0}
            if failed:
                try:
                    text = tester.filter_snapshot(text, failed)
                except tester.TestError:
                    pass  # 快照异常时回退为完整内容，不阻断分发
        etag_src = (source["sha256"] or "") + (
            ":filtered" if source["filter_unavailable"] else "")
        if source["filter_unavailable"]:
            # 过滤结果随测速变化，ETag 必须跟着变，否则客户端拿不到新的节点列表
            etag_src += ":" + security.sha256_text(
                source["test_results"] or "{}")[:16]
        etag = security.sha256_text(etag_src or text)[:32]

        def record():
            with db.tx() as wconn:
                wconn.execute(
                    "UPDATE devices SET last_pull_at=?, last_pull_ip=? WHERE id=?",
                    (db.now(), request.client.host if request.client else "", device["id"]),
                )

        return _respond(request, text, etag, record=record)


@router.api_route("/{token}/res/rule/{name}", methods=["GET", "HEAD"])
def rule_resource(token: str, name: str, request: Request):
    with db.connect() as conn:
        device = _resolve_device(conn, token)
        if not device:
            return Response("not found", status_code=404)
        rp = db.one(conn, "SELECT * FROM rule_providers WHERE name=?", (name,))
        # 停用不等于删除：内容还在就继续下发（原因同上）。
        if not rp or not rp["content"]:
            return Response("not found", status_code=404)
        etag = (rp["sha256"] or security.sha256_text(rp["content"]))[:32]

        def record():
            conn.execute(
                "UPDATE devices SET last_pull_at=?, last_pull_ip=? WHERE id=?",
                (db.now(), request.client.host if request.client else "", device["id"]),
            )

        if (rp["format"] or "yaml") in config.BINARY_FORMATS:
            # MRS：库里存的是 base64，下发时还原成原始字节
            try:
                data = base64.b64decode(rp["content"])
            except (ValueError, TypeError):
                data = rp["content"].encode()
            return _respond(request, "", etag, record=record, data=data)
        return _respond(request, rp["content"], etag, record=record)
