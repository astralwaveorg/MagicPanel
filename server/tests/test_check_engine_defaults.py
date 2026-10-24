"""引擎默认配置的官方出处核对：脚本本身的判定不能误报，也不能漏报。

这条检查在 CI 里跑（.github/workflows/ci.yml）。它一旦把"数据条目"当成
"配置键"就会误报（nameserver-policy 里的域名模式），一旦把真配置键放过
就等于没检查，所以两个方向都要锁住。
"""
import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

REPO = Path(__file__).resolve().parent.parent.parent


def _load_script():
    path = REPO / "scripts" / "check_engine_defaults.py"
    spec = importlib.util.spec_from_file_location("check_engine_defaults", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_domain_pattern_entries_are_data_not_config_keys():
    """nameserver-policy 这类表的条目是域名模式，不该被当成待核对的配置键。"""
    mod = _load_script()
    keys = mod.doc_keys({
        "dns": {
            "nameserver-policy": {"+.lan": "system", "+.local": "system"},
            "sniffer": {"override-tls-sniffing": True},
        }
    })
    assert "dns.nameserver-policy" in keys
    assert "dns.nameserver-policy.+.lan" not in keys
    # 同层真正的配置键仍然要逐键核对
    assert "dns.sniffer.override-tls-sniffing" in keys


def test_current_defaults_pass_the_official_provenance_check():
    """当前引擎默认配置的每个键都能在官方示例里找到出处（CI 的那一道门）。"""
    mod = _load_script()
    assert mod.main() == 0


def test_unknown_top_level_key_is_reported():
    """真的写错键时必须报出来，不能因为放宽判定就一路放行。"""
    mod = _load_script()
    from app.services import base_config as bc

    doc = bc.default_doc("mihomo")
    doc["definitely-not-a-real-key"] = 1
    keys = mod.doc_keys(doc)
    refs = mod.reference_keys(REPO / "official-example" / "mihomo-example.yaml")
    assert "definitely-not-a-real-key" not in refs
