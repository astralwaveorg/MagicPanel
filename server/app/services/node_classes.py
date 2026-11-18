"""节点分类输出：把质量结果整理成可直接用的 Mihomo 节点列表与分类文件。

产物（``data/node-classes/``）：
* ``qualified.yaml``   —— 主可用池（一级+二级达标）的 ``proxies:``
* ``<tag>.yaml``       —— 按能力标签分组的节点（ai / stream / netflix_premium …）
* ``rejected.yaml``    —— 未达标池（延迟或吞吐不达标）
* ``snapshot-<ts>.json`` —— 本轮结果快照（对比变化用）

写入一律「临时文件 → 校验 → 原子替换」：校验不过就保留旧文件，绝不写坏产物。
"""
import json
import logging
import re
import time
from pathlib import Path

import yaml

from .. import config

logger = logging.getLogger("magicpanel.node_classes")

OUTPUT_DIR = config.DATA_DIR / "node-classes"

# Mihomo 节点名合法性：规则语法里逗号是分隔符，等号是键值分隔符
ILLEGAL_NAME_CHARS = re.compile(r"[,#=\n\r\t]")
MAX_NAME_LEN = 80


class ClassifyError(Exception):
    """分类产物校验失败。"""


def _safe_name(name: str, used: set[str]) -> str:
    """合法化节点名：去非法字符、截断、重名加后缀。"""
    clean = ILLEGAL_NAME_CHARS.sub(" ", str(name or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) > MAX_NAME_LEN:
        clean = clean[:MAX_NAME_LEN].rstrip()
    if not clean:
        clean = "node"
    candidate = clean
    index = 2
    while candidate in used:
        suffix = f"-{index:02d}"
        base = clean[: MAX_NAME_LEN - len(suffix)].rstrip()
        candidate = f"{base}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _validate_proxies(proxies: list[dict]) -> None:
    """Mihomo 节点最小字段校验 + 重名检查。"""
    names = set()
    for proxy in proxies:
        if not isinstance(proxy, dict):
            raise ClassifyError("节点不是字典")
        name = proxy.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ClassifyError("节点缺少名称")
        if name in names:
            raise ClassifyError(f"节点重名：{name}")
        names.add(name)
        if not proxy.get("server"):
            raise ClassifyError(f"节点 {name} 缺少 server")
        if not proxy.get("type"):
            raise ClassifyError(f"节点 {name} 缺少 type")
        port = proxy.get("port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ClassifyError(f"节点 {name} 的 port 非法：{port}")


def write_yaml(path: Path, proxies: list[dict], header: str = "") -> None:
    """原子写一个 Mihomo proxies 文件。"""
    _validate_proxies(proxies)
    payload = {"proxies": proxies}
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    if header:
        text = f"# {header}\n{text}"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    # 写完再读回来校验：语法坏了就删临时文件、保留旧产物
    try:
        parsed = yaml.safe_load(tmp.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("proxies"), list):
            raise ClassifyError("生成的 YAML 结构不对")
        _validate_proxies(parsed["proxies"])
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)


def classify(results: dict, proxies_by_name: dict[str, dict]) -> dict[str, list[dict]]:
    """按质量结果与能力标签分组。

    results：``{节点名: {delay_ms, speed_bps, stage, badges, region, probes}}``
    proxies_by_name：``{节点名: Mihomo 节点字典}``
    """
    groups: dict[str, list[dict]] = {
        "qualified": [], "rejected": [], "ai": [], "stream": [],
        "netflix_premium": [], "fast": [],
    }
    used: set[str] = set()
    for name, item in sorted(results.items()):
        proxy = proxies_by_name.get(name)
        if not proxy:
            continue
        entry = dict(proxy)
        entry["name"] = _safe_name(str(name), used)
        qualified = (item.get("stage") == "probed"
                     or (int(item.get("delay_ms") or -1) >= 0
                         and int(item.get("delay_ms") or -1) < 600
                         and int(item.get("speed_bps") or 0) >= 2 * 1024 * 1024))
        if qualified:
            groups["qualified"].append(entry)
        else:
            groups["rejected"].append(entry)
        badges = str(item.get("badges") or "")
        if "🔓" in badges:
            groups["ai"].append(entry)
        if "🎬" in badges:
            groups["stream"].append(entry)
        if "📺" in badges:
            groups["netflix_premium"].append(entry)
        if int(item.get("speed_bps") or 0) >= 2 * 1024 * 1024:
            groups["fast"].append(entry)
    return groups


def write_outputs(results: dict, proxies_by_name: dict[str, dict]) -> dict:
    """生成全部分类文件（原子写 + 历史快照）。"""
    groups = classify(results, proxies_by_name)
    written = {}
    for tag, proxies in groups.items():
        if not proxies:
            continue
        path = OUTPUT_DIR / f"{tag}.yaml"
        write_yaml(path, proxies,
                   header=f"MagicPanel 节点分类 · {tag} · {time.strftime('%Y-%m-%d %H:%M:%S')}")
        written[tag] = len(proxies)
    # 结果快照（对比变化用）
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snapshot = OUTPUT_DIR / f"snapshot-{stamp}.json"
    snapshot.write_text(json.dumps(
        {"at": int(time.time()), "counts": written,
         "nodes": {k: {kk: vv for kk, vv in v.items() if kk != "probes"}
                   for k, v in results.items()}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    for old in sorted(OUTPUT_DIR.glob("snapshot-*.json"))[:-20]:
        try:
            old.unlink()
        except OSError:
            pass
    return written
