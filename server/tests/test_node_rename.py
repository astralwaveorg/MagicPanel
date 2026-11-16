"""节点名称规范化：确定性、地区保留、占位丢弃、批内去重序号。"""
from app.services import node_rename


def test_info_nodes_are_dropped():
    for name in ("剩余流量：95.45 GB", "距离下次重置剩余：22 天", "套餐到期：2027-03-08",
                 "📢 大陆加速:shenlong66.com 官网", "Expire: 2027-01-01"):
        assert node_rename.normalize_name(name) is None, name


def test_region_detection_zh_en_flag():
    cases = {
        "🇺🇸 美国01 Hyper": ("🇺🇸", "美国"),
        "US Los Angeles x2": ("🇺🇸", "美国"),
        "🇯🇵 日本IPV6 移动": ("🇯🇵", "日本"),
        "Japan Tokyo IEPL": ("🇯🇵", "日本"),
        "🇭🇰 香港 06 [Home]": ("🇭🇰", "香港"),
        "新加坡 01": ("🇸🇬", "新加坡"),
        "SG-Lion-01": ("🇸🇬", "新加坡"),
        "韩国 [IEPL] | 5x": ("🇰🇷", "韩国"),
        "🇬🇧 London 2": ("🇬🇧", "英国"),
        "土耳其 [A]": ("🇹🇷", "土耳其"),
        "欧洲1": ("🌍", "欧洲"),
    }
    for name, want in cases.items():
        assert node_rename.detect_region(name) == want, name


def test_normalize_full_format():
    alloc = {}
    out = node_rename.normalize_name("🇺🇸 美国01 Hyper", source="神龙机场", alloc=alloc)
    assert out == "🇺🇸 美国 01 [神龙机场]"
    out2 = node_rename.normalize_name("US-LA 0.5x [A]", source="夜煞云", alloc=alloc)
    assert out2 == "🇺🇸 美国 02 [0.5x·夜煞云]"
    # 家宽进入地区名；IEPL 与运营商成为标签
    out3 = node_rename.normalize_name("日本家宽-01 Home", source="夜煞云", alloc=alloc)
    assert out3 == "🇯🇵 日本家宽 01 [夜煞云]"
    out4 = node_rename.normalize_name("韩国 [IEPL] | 5x 移动", source="夜煞云", alloc=alloc)
    assert out4 == "🇰🇷 韩国 01 [5x·IEPL·移动·夜煞云]"


def test_seq_alloc_is_deterministic_per_batch():
    names = ["🇭🇰 香港 01", "🇭🇰 香港 02", "HK/03", "🇭🇰 香港 01"]
    mapping = node_rename.rename_batch(names, source="夜煞云")
    assert mapping[names[0]] == "🇭🇰 香港 01 [夜煞云]"
    assert mapping[names[1]] == "🇭🇰 香港 02 [夜煞云]"
    assert mapping[names[2]] == "🇭🇰 香港 03 [夜煞云]"
    assert mapping[names[3]] == "🇭🇰 香港 01 [夜煞云]"
    # 同样的输入永远得到同样的输出（确定性）
    assert node_rename.rename_batch(names, source="夜煞云") == mapping


def test_unknown_region_keeps_name():
    assert node_rename.normalize_name("MyPrivate-Relay-01") == "MyPrivate-Relay-01"


def test_multiplier_normalization():
    assert node_rename._extract_multiplier("节点 2X") == "2x"
    assert node_rename._extract_multiplier("节点 0.5x") == "0.5x"
    assert node_rename._extract_multiplier("节点 5倍") == "5x"
    assert node_rename._extract_multiplier("节点 无倍率") is None


def test_snapshot_normalization_drops_info_and_renames():
    text = """
proxies:
  - name: "🇺🇸 美国01 Hyper"
    type: vless
    server: a
    port: 443
  - name: "剩余流量：100GB"
    type: ss
    server: 127.0.0.1
    port: 53
  - name: "US 02"
    type: ss
    server: b
    port: 443
"""
    out = node_rename.normalize_snapshot(text, source="神龙机场")
    import yaml
    data = yaml.safe_load(out)
    names = [p["name"] for p in data["proxies"]]
    assert names == ["🇺🇸 美国 01 [神龙机场]", "🇺🇸 美国 02 [神龙机场]"]
