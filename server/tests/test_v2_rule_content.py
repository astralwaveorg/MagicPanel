"""规则内容严格验证与健康时效。"""
import pytest

# 真实 .mrs 文件头：zstd 帧 magic + 帧数据（本地 zstd 生成，非自造标志位）
MRS_ZSTD_FRAME = bytes.fromhex(
    '28b52ffd04589900006d72732d666978747572652d7061796c6f616411b84759')


def test_html_and_bad_mrs_are_not_valid():
    from app.services.rule_content import RuleContentError, validate_rule_content
    with pytest.raises(RuleContentError, match='html_rejected'):
        validate_rule_content(b'<html>payload: 1</html>', fmt='yaml',
                              behavior='domain', engine_caps={})
    with pytest.raises(RuleContentError, match='mrs_magic_invalid'):
        validate_rule_content(b'not mrs', fmt='mrs', behavior='domain',
                              engine_caps={})
    # 旧实现把 "MRS" 文本头当成 mrs 标志，真实 .mrs 并不是这个头
    with pytest.raises(RuleContentError, match='mrs_magic_invalid'):
        validate_rule_content(b'MRS\x00fixture', fmt='mrs', behavior='domain',
                              engine_caps={})


def test_zstd_framed_mrs_passes_validation():
    from app.services.rule_content import validate_rule_content
    result = validate_rule_content(MRS_ZSTD_FRAME, fmt='mrs',
                                   behavior='domain', engine_caps={})
    assert result['format'] == 'mrs' and result['behavior'] == 'domain'
    assert result['body_sha'] and result['semantic_sha']


def test_yaml_structure_and_behavior_count():
    from app.services.rule_content import RuleContentError, validate_rule_content
    body = b'payload:\n  - DOMAIN-SUFFIX,example.test\n'
    result = validate_rule_content(body, fmt='yaml', behavior='classical',
                                   engine_caps={})
    assert result['count'] == 1 and result['format'] == 'yaml'
    with pytest.raises(RuleContentError, match='yaml_structure_invalid'):
        validate_rule_content(b'rules: []\n', fmt='yaml', behavior='domain',
                              engine_caps={})


def test_rule_health_fresh_stale_expired():
    from app.services.rule_health import evaluate_rule_health
    refs = [{'rule_id': 'r', 'validated_at': '2026-11-01T00:00:00+00:00',
             'content_sha': 'a'}]
    result = evaluate_rule_health(refs, now='2026-11-05T00:00:00+00:00', policy={})
    assert result['sources']['r'] == 'fresh'
    stale = evaluate_rule_health(refs, now='2026-11-10T00:00:00+00:00', policy={})
    assert stale['sources']['r'] == 'stale'
    expired = evaluate_rule_health(refs, now='2026-11-20T00:00:00+00:00', policy={})
    assert expired['sources']['r'] == 'expired'
    assert expired['blockers'] == ['r']


def test_304_without_local_body_is_not_healthy():
    from app.services.rule_health import evaluate_rule_health
    result = evaluate_rule_health([{'rule_id': 'lost', 'validated_at': '2026-11-01T00:00:00+00:00',
                                    'content_sha': None}], now='2026-11-02T00:00:00+00:00',
                                  policy={})
    assert result['sources']['lost'] == 'expired'
    assert 'lost' in result['blockers']


def test_invalid_fetch_keeps_previous_content(client, monkeypatch):
    from app import db, security
    from app.services import updater
    with db.tx() as conn:
        cur = conn.execute("""INSERT INTO rule_providers(name,behavior,format,kind,url,enabled,
                           interval,content,rule_count,sha256,last_status,created_at,updated_at)
                           VALUES('fixture-html','domain','yaml','remote','https://rules.example/rule.yaml',
                           1,86400,'payload: []',1,'old','ok',?,?)""", (db.now(), db.now()))
        rp_id = cur.lastrowid

    def bad(url, ua='fixture', allow_private=False, proxy='', headers=None):
        return b'<html>payload: 1</html>'

    monkeypatch.setattr(updater.fetcher, 'fetch', bad)
    try:
        updater.refresh_provider(rp_id, 'fixture')
    except updater.fetcher.FetchError:
        pass
    else:
        raise AssertionError('invalid rule content must fail refresh')
    with db.connect() as conn:
        row = db.one(conn, 'SELECT content,sha256,last_status FROM rule_providers WHERE id=?', (rp_id,))
        revisions = db.all_(conn, 'SELECT id FROM resource_revisions WHERE logical_name=?', ('fixture-html',))
    assert row['content'] == 'payload: []' and row['last_status'] == 'failed'
    assert revisions == []


def test_valid_mrs_fetch_creates_exact_revision(client, monkeypatch):
    from app import db
    from app.services import updater
    from app.services.resource_revisions import read_revision
    with db.tx() as conn:
        cur = conn.execute("""INSERT INTO rule_providers(name,behavior,format,kind,url,enabled,
                           interval,content,rule_count,sha256,last_status,created_at,updated_at)
                           VALUES('fixture-mrs','domain','mrs','remote','https://rules.example/rule.mrs',
                           1,86400,'',0,'old','ok',?,?)""", (db.now(), db.now()))
        rp_id = cur.lastrowid
    body = MRS_ZSTD_FRAME + b'exact-bytes'
    monkeypatch.setattr(updater.fetcher, 'fetch', lambda *a, **k: body)
    updater.refresh_provider(rp_id, 'fixture')
    with db.connect() as conn:
        row = db.one(conn, 'SELECT content,last_status FROM rule_providers WHERE id=?', (rp_id,))
        row2 = db.one(conn, 'SELECT id FROM resource_revisions WHERE logical_name=?', ('fixture-mrs',))
    import base64
    assert row['last_status'] == 'ok'
    assert base64.b64decode(row['content']) == body
    with db.connect() as check_conn:
        assert read_revision(check_conn, row2['id']) == body
