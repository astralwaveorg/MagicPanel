#!/usr/bin/env python3
"""配置「自建美日」分流方案：剔除非日美的组与规则，精编组成员与节点池。

通过管理 API 操作（有校验、有审计），可重复执行（幂等：已删的跳过，
成员列表按目标值整体写入）。用法：

    python scripts/configure_selfbuilt_variant.py \
        --base https://magichub.top:8443 --username agent --password ***

步骤：
1. 确保方案存在（不存在则从默认方案复制，use_sources_empty=True）；
2. 更新保留组的成员列表（剔除港台韩新欧成员、节点池换成日美自建节点）；
3. 删除 8 条指向被剔除组的规则；
4. 删除 10 个非日美组（含隐藏自动组）；
5. 校验终态：23 个组、114 条规则。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

VARIANT_NAME = "自建美日"

# 需要删除的非日美组（可见组 + 隐藏自动组）
DELETE_GROUPS = [
    "🇹🇼台湾", "🇹🇼 台湾自动", "🇰🇷韩国", "🇰🇷 韩国自动",
    "🇸🇬 新加坡", "🇸🇬 新加坡自动", "🇭🇰香港", "🇭🇰 香港自动",
    "🌍欧洲", "🌍 欧洲自动",
]
# 指向被剔除组的规则（RULE-SET 的集合名）
DELETE_RULE_SETS = [
    "myTVSUPER", "JOOX", "Naver", "LineTV", "KKBOX", "TVB", "BBC", "Yandex",
]

# 保留组的成员精编（proxies / local_nodes 整体写入）。
# 节点 id 在运行时按节点名解析，不写死。
LOCAL_FIRST_JP = ["🇯🇵 日本机房 01", "🇯🇵 日本机房 02", "🇯🇵 AWS日本机房"]
LOCAL_REST_US = ["🇺🇸 美国机房 01", "🇺🇸 美国机房 02"] \
    + [f"🇺🇸 美国NTT {i:02d}" for i in range(1, 11)]
JP_IDS, US_IDS = [], []          # 运行时填充


def jp_us_ids() -> list[int]:
    return JP_IDS + US_IDS


GROUP_UPDATES: dict[str, dict] = {
    "🚀 默认代理": {
        "proxies": ["🏢 自建优先", "🇺🇸 美国NTT落地", "⚡️ 自动测速",
                    "🇯🇵 日本机房", "🇺🇸 美国机房", "🇯🇵日本", "🇺🇸美国"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "🏢 自建优先": {"local_nodes": lambda: jp_us_ids()},
    "🧠 人工智能": {
        "proxies": ["🇺🇸 美国机房", "🇺🇸 美国自动", "🇯🇵 日本机房", "🇯🇵 日本自动"],
    },
    "💻 开发工具": {
        "proxies": ["🚀 默认代理", "🇺🇸 美国NTT落地", "🇯🇵日本", "🇺🇸美国"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "🎮 海外游戏": {
        "proxies": ["🏢 自建优先", "🇺🇸 美国NTT落地", "⚡️ 自动测速",
                    "🇯🇵日本", "🇺🇸美国", "🚀 默认代理"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "🎞️ 国际影音": {
        "proxies": ["🇯🇵 日本自动", "🇺🇸 美国自动"],
    },
    "🎵 TikTok": {
        "proxies": ["🇯🇵 日本机房", "🇺🇸 美国NTT落地", "🇺🇸 美国机房",
                    "🇯🇵日本", "🇺🇸美国", "🚀 默认代理"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "💬 即时通讯": {
        "proxies": ["⚡️ 自动测速", "🇺🇸 美国NTT落地", "🇯🇵日本",
                    "🇺🇸 美国自动", "🚀 默认代理"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "👥 海外社交": {
        "proxies": ["🚀 默认代理", "🇺🇸 美国NTT落地", "🇯🇵日本", "🇺🇸美国"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "🍎 苹果服务": {
        "proxies": ["DIRECT", "🇺🇸 美国NTT落地", "🇺🇸美国", "🇯🇵日本", "🚀 默认代理"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "Ⓜ️ 微软服务": {
        "proxies": ["🚀 默认代理", "🇺🇸 美国NTT落地", "DIRECT",
                    "🇯🇵日本", "🇺🇸美国"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "🛒 跨境电商": {
        "proxies": ["🇺🇸美国", "🇺🇸 美国NTT落地", "🇯🇵日本", "⚡️ 自动测速"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "🪙 加密货币": {
        "proxies": ["🇺🇸美国", "🇺🇸 美国NTT落地", "🇺🇸 美国机房",
                    "🇯🇵日本", "🇯🇵 日本机房", "🚀 默认代理"],
        "local_nodes": lambda: jp_us_ids(),
    },
    "⚡️ 自动测速": {"local_nodes": lambda: jp_us_ids()},
    # AWS日本机房（本地节点 12）此前未进任何组：并入本方案的日本节点池
    "🇯🇵 日本机房": {"local_nodes": lambda: JP_IDS},
    "🇯🇵 日本自动": {"local_nodes": lambda: JP_IDS},
}


class Api:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/")
        self.csrf = ""
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(),
        )
        data = json.dumps({"username": username, "password": password}).encode()
        resp = self._raw("POST", "/api/v1/auth/login", data, csrf=False)
        body = json.loads(resp)
        self.csrf = body["csrf_token"]

    def _raw(self, method: str, path: str, data: bytes | None = None,
             csrf: bool = True) -> bytes:
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with self.opener.open(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {detail[:500]}")

    def get(self, path: str):
        return json.loads(self._raw("GET", path))

    def post(self, path: str, body: dict, ok: tuple = (200, 201)):
        raw = self._raw("POST", path, json.dumps(body, ensure_ascii=False).encode())
        return json.loads(raw) if raw else {}

    def put(self, path: str, body: dict):
        raw = self._raw("PUT", path, json.dumps(body, ensure_ascii=False).encode())
        return json.loads(raw) if raw else {}

    def delete(self, path: str):
        return json.loads(self._raw("DELETE", path) or "{}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--build", action="store_true", help="完成后触发一次构建")
    args = parser.parse_args()

    api = Api(args.base, args.username, args.password)

    # 0. 节点 id 按名称解析（改写组时引用的是本地节点 id）
    nodes = api.get("/api/v1/local-nodes")
    by_name = {n["name"]: n["id"] for n in nodes}
    missing = [n for n in LOCAL_FIRST_JP + LOCAL_REST_US if n not in by_name]
    if missing:
        raise SystemExit(f"本地节点不存在：{missing}（请核对名称）")
    JP_IDS.extend(by_name[n] for n in LOCAL_FIRST_JP)
    US_IDS.extend(by_name[n] for n in LOCAL_REST_US)
    print(f"节点池：JP={JP_IDS} US={US_IDS}")

    # 1. 确保方案存在（从默认复制并清空来源引用）
    variant = next((v for v in api.get("/api/v1/variants")
                    if v["name"] == VARIANT_NAME), None)
    if variant is None:
        variant = api.post("/api/v1/variants", {
            "name": VARIANT_NAME,
            "note": "只有自建节点（日美），分流按 AI/谷歌→美国、低延迟→日本",
            "copy_from": 0,
            "use_sources_empty": True,
        })
        print(f"已创建方案 #{variant['id']}")
    vid = variant["id"]
    print(f"方案：{VARIANT_NAME} #{vid}")

    groups = {g["name"]: g for g in api.get(f"/api/v1/groups?variant={vid}")}
    rules = api.get(f"/api/v1/rules?variant={vid}")

    # 2. 更新保留组的成员
    for name, patch in GROUP_UPDATES.items():
        g = groups.get(name)
        if g is None:
            print(f"  跳过（组不存在）：{name}")
            continue
        body = {
            "name": g["name"], "variant_id": vid, "type": g["type"],
            "hidden": g["hidden"], "filter": g["filter"],
            "use_sources": g["use_sources"],
            "local_nodes": g["local_nodes"], "proxies": g["proxies"],
            "url": g["url"], "interval": g["interval"], "timeout": g["timeout"],
            "tolerance": g["tolerance"], "lazy": g["lazy"],
            "strategy": g["strategy"], "targets": g["targets"],
            "devices": g["devices"], "local_first": g["local_first"],
        }
        for key, value in patch.items():
            body[key] = value() if callable(value) else value
        api.put(f"/api/v1/groups/{g['id']}", body)
        print(f"  已更新组：{name}")
        groups[name] = {**g, **{k: v for k, v in body.items() if k != "variant_id"}}

    # 3. 删除指向被剔除组的规则
    for r in rules:
        if r["type"] == "RULE-SET" and r["value"] in DELETE_RULE_SETS:
            api.delete(f"/api/v1/rules/{r['id']}")
            print(f"  已删除规则：RULE-SET,{r['value']} -> {r['target']}")

    # 4. 删除非日美组（成员引用已在第 2 步清掉）
    for name in DELETE_GROUPS:
        g = groups.get(name)
        if g is None:
            continue
        api.delete(f"/api/v1/groups/{g['id']}")
        print(f"  已删除组：{name}")

    # 5. 终态校验
    groups = api.get(f"/api/v1/groups?variant={vid}")
    rules = api.get(f"/api/v1/rules?variant={vid}")
    print(f"终态：{len(groups)} 个组、{len(rules)} 条规则")
    problems = []
    if len(groups) != 23:
        problems.append(f"组数应为 23，实际 {len(groups)}")
    if len(rules) != 114:
        problems.append(f"规则数应为 114，实际 {len(rules)}")
    names = {g["name"] for g in groups}
    for g in groups:
        for member in g["proxies"]:
            if member not in names and member not in (
                    "DIRECT", "REJECT", "REJECT-DROP", "PASS", "GLOBAL"):
                problems.append(f"组「{g['name']}」成员引用不存在：{member}")
        for src in g["use_sources"]:
            if src != "*":
                problems.append(f"组「{g['name']}」仍引用节点来源：{src}")
    if problems:
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1
    print("✓ 自建美日方案配置完成")
    if args.build:
        build = api.post("/api/v1/builds", {"note": "自建美日方案配置后构建"})
        print(f"构建 #{build['id']}：{build['verify_status']}")
        bad = {k: v for k, v in (build.get("results") or {}).items() if not v["ok"]}
        if bad:
            for k, v in bad.items():
                print(f"  ✗ {k}: {v['errors'][:3]}", file=sys.stderr)
            return 1
        print("✓ 全部产物构建成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
