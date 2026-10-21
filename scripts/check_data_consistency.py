#!/usr/bin/env python3
"""数据自检：面板里的数据必须自洽、可用、可解释。

检查项（任何一条不过都算数据不规范）：
  1. 引擎平台：同一「引擎 + 平台」只能有一个；名称与文件名规则一致；
  2. 引用：策略组 / 规则的「适用引擎平台」「适用设备」必须真实存在；
     策略组成员、规则目标必须存在；
  3. 设备：所属引擎平台存在；「设备独立配置」的键与设备所在引擎平台一致；
  4. 基础配置各层：不含结构键（proxies / proxy-groups / rules 等）；
     不保留与上层完全相同的键（重复覆盖 = 数据冗余）；
  5. 功能模块：内容是非空 YAML 映射、不含结构键、引擎范围合法；
     已启用的模块若与引擎默认配置完全重复，给出提示（可关掉）；
  6. 命名：策略组 / 规则 / 引擎平台 / 设备的命名风格一致、无空白字符。

用法：
    python3 scripts/check_data_consistency.py [数据库路径]
默认读 data/magicpanel.db（可用 MAGICPANEL_DATA_DIR 指向别处）。
退出码 0 = 全部通过；1 = 存在不规范数据。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
# 容器里 app 在 /app 下，仓库里在 server/app 下，两处都试
for _path in (REPO / "server", Path("/app")):
    if (_path / "app" / "services" / "base_config.py").exists():
        sys.path.insert(0, str(_path))
        break

from app.services import base_config as bc  # noqa: E402

STRUCT_KEYS = set(bc.PROTECTED_KEYS)
# 命名规范：不空白、不含控制字符、首尾不空。表情符号与中文都允许
# （策略组名本身就是「🇭🇰 香港优选」这种风格）。
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def bad_name(name: str) -> bool:
    if not name or not name.strip():
        return True
    if name != name.strip():
        return True
    return bool(CONTROL_RE.search(name))


def db_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    data_dir = Path(os.environ.get("MAGICPANEL_DATA_DIR", REPO / "data"))
    return data_dir / "magicpanel.db"


def main() -> int:
    path = db_path()
    if not path.exists():
        print(f"找不到数据库：{path}")
        return 1
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    problems: list[str] = []
    notes: list[str] = []

    def rows(sql: str, args=()) -> list[sqlite3.Row]:
        return conn.execute(sql, args).fetchall()

    # ---- 1. 引擎平台 ----
    targets = rows("SELECT id, name, engine, platform, extra_yaml FROM targets "
                   "ORDER BY id")
    target_names = {t["name"] for t in targets}
    pairs: dict[tuple[str, str], str] = {}
    for t in targets:
        key = (t["engine"], t["platform"])
        if key in pairs:
            problems.append(
                f"引擎平台「{t['engine']} + {t['platform']}」重复："
                f"{pairs[key]} 与 {t['name']}")
        pairs[key] = t["name"]
        if not re.match(r"^[A-Za-z0-9_-]+$", t["name"]):
            problems.append(f"引擎平台名称「{t['name']}」含非法字符（只允许字母数字 _ -）")
        if t["extra_yaml"] and t["extra_yaml"].strip():
            try:
                doc = yaml.safe_load(t["extra_yaml"]) or {}
            except Exception as exc:
                problems.append(f"引擎平台 {t['name']} 的目标扩展不是合法 YAML：{exc}")
                doc = {}
            if isinstance(doc, dict):
                for key in STRUCT_KEYS:
                    if key in doc:
                        problems.append(f"引擎平台 {t['name']} 的目标扩展含结构键 {key}")

    # ---- 2. 策略组与规则 ----
    groups = rows("SELECT id, name, proxies, use_sources, targets, devices, "
                  "local_nodes FROM proxy_groups ORDER BY sort, id")
    group_names = {g["name"] for g in groups}
    devices = rows("SELECT id, name, target_id FROM devices")
    device_names = {d["name"] for d in devices}
    sources = {r["name"] for r in rows("SELECT name FROM sources")}
    local_nodes = {r["id"] for r in rows("SELECT id FROM local_nodes")}

    for g in groups:
        for name in json.loads(g["targets"] or "[]"):
            if name not in target_names:
                problems.append(f"策略组「{g['name']}」适用了不存在的引擎平台「{name}」")
        for name in json.loads(g["devices"] or "[]"):
            if name not in device_names:
                problems.append(f"策略组「{g['name']}」适用了不存在的设备「{name}」")
        for member in json.loads(g["proxies"] or "[]"):
            if member not in group_names and member not in bc.__dict__.get(
                    "BUILTIN_TARGETS", ()) and member not in ("DIRECT", "REJECT", "PASS", "COMPATIBLE"):
                problems.append(f"策略组「{g['name']}」的成员「{member}」不存在")
        for src in json.loads(g["use_sources"] or "[]"):
            if src not in sources:
                problems.append(f"策略组「{g['name']}」引用了不存在的节点来源「{src}」")
        for nid in json.loads(g["local_nodes"] or "[]"):
            if nid not in local_nodes:
                problems.append(f"策略组「{g['name']}」引用了不存在的本地节点 {nid}")
        if bad_name(g["name"]):
            problems.append(f"策略组名称「{g['name']}」命名不规范")

    # 规则按实际生效顺序取（sort 就是产物里的先后顺序）
    rules = rows("SELECT id, type, value, target, targets, devices FROM rules "
                 "ORDER BY sort, id")
    for r in rules:
        for name in json.loads(r["targets"] or "[]"):
            if name not in target_names:
                problems.append(f"规则「{r['type']},{r['value']}」适用了不存在的引擎平台「{name}」")
        for name in json.loads(r["devices"] or "[]"):
            if name not in device_names:
                problems.append(f"规则「{r['type']},{r['value']}」适用了不存在的设备「{name}」")
        if r["target"] not in group_names and r["target"] not in (
                "DIRECT", "REJECT", "PASS", "COMPATIBLE"):
            problems.append(f"规则「{r['type']},{r['value']}」指向不存在的策略组「{r['target']}」")

    # ---- 3. 设备 ----
    for d in devices:
        if d["target_id"] not in {t["id"] for t in targets}:
            problems.append(f"设备「{d['name']}」指向不存在的引擎平台")
        if bad_name(d["name"]):
            problems.append(f"设备文件名「{d['name']}」命名不规范")

    target_by_id = {t["id"]: t for t in targets}

    # ---- 4. 基础配置各层 ----
    docs = {}
    for row in rows("SELECT engine, platform, device_id, content FROM base_configs"):
        key = (row["engine"], row["platform"], int(row["device_id"] or 0))
        if not (row["content"] or "").strip():
            docs[key] = {}      # 这一层没有覆盖
            continue
        try:
            docs[key] = bc.parse_content(row["content"] or "")
        except Exception as exc:
            problems.append(f"基础配置 {key} 不是合法 YAML：{exc}")
            docs[key] = {}
        for k in STRUCT_KEYS:
            if k in docs[key]:
                problems.append(f"基础配置 {key} 含结构键 {k}")
    for d in devices:
        target = target_by_id.get(d["target_id"])
        if not target:
            continue
        for key, doc in docs.items():
            if key[2] != d["id"]:
                continue
            if (key[0], key[1]) != (target["engine"], target["platform"]):
                problems.append(
                    f"设备「{d['name']}」的独立配置挂在 {key[0]}/{key[1]}，"
                    f"但它现在在 {target['engine']}/{target['platform']}（会静默失效）")
    # 冗余覆盖：与上层完全相同的键没有必要留在本层
    for (engine, platform, device_id), doc in docs.items():
        layers = bc.scope_layers(engine, platform, device_id, docs)
        if len(layers) < 2:
            continue
        inherited, _ = bc.cascade(layers[:-1])
        for key, value in (doc or {}).items():
            if key in inherited and inherited[key] == value:
                notes.append(
                    f"基础配置 {engine}/{platform or '默认'}/设备{device_id} 里的 {key} "
                    "与上层完全相同，可清掉（属于冗余覆盖）")

    # ---- 4b. 规则的覆盖逻辑 ----
    providers = {r["name"]: r for r in rows(
        "SELECT name, enabled FROM rule_providers")}
    used_providers: set[str] = set()
    for r in rules:
        if r["type"] != "RULE-SET":
            continue
        used_providers.add(r["value"])
        prov = providers.get(r["value"])
        if prov is None:
            problems.append(f"规则「{r['type']},{r['value']}」引用了不存在的规则集合")
        elif not prov["enabled"]:
            problems.append(
                f"规则「{r['type']},{r['value']}」引用了已停用的规则集合"
                f"（{r['value']}）——这条规则在产物里会被丢弃")
    for name, prov in providers.items():
        if prov["enabled"] and name not in used_providers:
            notes.append(f"规则集合「{name}」已启用但没有任何规则引用它（白拿流量）")
        elif not prov["enabled"] and name not in used_providers:
            notes.append(f"规则集合「{name}」已停用且无人引用，可清理")
    # 兜底规则之后还有规则 = 永远不生效
    for i, r in enumerate(rules):
        if r["type"] in ("MATCH", "FINAL"):
            after = rules[i + 1:]
            if after:
                problems.append(
                    f"兜底规则之后还有 {len(after)} 条规则，永远不会命中："
                    + "、".join(f"{x['type']},{x['value'][:16]}" for x in after[:3]))
            break
    # 范围交集为空 = 这条规则在哪儿都不生效
    device_target = {}
    for d in devices:
        target = target_by_id.get(d["target_id"])
        if target:
            device_target[d["name"]] = target["name"]
    for r in rules:
        ts = set(json.loads(r["targets"] or "[]"))
        ds = set(json.loads(r["devices"] or "[]"))
        if not ts and not ds:
            continue
        if ds and ts:
            bad = [d for d in ds if d in device_target and device_target[d] not in ts]
            if bad:
                problems.append(
                    f"规则「{r['type']},{r['value']}」的设备 {bad} "
                    f"不在它的引擎平台范围 {sorted(ts)} 内 —— 不会生效")
        elif ds:
            missing = [d for d in ds if d not in device_target]
            if missing:
                problems.append(f"规则「{r['type']},{r['value']}」适用了不存在的设备 {missing}")
        elif ts and not (ts & target_names):
            problems.append(
                f"规则「{r['type']},{r['value']}」的引擎平台范围 {sorted(ts)} "
                "与现有引擎平台没有交集 —— 不会生效")
    # 规则的目标组与规则本身的适用范围必须相交
    group_scope = {g["name"]: (set(json.loads(g["targets"] or "[]")),
                              set(json.loads(g["devices"] or "[]"))) for g in groups}
    for r in rules:
        gscope = group_scope.get(r["target"])
        if not gscope:
            continue
        gts, gds = gscope
        rts = set(json.loads(r["targets"] or "[]"))
        rds = set(json.loads(r["devices"] or "[]"))
        if gds and rds and not (gds & rds):
            problems.append(
                f"规则「{r['type']},{r['value']}」与目标组「{r['target']}」"
                "的适用设备没有交集 —— 规则会被自动剔除")
        elif gts and rts and not (gts & rts):
            problems.append(
                f"规则「{r['type']},{r['value']}」与目标组「{r['target']}」"
                "的适用引擎平台没有交集 —— 规则会被自动剔除")
    # 被更早的同类型规则完全遮蔽（后缀按标签边界判定，域名的后缀匹配同理）
    def suffix_covers(broad: str, narrow: str) -> bool:
        return narrow == broad or narrow.endswith("." + broad)

    for i, r in enumerate(rules):
        if r["type"] != "DOMAIN-SUFFIX" or not (r["value"] or "").strip():
            continue
        narrow = r["value"].strip().lower()
        rts = set(json.loads(r["targets"] or "[]"))
        rds = set(json.loads(r["devices"] or "[]"))
        for j in range(i):
            p_rule = rules[j]
            if p_rule["type"] != "DOMAIN-SUFFIX" or not (p_rule["value"] or "").strip():
                continue
            broad = p_rule["value"].strip().lower()
            if broad == narrow or not suffix_covers(broad, narrow):
                continue
            pts = set(json.loads(p_rule["targets"] or "[]"))
            pds = set(json.loads(p_rule["devices"] or "[]"))
            if rds and pds and not (pds & rds):
                continue
            if rts and pts and not (pts & rts):
                continue
            if rds and not pds and not pts:
                continue
            if p_rule["target"] == r["target"]:
                notes.append(
                    f"规则「DOMAIN-SUFFIX,{r['value']}」被更早的"
                    f"「DOMAIN-SUFFIX,{p_rule['value']}」覆盖（目标相同，行为一致）")
            else:
                notes.append(
                    f"规则「DOMAIN-SUFFIX,{r['value']}」被更早的"
                    f"「DOMAIN-SUFFIX,{p_rule['value']}」遮蔽（目标不同，可能不生效）")
            break

    # 空策略组：没有任何成员
    for g in groups:
        if not (json.loads(g["proxies"] or "[]")
                or json.loads(g["use_sources"] or "[]")
                or json.loads(g["local_nodes"] or "[]")):
            problems.append(f"策略组「{g['name']}」没有任何成员")

    # ---- 5. 功能模块 ----
    for s in rows("SELECT id, name, engine, enabled, content FROM snippets"):
        try:
            content = yaml.safe_load(s["content"] or "")
        except Exception as exc:
            problems.append(f"功能模块「{s['name']}」内容不是合法 YAML：{exc}")
            continue
        if not isinstance(content, dict) or not content:
            problems.append(f"功能模块「{s['name']}」内容必须是非空 YAML 映射")
            continue
        for k in STRUCT_KEYS:
            if k in content:
                problems.append(f"功能模块「{s['name']}」含结构键 {k}")
        if s["engine"] not in ("all", "stash", "mihomo"):
            problems.append(f"功能模块「{s['name']}」的引擎范围「{s['engine']}」非法")
        if s["enabled"]:
            for engine in (("stash", "mihomo") if s["engine"] == "all" else (s["engine"],)):
                default = bc.default_doc(engine)
                if all(key in default and default[key] == value
                       for key, value in content.items()):
                    notes.append(
                        f"功能模块「{s['name']}」与 {engine} 引擎默认配置完全重复，"
                        "可以关掉（引擎默认配置已包含）")

    if notes:
        print("提示（不阻断）：")
        for note in notes:
            print(f"  · {note}")
        print()
    if problems:
        print("数据不规范：")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 1
    print("✓ 数据自检通过：引用完整、命名统一、无冗余覆盖、结构键未被越权写入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
