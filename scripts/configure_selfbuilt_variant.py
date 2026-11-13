#!/usr/bin/env python3
"""配置「自建美日」分流方案：精简策略组 + 改写规则指向，可重复执行。

终态结构（2026-11-13 向阳定稿：只有日美两类节点，客户端组列表要简化）：

  可见组（一般设备只有前三个）：
    🚀 默认代理  select  [🇯🇵日本, 🇺🇸美国]        —— 入口组，MATCH 与兜底代理指向它
    🇯🇵日本      select  [🇯🇵 日本自动, +日本节点]  —— 低延迟/日本区服务
    🇺🇸美国      select  [🇺🇸 美国自动, +美国节点]  —— AI/谷歌/风控类服务
    🏠 路由回家  select  （仅 LVSP 设备可见，不动）
  隐藏组：
    🇯🇵 日本自动 / 🇺🇸 美国自动  url-test 自动测速（约束 11/13/14：内层自动 + 外层可见）

其余组（自建优先、谷歌服务、人工智能、开发工具、海外游戏、国际影音、TikTok、
即时通讯、海外社交、苹果服务、微软服务、跨境电商、加密货币、自动测速、
日本机房、美国机房、美国NTT落地、港台韩新欧及其自动组）全部删除；
指向它们的规则改指向 🇯🇵日本 / 🇺🇸美国 / DIRECT。

用法（通过管理 API，有校验有审计）：

    python scripts/configure_selfbuilt_variant.py \
        --base https://magichub.top:8443 --username agent --password ***
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

VARIANT_NAME = "自建美日"

# 全部要删除的组（精简 + 原区域锁组）。删除前先改写规则指向与组成员引用。
DELETE_GROUPS = [
    # 区域锁组（第一版就删）
    "🇹🇼台湾", "🇹🇼 台湾自动", "🇰🇷韩国", "🇰🇷 韩国自动",
    "🇸🇬 新加坡", "🇸🇬 新加坡自动", "🇭🇰香港", "🇭🇰 香港自动",
    "🌍欧洲", "🌍 欧洲自动",
    # 精简：服务分组并入 日本 / 美国 / DIRECT
    "🏢 自建优先", "🔍 谷歌服务", "🧠 人工智能", "💻 开发工具",
    "🎮 海外游戏", "🎞️ 国际影音", "🎵 TikTok", "💬 即时通讯",
    "👥 海外社交", "🍎 苹果服务", "Ⓜ️ 微软服务", "🛒 跨境电商",
    "🪙 加密货币", "⚡️ 自动测速",
    "🇯🇵 日本机房", "🇺🇸 美国机房", "🇺🇸 美国NTT落地",
]

# 保留组的成员精编（proxies / local_nodes / filter 整体写入）
LOCAL_FIRST_JP = ["🇯🇵 日本机房 01", "🇯🇵 日本机房 02", "🇯🇵 AWS日本机房"]
LOCAL_REST_US = ["🇺🇸 美国机房 01", "🇺🇸 美国机房 02"] \
    + [f"🇺🇸 美国NTT {i:02d}" for i in range(1, 11)]
JP_IDS, US_IDS = [], []


def jp_us_ids() -> list[int]:
    return JP_IDS + US_IDS


GROUP_UPDATES: dict[str, dict] = {
    # 入口组：只有日本 / 美国两个策略，客户端里一眼能懂
    "🚀 默认代理": {"proxies": ["🇯🇵日本", "🇺🇸美国"], "local_nodes": [],
                    "filter": "", "use_sources": []},
    # 地区两层：可见 select 包住隐藏 url-test（约束 11/14），节点池全自建
    "🇯🇵日本": {"proxies": ["🇯🇵 日本自动"], "local_nodes": lambda: JP_IDS,
                "filter": "", "use_sources": []},
    "🇺🇸美国": {"proxies": ["🇺🇸 美国自动"], "local_nodes": lambda: US_IDS,
                "filter": "", "use_sources": []},
    "🇯🇵 日本自动": {"local_nodes": lambda: JP_IDS, "filter": "", "use_sources": []},
    "🇺🇸 美国自动": {"local_nodes": lambda: US_IDS, "filter": "", "use_sources": []},
    # 🏠 路由回家不动：LVSP 设备专属（组与规则都带设备作用域）
}

# 规则改指向：被删组的服务按「美国 / 日本 / 直连」三向归位（向阳定稿原则：
# AI、谷歌等选美国；要低延迟的选日本；国内可达的直连）
RULE_RETARGET = {
    # 谷歌系 → 美国
    "search": "🇺🇸美国", "youtube": "🇺🇸美国", "google": "🇺🇸美国",
    "magic-google": "🇺🇸美国",
    # AI → 美国
    "apple-intelligence": "🇺🇸美国", "openai": "🇺🇸美国",
    "anthropic": "🇺🇸美国", "category-ai-chat-!cn": "🇺🇸美国",
    "magic-us": "🇺🇸美国",
    # 开发工具 → 美国（GitHub / Docker / npm 等服务主力在美国）
    "github": "🇺🇸美国", "docker": "🇺🇸美国", "npmjs": "🇺🇸美国",
    "jetbrains": "🇺🇸美国", "stackexchange": "🇺🇸美国",
    # 游戏 → 日本（低延迟优先）
    "games": "🇯🇵日本", "magic-game": "🇯🇵日本",
    # 国际影音 → 日本（低延迟；DMM/Pixiv 等 Japan 原本就是日本）
    "Twitch": "🇯🇵日本", "LastFM": "🇯🇵日本", "Qobuz": "🇯🇵日本",
    "PrimeVideo": "🇯🇵日本", "Emby": "🇯🇵日本", "netflix": "🇯🇵日本",
    "disney": "🇯🇵日本", "spotify": "🇯🇵日本", "media": "🇯🇵日本",
    "biliintl": "🇯🇵日本",
    # TikTok → 日本（低延迟）
    "tiktok": "🇯🇵日本",
    # 即时通讯 → 美国（Telegram/Discord 等基础设施在美国/欧洲）
    "telegram": "🇺🇸美国", "telegram-ip": "🇺🇸美国", "Discord": "🇺🇸美国",
    "Slack": "🇺🇸美国", "Snap": "🇺🇸美国", "Whatsapp": "🇺🇸美国",
    "KakaoTalk": "🇺🇸美国", "Line": "🇺🇸美国", "Zalo": "🇺🇸美国",
    "category-communication": "🇺🇸美国", "magic-chat": "🇺🇸美国",
    # 海外社交 → 美国（Reddit/X 等主力在美国）
    "Pinterest": "🇺🇸美国", "Reddit": "🇺🇸美国", "social-extra": "🇺🇸美国",
    "social": "🇺🇸美国", "magic-social": "🇺🇸美国",
    # 苹果国内可达 → 直连（apple-cn 已在前置直连）
    "apple": "DIRECT",
    # 微软国际服务 → 美国
    "microsoft": "🇺🇸美国", "onedrive": "🇺🇸美国", "magic-microsoft": "🇺🇸美国",
    # 跨境电商 / 加密货币：账号风控，固定美国出口
    "Amazon": "🇺🇸美国", "eBay": "🇺🇸美国", "Shopify": "🇺🇸美国",
    "payment-finance": "🇺🇸美国", "PayPal": "🇺🇸美国",
    "Cryptocurrency": "🇺🇸美国",
}

EXPECTED_GROUPS = 6
EXPECTED_RULES = 114


class Api:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/")
        self.csrf = ""
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(),
        )
        data = json.dumps({"username": username, "password": password}).encode()
        resp = self._raw("POST", "/api/v1/auth/login", data, csrf=False)
        self.csrf = json.loads(resp)["csrf_token"]

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

    def post(self, path: str, body: dict):
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

    # 0. 节点 id 按名称解析
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
            "note": "只有自建节点（日美）：客户端只有 默认代理/日本/美国 三个组，"
                    "分流按 AI/谷歌→美国、低延迟→日本、国内可达→直连",
            "copy_from": 0,
            "use_sources_empty": True,
        })
        print(f"已创建方案 #{variant['id']}")
    vid = variant["id"]
    print(f"方案：{VARIANT_NAME} #{vid}")

    groups = {g["name"]: g for g in api.get(f"/api/v1/groups?variant={vid}")}
    rules = api.get(f"/api/v1/rules?variant={vid}")

    # 2. 更新保留组的成员（幂等：整体写入）
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

    # 3. 规则改指向（被删组的服务三向归位）
    retargeted = 0
    for r in rules:
        new_target = RULE_RETARGET.get(r["value"]) if r["type"] == "RULE-SET" else None
        if not new_target or r["target"] == new_target:
            continue
        api.put(f"/api/v1/rules/{r['id']}", {
            "variant_id": vid, "type": r["type"], "value": r["value"],
            "target": new_target, "enabled": r["enabled"], "note": r["note"],
            "no_resolve": r["no_resolve"], "no_track": r["no_track"],
            "pre_matching": r["pre_matching"], "targets": r["targets"],
            "devices": r["devices"],
        })
        retargeted += 1
        print(f"  已改指向：RULE-SET,{r['value']}  {r['target']} → {new_target}")
    print(f"  共改写 {retargeted} 条规则指向")

    # 4. 删除被精简的组（规则与组成员引用已先行改写，force 兜底解绑）
    groups = {g["name"]: g for g in api.get(f"/api/v1/groups?variant={vid}")}
    for name in DELETE_GROUPS:
        g = groups.get(name)
        if g is None:
            continue
        api.delete(f"/api/v1/groups/{g['id']}?force=1")
        print(f"  已删除组：{name}")

    # 5. 终态校验
    groups = api.get(f"/api/v1/groups?variant={vid}")
    rules = api.get(f"/api/v1/rules?variant={vid}")
    print(f"终态：{len(groups)} 个组、{len(rules)} 条规则")
    problems = []
    if len(groups) != EXPECTED_GROUPS:
        problems.append(f"组数应为 {EXPECTED_GROUPS}，实际 {len(groups)}")
    if len(rules) != EXPECTED_RULES:
        problems.append(f"规则数应为 {EXPECTED_RULES}，实际 {len(rules)}")
    names = {g["name"] for g in groups}
    for g in groups:
        for member in g["proxies"]:
            if member not in names and member not in (
                    "DIRECT", "REJECT", "REJECT-DROP", "PASS", "GLOBAL"):
                problems.append(f"组「{g['name']}」成员引用不存在：{member}")
        for src in g["use_sources"]:
            if src != "*":
                problems.append(f"组「{g['name']}」仍引用节点来源：{src}")
    # 规则指向必须落在本方案的组或内置字面量上
    for r in rules:
        if r["target"] not in names and r["target"] not in (
                "DIRECT", "REJECT", "REJECT-DROP"):
            problems.append(
                f"规则 RULE-SET,{r['value']} 指向已删除的组：{r['target']}")
    if problems:
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1
    print("✓ 自建美日方案精简配置完成（默认代理/日本/美国 + 路由回家 + 两个隐藏自动组）")
    if args.build:
        build = api.post("/api/v1/builds", {"note": "自建美日方案精简后构建"})
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
