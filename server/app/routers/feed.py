"""设备配置分发。

令牌即凭据：任何持有完整订阅地址的人都可下载配置，撤销只影响后续下载。
HTTP 200 只代表下载成功，不代表客户端已加载或策略已生效。
"""
from fastapi import APIRouter, Request
from fastapi.responses import Response

import json
import urllib.parse

from .. import db, security
from ..compiler import render
from ..services import tester
from .builds import artifact_path

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
             record=None) -> Response:
    headers = dict(YAML_HEADERS)
    quoted = f'"{etag}"'
    headers["ETag"] = quoted
    if extra:
        headers.update(extra)
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    if_none = request.headers.get("if-none-match", "")
    candidates = [t.strip() for t in if_none.split(",") if t.strip()]
    if quoted in candidates or etag in candidates or "*" in candidates:
        return Response(status_code=304, headers=headers)
    if record:
        record()
    return Response(
        text, media_type="text/yaml; charset=utf-8", headers=headers,
    )


def _device_build(conn, device):
    pointer = db.one(
        conn, "SELECT build_id FROM pointers WHERE channel=?", (device["channel"],)
    )
    if not pointer or not pointer["build_id"]:
        return None, None
    build = db.one(conn, "SELECT * FROM builds WHERE id=?", (pointer["build_id"],))
    target = db.one(conn, "SELECT * FROM targets WHERE id=?", (device["target_id"],))
    return build, target


@router.api_route("/{token}/config.yaml", methods=["GET", "HEAD"])
def device_config(token: str, request: Request):
    with db.tx() as conn:
        device = _resolve_device(conn, token)
        if not device:
            return Response("not found", status_code=404)
        build, target = _device_build(conn, device)
        if not build or not target:
            return Response("no release", status_code=503)
        path = artifact_path(build["id"], target["name"])
        if not path.exists():
            return Response("artifact missing", status_code=503)
        feed_base = f"{_base_url(request, conn)}/feed/{token}"
        raw = path.read_text(encoding="utf-8")
        # 设备级个性化：叠加在该设备目标产物之上（结构键受保护）
        overlay = (device["extra_yaml"] or "").strip()
        if overlay:
            try:
                raw = render.apply_device_overlay(raw, overlay)
            except ValueError as exc:
                return Response(str(exc), status_code=500)
        text = render.substitute_feed(raw, feed_base)
        subscribe_url = f"{feed_base}/config.yaml"
        # Stash 保存订阅时会自己补一行 #SUBSCRIBED，服务端再补一行就会重复；
        # 浏览器下载（门户「下载配置」）仍需要这行，导入后客户端才知道从哪更新。
        agent = (request.headers.get("user-agent") or "").lower()
        if "stash" not in agent:
            text = f"#SUBSCRIBED {subscribe_url}\n" + text
        etag = security.sha256_text(
            f"{build['id']}:{target['name']}:{token[:10]}:"
            f"{security.sha256_text(overlay or '')[:16]}")[:32]
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

        def record():
            conn.execute(
                "UPDATE devices SET last_pull_at=?, last_pull_ip=?, "
                "pull_count=pull_count+1 WHERE id=?",
                (db.now(), request.client.host if request.client else "", device["id"]),
            )
            security.audit(conn, device["note"] or device["name"],
                           "设备下载完整配置", "device", device["id"],
                           {"build_id": build["id"], "filename": device["name"]})

        return _respond(request, text, etag, extra, record=record)


@router.api_route("/{token}/res/provider/{name}", methods=["GET", "HEAD"])
def provider_resource(token: str, name: str, request: Request):
    with db.tx() as conn:
        device = _resolve_device(conn, token)
        if not device:
            return Response("not found", status_code=404)
        source = db.one(conn, "SELECT * FROM sources WHERE name=?", (name,))
        if not source or not source["enabled"] or not source["snapshot_enc"]:
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
            conn.execute(
                "UPDATE devices SET last_pull_at=?, last_pull_ip=? WHERE id=?",
                (db.now(), request.client.host if request.client else "", device["id"]),
            )

        return _respond(request, text, etag, record=record)


@router.api_route("/{token}/res/rule/{name}", methods=["GET", "HEAD"])
def rule_resource(token: str, name: str, request: Request):
    with db.tx() as conn:
        device = _resolve_device(conn, token)
        if not device:
            return Response("not found", status_code=404)
        rp = db.one(conn, "SELECT * FROM rule_providers WHERE name=?", (name,))
        if not rp or not rp["enabled"] or not rp["content"]:
            return Response("not found", status_code=404)
        etag = (rp["sha256"] or security.sha256_text(rp["content"]))[:32]

        def record():
            conn.execute(
                "UPDATE devices SET last_pull_at=?, last_pull_ip=? WHERE id=?",
                (db.now(), request.client.host if request.client else "", device["id"]),
            )

        return _respond(request, rp["content"], etag, record=record)
