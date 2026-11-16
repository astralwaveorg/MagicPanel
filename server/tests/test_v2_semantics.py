"""跨引擎周期、Google 图与路由解释语义。"""


def test_weekly_interval_roundtrip_and_google_direct_leaf(client):
    from conftest import auth_headers, setup_admin
    from app.compiler.semantics import validate_google_graph
    csrf = setup_admin(client)
    response = client.post('/api/v1/groups', headers=auth_headers(csrf), json={
        'name': '周周期组', 'type': 'select', 'proxies': ['DIRECT'], 'interval': 604800})
    assert response.status_code == 201, response.text
    assert response.json()['interval'] == 604800
    graph = {'groups': [{'id': 1, 'name': 'Google', 'members': [
        {'kind': 'group', 'ref': '2'}]}, {'id': 2, 'name': 'nested', 'members': [
        {'kind': 'builtin', 'ref': 'DIRECT'}]}]}
    errors = validate_google_graph(graph, {'google_group_id': 1,
                                           'country_tiers': ['US', 'SG', 'JP']})
    assert any(error['code'] == 'google_direct_leaf' for error in errors)


def test_route_explanation_keeps_unknown_preceding_asn(monkeypatch):
    import socket
    from app.services.route_explanation import explain_route

    def no_dns(*args, **kwargs):
        raise AssertionError('unexpected_dns')

    monkeypatch.setattr(socket, 'getaddrinfo', no_dns)
    snapshot = {'rules': [{'id': 1, 'type': 'IP-ASN', 'value': '15169', 'target': 'Google'},
                          {'id': 2, 'type': 'MATCH', 'value': '', 'target': 'Proxy'}]}
    result = explain_route(snapshot, {'host': 'example.test', 'network': 'tcp',
                                      'dst_port': 443}, {})
    assert result['matched_rule'] is None
    assert any(stage['state'] == 'unknown' for stage in result['stages'])
    assert 'dst_asn' in str(result['limitations'])


def test_semantics_reports_week_and_engine_invariants(client):
    from app.compiler.semantics import validate_semantics
    errors = validate_semantics({'groups': [{'name': 'weekly', 'type': 'url-test',
                                             'interval': 604801}],
                                 'rule_providers': [{'name': 'bad', 'format': 'mrs',
                                                     'behavior': 'classical'}]},
                                engine='mihomo', capabilities={})
    assert any(error['code'] == 'interval_range' for error in errors)
    assert any(error['code'] == 'mrs_behavior_invalid' for error in errors)
