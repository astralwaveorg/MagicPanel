"""三层配置的唯一解析入口与受控运行档案。"""
from copy import deepcopy

import pytest


@pytest.mark.parametrize('engine', ['stash', 'mihomo'])
def test_legacy_resolver_matches_three_layers(client, engine):
    from app.services import base_config
    from app.services.config_resolution import resolve_layers
    docs = {(engine, '', 0): {'ipv6': False},
            (engine, 'linux', 0): {'allow-lan': True},
            (engine, 'linux', 9): {'hosts': {'nas.example.com': '10.0.1.2'}}}
    original = deepcopy(docs)
    expected, sources = base_config.cascade(base_config.scope_layers(engine, 'linux', 9, docs))
    result = resolve_layers(engine=engine, platform='linux', device_id=9, docs=docs,
                            runtime_profile='legacy-v1')
    assert result['effective'] == expected
    assert result['provenance'] == sources
    assert result['profile_version'] == 1
    assert docs == original


def test_resolver_preserves_replace_and_device_append_semantics(client):
    from app.services.config_resolution import resolve_layers
    docs = {('mihomo', '', 0): {'_fake_ip_filter': ['a.example']},
            ('mihomo', 'linux', 0): {'_fake_ip_filter': ['b.example']},
            ('mihomo', 'linux', 7): {'_fake_ip_filter': ['b.example', 'c.example']}}
    result = resolve_layers(engine='mihomo', platform='linux', device_id=7, docs=docs)
    assert result['inherited']['_fake_ip_filter'] == ['b.example']
    assert result['effective']['_fake_ip_filter'] == ['b.example', 'c.example']
    assert result['overlay'] == {'_fake_ip_filter': ['b.example', 'c.example']}


def test_default_scope_compares_source_baseline_and_returns_owned_copies(client):
    from app.services import base_config
    from app.services.config_resolution import resolve_layers
    docs = {('mihomo', '', 0): {'ipv6': False}}
    baseline = base_config.default_doc('mihomo')
    result = resolve_layers(engine='mihomo', docs=docs)
    assert result['inherited'] == baseline
    assert result['overlay'] == {'ipv6': False}
    result['effective']['dns']['nameserver'].append('fixture-invalid-server')
    assert base_config.default_doc('mihomo') == baseline
    assert docs == {('mihomo', '', 0): {'ipv6': False}}


def test_input_hash_is_deterministic_and_scoped_to_relevant_layers(client, monkeypatch):
    from app.services import base_config
    from app.services.config_resolution import resolve_layers
    docs = {('mihomo', 'linux', 0): {'allow-lan': True}}
    first = resolve_layers(engine='mihomo', platform='linux', docs=docs)
    more = {**docs, ('stash', 'ios', 4): {'ipv6': False}}
    assert resolve_layers(engine='mihomo', platform='linux', docs=more)['input_sha256'] == first['input_sha256']
    changed = resolve_layers(engine='mihomo', platform='linux', docs={('mihomo', 'linux', 0): {'allow-lan': False}})
    assert changed['input_sha256'] != first['input_sha256']
    original = base_config.default_doc
    monkeypatch.setattr(base_config, 'default_doc', lambda engine: {**original(engine), 'ipv6': False})
    assert resolve_layers(engine='mihomo', platform='linux', docs=docs)['input_sha256'] != first['input_sha256']


def test_profile_version_participates_in_input_hash(client, monkeypatch):
    from app.services import runtime_profiles
    from app.services.config_resolution import resolve_layers
    before = resolve_layers(engine='mihomo', platform='linux')
    original = runtime_profiles.get_profile
    monkeypatch.setattr(runtime_profiles, 'get_profile', lambda *a, **kw: {**original(*a, **kw), 'version': 2})
    after = resolve_layers(engine='mihomo', platform='linux')
    assert before['input_sha256'] != after['input_sha256']
    assert after['profile_version'] == 2


@pytest.mark.parametrize('profile', ['openclash-v2', 'terminal-v2', 'unknown', ''])
def test_unimplemented_profiles_cannot_be_activated(client, profile):
    from app.services.config_resolution import resolve_layers
    with pytest.raises(ValueError, match='runtime_profile_invalid'):
        resolve_layers(engine='mihomo', platform='linux', runtime_profile=profile)


def test_invalid_config_hash_never_echoes_input_material(client):
    from app.services.config_resolution import resolve_layers
    with pytest.raises(ValueError) as caught:
        resolve_layers(engine='mihomo', docs={('mihomo', '', 0): {
            'fixture-secret-value': float('nan')}})
    assert str(caught.value) == 'config_resolution_invalid'


def test_renderer_rejects_unknown_profile_instead_of_silently_using_legacy(client):
    from app.compiler.render import render_target
    snapshot = {'sources': [], 'groups': [], 'rule_providers': [], 'rules': [], 'snippets': []}
    target = {'engine': 'mihomo', 'platform': 'linux', 'default_runtime_profile': 'unknown'}
    with pytest.raises(ValueError, match='runtime_profile_invalid'):
        render_target(snapshot, target)
