"""测速与错误说明的边界行为：错误可读、核心读不懂的节点能定位、协议渲染正确。"""


def test_describe_error_translates_known_codes():
    from app.services.access_dto import describe_error
    assert 'mrs' in describe_error('规则内容验证失败：mrs_magic_invalid')
    assert '规则集格式无效' in describe_error('规则内容验证失败：mrs_magic_invalid')
    assert describe_error('上游返回 HTTP 404') == '上游返回 HTTP 404'
    assert '超时' in describe_error('请求失败：ReadTimeout')
    assert '域名解析失败' in describe_error('主机名解析失败：gaierror')
    # 回显不了原文，也不该把订阅地址带出来
    assert 'token' not in describe_error('https://example.com/sub?token=abc')
    assert describe_error('') == ''


def test_start_failure_locates_unreadable_node():
    from app.services.tester import _start_failure
    log = ["Parse config error: proxy 3: unsupport proxy type: juicity\n"]
    index, types, reason = _start_failure(log)
    assert index == 3
    assert types == {'juicity'}
    assert 'juicity' in reason
    # 字段不全的节点同样定位得到
    index, types, reason = _start_failure(
        ["Parse config error: proxy 0: '' has unset fields: transport, username\n"])
    assert index == 0
    assert not types


def test_hysteria_v1_render_matches_official_fields():
    from app.services.local_nodes import render_proxy
    node = {
        'name': 'hy1', 'node_type': '自建', 'protocol': 'hysteria',
        'server': 'a.example.com', 'port': 443,
        'params': {'password': 'pw', 'protocol': 'udp', 'up': 50, 'down': 200,
                   'sni': 's.example.com', 'skip_cert_verify': True,
                   'obfs': 'salamander', 'obfs_password': 'op', 'alpn': 'h3'},
        'extra_yaml': '',
    }
    for engine in ('mihomo', 'stash'):
        entry = render_proxy(node, engine)
        assert entry['type'] == 'hysteria'
        assert entry['auth-str'] == 'pw'
        assert entry['protocol'] == 'udp'
        assert entry['up'] == '50 Mbps' and entry['down'] == '200 Mbps'
        assert entry['sni'] == 's.example.com'
        assert entry['skip-cert-verify'] is True
        assert entry['obfs'] == 'salamander' and entry['obfs-password'] == 'op'
        assert entry['alpn'] == ['h3']


def test_local_protocol_schema_includes_hysteria_v1():
    from app.services.local_nodes import protocol_schema
    values = [item.get('value') for item in protocol_schema()]
    assert 'hysteria' in values and 'hysteria2' in values
