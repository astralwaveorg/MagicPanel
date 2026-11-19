"""把节点质量结论导出为通过核心校验的 Mihomo 达标池。"""
import logging
import re
from string import Formatter
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from .. import config

logger = logging.getLogger("magicpanel.node_classes")

OUTPUT_DIR = config.DATA_DIR / "node-classes"

# Mihomo 节点名合法性：规则语法里逗号是分隔符，等号是键值分隔符
ILLEGAL_NAME_CHARS = re.compile(r"[,#=\n\r\t]")
MAX_NAME_LEN = 80
DEFAULT_NAME_TEMPLATE = "{name} · {original}"


def valid_name_template(template: str) -> bool:
    """只接受有限占位符，模板不能读取对象字段或执行格式转换。"""
    try:
        fields = [(field, spec, conv) for _, field, spec, conv in Formatter().parse(template)
                  if field is not None]
    except ValueError:
        return False
    return (0 < len(template) <= 100 and bool(fields)
            and all(field in {"name", "original", "region", "badges", "performance"} and not spec and not conv
                    for field, spec, conv in fields))


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
        if ILLEGAL_NAME_CHARS.search(name) or len(name) > MAX_NAME_LEN:
            raise ClassifyError("节点名称包含分隔符或过长")
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
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(text)
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


def classify(results: dict, proxies_by_name: dict[str, dict], *,
             template: str = DEFAULT_NAME_TEMPLATE) -> dict[str, list[dict]]:
    """按质量结果与能力标签分组。

    results：``{节点名: {delay_ms, speed_bps, stage, badges, region, probes}}``
    proxies_by_name：``{节点名: Mihomo 节点字典}``
    """
    groups: dict[str, list[dict]] = {
        "qualified": [], "rejected": [], "ai": [], "stream": [],
        "netflix_premium": [], "fast": [],
    }
    from . import node_rename
    if not valid_name_template(template):
        template = DEFAULT_NAME_TEMPLATE
    used: set[str] = set()
    for name, item in sorted(results.items()):
        proxy = proxies_by_name.get(name)
        if not proxy:
            continue
        if item.get("stage") not in {"probed", "latency_failed", "speed_failed"}:
            continue
        entry = {k: v for k, v in proxy.items() if k != "source_id"}
        label = node_rename.normalize_name(str(name), badge=item.get("badges") or "",
                                           speed_bps=item.get("speed_bps", 0),
                                           delay_ms=item.get("delay_ms", -1))
        original = _safe_name(str(name), set())
        speed = item.get("speed_bps") or 0
        delay = item.get("delay_ms", -1)
        performance = " / ".join(([f"{speed / 1_000_000:.1f} MB/s"] if speed > 0 else [])
                                 + ([f"{delay} ms"] if delay >= 0 else []))
        display = template.format(name=label or original, original=original[:27],
                                  badges=item.get("badges", ""), region=item.get("region", ""),
                                  performance=performance)
        if template == DEFAULT_NAME_TEMPLATE and (not label or label == original):
            display = f"{original} {performance}".strip()
        entry["name"] = _safe_name(display or original, used)
        qualified = item.get("stage") == "probed"
        if qualified:
            groups["qualified"].append(entry)
        else:
            groups["rejected"].append(entry)
            continue
        badges = str(item.get("badges") or "")
        if "🔓" in badges:
            groups["ai"].append(entry)
        if "🎬" in badges:
            groups["stream"].append(entry)
        if "📺" in badges:
            groups["netflix_premium"].append(entry)
        groups["fast"].append(entry)
        region = str(item.get("region") or "")
        if re.fullmatch("[A-Z]{2}", region):
            groups.setdefault(f"region-{region}", []).append(entry)
        for pid, probe in (item.get("probes") or {}).items():
            if re.fullmatch("[a-z0-9_]+", pid) and probe.get("state") == "unlocked":
                groups.setdefault(f"platform-{pid}", []).append(entry)
    return groups


def export_pools(results: dict, candidates: list[dict], validate_config, *,
                 template: str = DEFAULT_NAME_TEMPLATE) -> str:
    """导出只含达标节点的配置。失败时不覆盖上一份通过校验的文件。"""
    groups = classify(results, {p["name"]: p for p in candidates}, template=template)
    qualified = groups["qualified"]
    if not qualified:
        raise ClassifyError("没有可导出的达标节点")
    _validate_proxies(qualified)
    labels = {"qualified": "达标节点", "ai": "AI 解锁", "stream": "流媒体解锁",
              "netflix_premium": "Netflix 非自制剧样本"}
    used = {p["name"] for p in qualified}
    proxy_groups = []
    for tag, entries in groups.items():
        if not entries or tag in {"fast", "rejected"}:
            continue
        label = labels.get(tag, tag.removeprefix("platform-"))
        if label.startswith("region-"):
            label = "地区 · " + label.removeprefix("region-")
        else:
            label = "质量 · " + label
        proxy_groups.append({"name": _safe_name(label, used), "type": "select",
                             "proxies": [p["name"] for p in entries]})
    text = yaml.safe_dump({"proxies": qualified, "proxy-groups": proxy_groups},
                          allow_unicode=True, sort_keys=False)
    directory = OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(text)
    try:
        content = tmp.read_text(encoding="utf-8")
        _validate_proxies(yaml.safe_load(content)["proxies"])
        checked, error = validate_config(content)
        if not checked or error:
            raise ClassifyError("Mihomo 未通过校验，保留上次导出的文件")
        tmp.replace(directory / "node-pools.yaml")
    finally:
        tmp.unlink(missing_ok=True)
    return text
