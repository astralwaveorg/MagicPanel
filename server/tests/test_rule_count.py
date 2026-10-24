"""规则条目数统计：带注释头的 YAML 要按 payload 条目算，不能把 payload: 那行数进去。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_plain_payload_file_counts_entries():
    from app.services import fetcher

    body = b"payload:\n- +.a.com\n- +.b.com\n"
    assert fetcher.count_rules(body, "domain") == 2


def test_commented_header_file_counts_entries():
    """自维护仓库的规则集都带注释头，条目数不能多算一行。"""
    from app.services import fetcher

    body = ("# 名称: ads-minimal\n"
            "# behavior: domain\n"
            "# 条目: 4\n"
            "payload:\n"
            "  - ad.doubleclick.net\n"
            "  - googleads.g.doubleclick.net\n"
            "  - pagead2.googlesyndication.com\n"
            "  - adservice.google.com\n").encode()
    assert fetcher.count_rules(body, "domain") == 4


def test_commented_header_without_payload_falls_back_to_line_count():
    from app.services import fetcher

    body = b"# a comment\nDOMAIN,a.com\nDOMAIN,b.com\n"
    assert fetcher.count_rules(body, "classical") == 2


def test_plain_text_rule_set_counts_lines():
    from app.services import fetcher

    body = b"DOMAIN,a.com\nDOMAIN,b.com\nDOMAIN,c.com\n"
    assert fetcher.count_rules(body, "classical") == 3


def test_mrs_returns_zero():
    from app.services import fetcher

    assert fetcher.count_rules(b"\x00\x01binary", "domain", "mrs") == 0
