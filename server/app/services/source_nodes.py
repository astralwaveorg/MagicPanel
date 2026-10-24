"""节点来源的节点定义：只取 proxies 段，渲染时供内联模式展开。

机场订阅本身是一份完整的 Clash 配置（含它自己的 rules / dns / proxy-groups），
面板只取其中的 proxies：其余内容与面板自己的策略无关，
留着既撑大快照，也会让内联模式把机场的规则和策略组混进产物。

过滤与后缀的语义对齐客户端：
* 来源自身的过滤正则作用在**原始节点名**上（provider 的 filter 先于 override）；
* 策略组的过滤正则作用在**加过后缀的节点名**上（客户端的组过滤跑在 provider 之后）。
"""
import re

import yaml


class SourceError(Exception):
    """订阅内容不合法。"""


def extract(body: bytes) -> list[dict]:
    """从订阅内容里取出 proxies 列表（保留完整定义：类型、地址、凭据等）。"""
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise SourceError(f"YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise SourceError("内容不含 proxies 列表，不是有效的节点订阅")
    nodes = [dict(item) for item in data["proxies"]
             if isinstance(item, dict) and item.get("name") and item.get("type")]
    if not nodes:
        raise SourceError("订阅中没有可用节点")
    return nodes


def dump(nodes: list[dict]) -> str:
    """只含 proxies 段的 YAML 文本（快照与 provider 文件都用它）。"""
    return yaml.safe_dump({"proxies": nodes}, allow_unicode=True,
                          sort_keys=False, width=4096)


def parse(text: str) -> list[dict]:
    """从已存快照里取回节点定义；内容坏了就当没有节点。"""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        return []
    return [dict(item) for item in data["proxies"]
            if isinstance(item, dict) and item.get("name") and item.get("type")]


def match(pattern: str, name: str) -> bool:
    """过滤正则是否命中节点名（与客户端一致：不要求整串匹配）。"""
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, name))
    except re.error:
        return True     # 正则无效时不过滤：保存来源时已经拦过一次
