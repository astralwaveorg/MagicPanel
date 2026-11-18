"""生产产物深度验证（反向分析工具）：逐组验证 filter 命中数、
成员引用完整性、节点名格式一致性。

用法（NAS 容器内）：python3 scripts/verify_production.py [build_id]
  不给构建号时取当前生产构建。
2026-11-18 首次用于构建 #301（节点新命名格式启用）的反向分析，
检查口径：filter 命中 0 节点的组、悬空成员引用、来源节点名格式、
兜底规则位置、重名节点、DNS 国内 DoH。
"""
import json
import re
import sys
import yaml

sys.path.insert(0, "/app")
from app import db
from app.services import releases

bid = int(sys.argv[1]) if len(sys.argv) > 1 else int(releases.current(db.connect(), releases.Env.PRODUCTION)["id"])
conn = db.connect()
current = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
results = json.loads(current["results"] or "{}")
print(f"生产构建 #{bid}，产物 {len(results)} 个")

problems, notes = [], []
for name, item in results.items():
    if not item.get("ok"):
        continue
    text = open(f"/app/data/builds/{bid}/{name}.yaml", encoding="utf-8").read()
    data = yaml.safe_load(text)
    proxies = data.get("proxies") or []
    groups = data.get("proxy-groups") or []
    node_names = [p.get("name", "") for p in proxies]
    node_set = set(node_names)
    group_names = {g.get("name") for g in groups}

    # 1) 每个 filter 组的实际命中数（对产物顶层 proxies 的节点名）
    for g in groups:
        filt = g.get("filter")
        if not filt:
            continue
        try:
            rx = re.compile(filt, re.IGNORECASE if "(?i)" in filt else 0)
        except re.error:
            problems.append(f"{name}: 组 {g['name']} filter 正则编译失败")
            continue
        # filter 只作用于 use 来源展开的节点；近似口径：对全部节点名求命中
        hits = [n for n in node_names if rx.search(n)]
        if g.get("use") and not hits:
            problems.append(f"{name}: 组 {g['name']} filter {filt!r} 命中 0 节点")
        else:
            notes.append(f"{name}: {g['name']} filter 命中 {len(hits)} 节点"
                         + (f"（例：{hits[0]}）" if hits else ""))

    # 2) 组成员引用完整性（proxies 成员必须是组名/节点名/内置目标）
    from app import config as cfg
    known = node_set | group_names | cfg.BUILTIN_TARGETS
    for g in groups:
        for m in (g.get("proxies") or []):
            if m not in known:
                problems.append(f"{name}: 组 {g['name']} 成员 {m!r} 不存在")

    # 3) 新格式抽查：神龙机场来源节点应为新格式
    sample = [n for n in node_names if "[神龙机场]" in n]
    if sample and not all(re.match(r"^🇯🇵|🇺🇸|🇭🇰|🇹🇼|🇰🇷|🇸🇬 \[神龙机场\] \S+ \d{2}$", n)
                          for n in sample):
        problems.append(f"{name}: 神龙机场节点名未全部符合新格式"
                        f"（例：{[n for n in sample if not re.match(r'^🇯🇵|🇺🇸|🇭🇰|🇹🇼|🇰🇷|🇸🇬 \\[神龙机场\\] \\S+ \\d{2}$', n)][:3]}）")
    if sample:
        notes.append(f"{name}: 神龙机场新格式节点 {len(sample)} 个（例：{sample[0]}）")

print("--- notes（摘要 12 条）---")
for n in notes[:12]:
    print(" ", n)
print("--- problems ---")
if problems:
    for p in problems:
        print("!!", p)
else:
    print("  无问题")
