from v2_helpers import admin, import_source, proxy


def test_subscription_notices_do_not_replace_real_nodes_or_reuse_old_ids(client):
    import pytest
    from app import db
    from app.services import node_catalog, source_nodes

    notice = proxy("发布页: service.example.com")
    real = proxy("香港 01")
    source = import_source(client, admin(client), [notice, real, notice])
    assert source["node_count"] == 1
    assert source_nodes.parse(source_nodes.dump([notice, real])) == [real]
    with pytest.raises(source_nodes.SourceError, match="只有通知"):
        source_nodes.extract(source_nodes.dump([notice]).encode())
    with db.tx(immediate=True) as conn:
        first = node_catalog.list_active_nodes(conn)[0]
        # 旧目录里曾把提示当作节点；有相同连接材料也不能借用旧 ID。
        conn.execute("UPDATE node_catalog SET raw_name=? WHERE node_uid=?",
                     (notice["name"], first["node_uid"]))
        report = node_catalog.retire_subscription_notices(conn)
        assert report["retired"] == [first["node_uid"]]
        assert node_catalog.retire_subscription_notices(conn)["retired"] == []
        node_catalog.reconcile_source(conn, source["id"], [notice, real, notice])
        current, = node_catalog.list_active_nodes(conn)
        assert current["raw_name"] == real["name"] and current["node_uid"] != first["node_uid"]
        assert node_catalog.get_revision(conn, first["node_uid"], 1) is not None


def test_source_rename_keeps_uid_and_material_version(client):
    from app import db
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy('old')])
    with db.tx(immediate=True) as conn:
        first = node_catalog.list_active_nodes(conn)[0]
        report = node_catalog.reconcile_source(conn, source['id'], [proxy('new')])
        second = node_catalog.list_active_nodes(conn)[0]
        assert first['node_uid'] == second['node_uid']
        assert first['revision'] == second['revision'] == 1
        assert second['raw_name'] == 'new' and second['emit_name'] == first['emit_name']
        assert report['renamed'] == [first['node_uid']]


def test_old_connection_material_stays_readable(client):
    from app import db
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        first = node_catalog.list_active_nodes(conn)[0]
        node_catalog.reconcile_source(conn, source['id'], [proxy(password='example-rotated-password')])
        current = node_catalog.list_active_nodes(conn)[0]
        old = node_catalog.load_probe_material(conn, first['node_uid'], 1)
        assert current['node_uid'] == first['node_uid'] and current['revision'] == 2
        assert old['password'] == 'example-test-password'
        assert old['name'] == 'mp-' + first['node_uid']


def test_disappearance_reappearance_and_snapshot_order(client):
    from app import db
    from app.services import node_catalog
    b = {**proxy('B'), 'server': 'other.example.com'}
    source = import_source(client, admin(client), [proxy(), b])
    with db.tx(immediate=True) as conn:
        before = node_catalog.list_active_nodes(conn)
        rev = node_catalog.reconcile_source(conn, source['id'], [b, proxy()])
        assert rev['catalog_revision'] == 1
        assert node_catalog.list_active_nodes(conn) == before
        node_catalog.reconcile_source(conn, source['id'], [])
        assert node_catalog.list_active_nodes(conn) == []
        node_catalog.reconcile_source(conn, source['id'], [b, proxy()])
        assert node_catalog.list_active_nodes(conn) == before
        assert conn.execute('SELECT COUNT(*) FROM node_revisions').fetchone()[0] == 2


def test_multi_account_rotation_is_ambiguous_and_repeat_safe(client):
    from app import db
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy('A', 'example-account-a'), proxy('B', 'example-account-b')])
    with db.tx(immediate=True) as conn:
        before = node_catalog.list_active_nodes(conn)
        report = node_catalog.reconcile_source(conn, source['id'], [proxy('C', 'example-account-c'), proxy('D', 'example-account-d')])
        assert report['issues'] and not report['created'] and not report['retired']
        assert node_catalog.list_active_nodes(conn) == before
        again = node_catalog.reconcile_source(conn, source['id'], [proxy('C', 'example-account-c'), proxy('D', 'example-account-d')])
        assert again['catalog_revision'] == report['catalog_revision']


def test_duplicate_initial_material_does_not_mint_ids_on_retry(client):
    from app import db
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy('A'), proxy('B')])
    with db.tx(immediate=True) as conn:
        before = node_catalog.list_active_nodes(conn)
        report = node_catalog.reconcile_source(conn, source['id'], [proxy('A'), proxy('B')])
        assert report['issues'] and not report['created']
        assert node_catalog.list_active_nodes(conn) == before


def test_safe_revision_no_secrets_and_no_current_fallback(client):
    import pytest
    from v2_helpers import assert_no_secrets
    from app import db
    from app.services import node_catalog
    import_source(client, admin(client), [proxy()])
    with db.connect() as conn:
        node = node_catalog.list_active_nodes(conn)[0]
        revision = node_catalog.get_revision(conn, node['node_uid'], 1)
        assert_no_secrets([node, revision])
        assert not {'material_hmac', 'identity_hmac', 'material_blob_id'} & revision.keys()
        assert revision['configured_secret_fields'] == ['password']
        assert node_catalog.get_revision(conn, node['node_uid'], 999) is None
        with pytest.raises(ValueError, match='catalog_revision_missing'):
            node_catalog.load_probe_material(conn, node['node_uid'], 999)


def test_local_write_toggle_delete_preserves_history(client):
    from v2_helpers import make_local
    from app import db
    from app.services import node_catalog
    h = admin(client)
    local = make_local(client, h)
    with db.connect() as conn:
        first = node_catalog.list_active_nodes(conn)[0]
    assert client.patch(f"/api/v1/local-nodes/{local['id']}/enabled", headers=h, json={'enabled': False}).status_code == 200
    with db.connect() as conn:
        second = node_catalog.list_active_nodes(conn)[0]
        assert not second['enabled'] and second['revision'] == 1
    assert client.delete(f"/api/v1/local-nodes/{local['id']}", headers=h).status_code == 200
    with db.connect() as conn:
        assert node_catalog.list_active_nodes(conn) == []
        assert node_catalog.load_probe_material(conn, first['node_uid'], 1)['password'] == 'example-test-password'


def test_atomic_source_failure_rolls_back_cache_and_catalog(client, monkeypatch):
    import base64
    import yaml
    from app import db, security
    from app.services import node_catalog, resource_store
    h = admin(client)
    source = import_source(client, h, [proxy()])
    with db.connect() as conn:
        before = node_catalog.list_active_nodes(conn)
        cache = security.decrypt_text(conn.execute('SELECT snapshot_enc FROM sources WHERE id=?', (source['id'],)).fetchone()[0])
    def fail(*args, **kwargs):
        raise ValueError('private_blob_invalid')
    monkeypatch.setattr(resource_store, 'put_private', fail)
    try:
        client.put(f"/api/v1/sources/{source['id']}/file", headers=h, json={
            'name': source['name'], 'content_b64': base64.b64encode(yaml.safe_dump({'proxies': [proxy(password='example-rotated')]}).encode()).decode()})
    except ValueError:
        pass
    with db.connect() as conn:
        assert node_catalog.list_active_nodes(conn) == before
        assert security.decrypt_text(conn.execute('SELECT snapshot_enc FROM sources WHERE id=?', (source['id'],)).fetchone()[0]) == cache


def test_backfill_repeat_preserves_ordinals_and_metadata(client):
    from app import db
    from app.migrations import v2_foundation
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        first = node_catalog.list_active_nodes(conn)[0]
        conn.execute('UPDATE node_catalog SET meta_json=?,display_name=?', ('{"note":"manual"}', 'manual'))
        v2_foundation.migrate(conn)
        node_catalog.reconcile_source(conn, source['id'], [proxy('renamed')])
        after = node_catalog.list_active_nodes(conn)[0]
        assert first['node_uid'] == after['node_uid']
        assert after['display_name'] == 'manual' and after['meta'] == {'note': 'manual'}


def test_logical_backup_and_archive_preserve_uid_hmac_and_old_material(client, tmp_path):
    import sqlite3
    from contextlib import closing
    from app import db, config
    from app.services import node_catalog, backups
    source = import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        first = node_catalog.list_active_nodes(conn)[0]
        node_catalog.reconcile_source(conn, source['id'], [proxy(password='example-rotated')])
        rows = [tuple(r) for r in conn.execute('SELECT node_uid,revision,identity_hmac,material_hmac FROM node_revisions ORDER BY revision')]
        payload = backups.export_logical(conn)
        backups.restore_logical(conn, payload)
        assert [tuple(r) for r in conn.execute('SELECT node_uid,revision,identity_hmac,material_hmac FROM node_revisions ORDER BY revision')] == rows
    archive = tmp_path / 'catalog.mpbackup'
    destination = tmp_path / 'restored'
    with db.connect() as conn:
        backups.create_archive(conn, archive)
    backups.restore_archive(archive, destination, key_path=config.SECRET_KEY_PATH)
    with closing(sqlite3.connect(destination / 'magicpanel.db')) as conn:
        conn.row_factory = sqlite3.Row
        assert [tuple(r) for r in conn.execute('SELECT node_uid,revision,identity_hmac,material_hmac FROM node_revisions ORDER BY revision')] == rows
        assert node_catalog.load_probe_material(conn, first['node_uid'], 1)['password'] == 'example-test-password'


def test_legacy_without_catalog_has_explicit_default_and_rebuild_marker(client):
    from app import db
    from app.services import node_catalog, backups
    from app.migrations import v2_foundation
    import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        payload = backups.export_logical(conn)
        payload['version'] = 1
        for table in ('node_catalog', 'catalog_state', 'node_revisions', 'node_aliases', 'catalog_issues'):
            del payload['tables'][table]
        payload['tables']['private_blobs'] = []
        payload['tables']['schema_version'] = [r for r in payload['tables']['schema_version'] if r['key'] != 'v2_catalog']
        backups.restore_logical(conn, payload)
        assert conn.execute('SELECT revision FROM catalog_state WHERE id=1').fetchone()[0] == 1
        v2_foundation.migrate(conn)
        assert len(node_catalog.list_active_nodes(conn)) == 1


def test_trusted_upstream_id_opt_in_binds_existing_then_survives_endpoint_change(client):
    from app import db
    from app.services import node_catalog
    h = admin(client)
    material = {**proxy(), 'provider-id': 'account-123'}
    source = import_source(client, h, [material])
    with db.connect() as conn:
        first = node_catalog.list_active_nodes(conn)[0]
    result = client.put(f"/api/v1/sources/{source['id']}", headers=h, json={
        'name': source['name'], 'trusted_upstream_id_key': 'provider-id'})
    assert result.status_code == 200, result.text
    with db.tx(immediate=True) as conn:
        node_catalog.reconcile_source(conn, source['id'], [material])
        node_catalog.reconcile_source(conn, source['id'], [{**material, 'server': 'new.example.com', 'password': 'example-rotated'}])
        after = node_catalog.list_active_nodes(conn)[0]
        assert first['node_uid'] == after['node_uid'] and after['revision'] == 2
        assert 'account-123' not in str(dict(conn.execute('SELECT * FROM node_catalog').fetchone()))


def test_untrusted_self_reported_id_does_not_merge_endpoints(client):
    from app import db
    from app.services import node_catalog
    source = import_source(client, admin(client), [{**proxy(), 'provider-id': 'same'}])
    with db.tx(immediate=True) as conn:
        first = node_catalog.list_active_nodes(conn)[0]
        node_catalog.reconcile_source(conn, source['id'], [{**proxy(), 'provider-id': 'same', 'server': 'other.example.com'}])
        assert node_catalog.list_active_nodes(conn)[0]['node_uid'] != first['node_uid']


def test_legacy_physical_without_catalog_stages_with_explicit_old_key(client, tmp_path):
    import base64
    import sqlite3
    from contextlib import closing
    from cryptography.fernet import Fernet
    from app import db, config, security
    from app.services import webdav
    import_source(client, admin(client), [proxy()])
    live_key = config.SECRET_KEY_PATH.read_bytes()
    live_token = security.encrypt_text('prime-live')
    old_key = tmp_path / 'old.key'
    old_key.write_bytes(Fernet.generate_key())
    old_fernet = Fernet(old_key.read_bytes())
    snapshot = tmp_path / 'legacy.db'
    with db.connect() as conn, closing(sqlite3.connect(snapshot)) as target:
        conn.backup(target)
    with closing(sqlite3.connect(snapshot)) as conn:
        for table in ('node_aliases', 'node_revisions', 'node_catalog', 'catalog_state', 'catalog_issues', 'private_blobs'):
            conn.execute(f'DROP TABLE {table}')
        conn.execute("DELETE FROM schema_version WHERE key='v2_catalog'")
        row = conn.execute('SELECT id,url_enc,snapshot_enc FROM sources').fetchone()
        conn.execute('UPDATE sources SET url_enc=?,snapshot_enc=? WHERE id=?', (
            old_fernet.encrypt(security.decrypt_text(row[1]).encode()).decode(),
            old_fernet.encrypt(security.decrypt_text(row[2]).encode()).decode(), row[0]))
        conn.commit()
    stage = tmp_path / 'stage'
    result = webdav._restore_files(snapshot, old_key, 'fixture', destination=stage, legacy=True)
    assert result['status'] == 'STAGED'
    with closing(sqlite3.connect(stage / 'magicpanel.db')) as conn:
        assert conn.execute('SELECT COUNT(*) FROM node_catalog').fetchone()[0] == 0
        assert conn.execute('SELECT revision FROM catalog_state WHERE id=1').fetchone()[0] == 0
        assert not conn.execute("SELECT 1 FROM schema_version WHERE key='v2_catalog'").fetchone()
        token = conn.execute('SELECT snapshot_enc FROM sources').fetchone()[0]
        assert b'example-test-password' in old_fernet.decrypt(token.encode())
    assert (stage / 'secret.key').read_bytes() == old_key.read_bytes()
    assert config.SECRET_KEY_PATH.read_bytes() == live_key
    assert security.decrypt_text(live_token) == 'prime-live'


def test_legacy_bad_material_rolls_back_live_restore(client):
    import pytest
    from app import db
    from app.services import node_catalog, backups
    import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        before = node_catalog.list_active_nodes(conn)
        payload = backups.export_logical(conn)
        payload['version'] = 1
        for table in ('node_catalog', 'catalog_state', 'node_revisions', 'node_aliases', 'catalog_issues'):
            del payload['tables'][table]
        payload['tables']['private_blobs'] = []
        payload['tables']['sources'][0]['snapshot_enc'] = 'corrupt'
        with pytest.raises(Exception):
            backups.restore_logical(conn, payload)
        assert node_catalog.list_active_nodes(conn) == before
        assert node_catalog.load_probe_material(conn, before[0]['node_uid'], 1)['password'] == 'example-test-password'


def test_sources_same_name_are_separate_and_delete_keeps_origin_history(client):
    import base64
    import yaml
    from app import db
    from app.services import node_catalog
    h = admin(client)
    first = import_source(client, h, [proxy()])
    result = client.post('/api/v1/sources/import-file', headers=h, json={
        'name': 'second-source', 'auto_test': False,
        'content_b64': base64.b64encode(yaml.safe_dump({'proxies': [proxy()]}).encode()).decode()})
    assert result.status_code == 201
    with db.connect() as conn:
        before = node_catalog.list_active_nodes(conn)
        assert len({n['node_uid'] for n in before}) == 2
        origin = conn.execute('SELECT origin_key FROM node_catalog WHERE source_id=?', (first['id'],)).fetchone()[0]
    assert client.delete(f"/api/v1/sources/{first['id']}", headers=h).status_code == 200
    with db.connect() as conn:
        assert len(node_catalog.list_active_nodes(conn)) == 1
        row = conn.execute('SELECT * FROM node_catalog WHERE origin_key=?', (origin,)).fetchone()
        assert row['retired'] and row['source_id'] is None


def test_source_enabled_change_updates_directory_without_new_material(client):
    from app import db
    from app.services import node_catalog
    h = admin(client)
    source = import_source(client, h, [proxy()])
    with db.connect() as conn:
        first = node_catalog.list_active_nodes(conn)[0]
    assert client.patch(f"/api/v1/sources/{source['id']}/enabled", headers=h, json={'enabled': False}).status_code == 200
    with db.connect() as conn:
        second = node_catalog.list_active_nodes(conn)[0]
        assert not second['enabled'] and second['revision'] == first['revision']


def test_refresh_failure_keeps_catalog_without_network(client, monkeypatch):
    import pytest
    from app import db
    from app.services import node_catalog, updater, fetcher
    source = import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        conn.execute("UPDATE sources SET source_kind='remote' WHERE id=?", (source['id'],))
        before = node_catalog.list_active_nodes(conn)
    def fail(*args, **kwargs):
        raise fetcher.FetchError('offline-fixture')
    monkeypatch.setattr(fetcher, 'fetch', fail)
    with pytest.raises(fetcher.FetchError):
        updater.refresh_source(source['id'], 'fixture')
    with db.connect() as conn:
        assert node_catalog.list_active_nodes(conn) == before


def test_catalog_missing_key_cannot_generate_identity(client, monkeypatch):
    import pytest
    from app import config, db, security
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy()])
    config.SECRET_KEY_PATH.unlink()
    def forbidden():
        raise AssertionError('identity_generated_without_key')
    monkeypatch.setattr(node_catalog.uuid, 'uuid4', forbidden)
    with db.tx(immediate=True) as conn:
        with pytest.raises(security.DecryptError, match='key_required'):
            node_catalog.reconcile_source(conn, source['id'], [proxy('new')])
        assert len(node_catalog.list_active_nodes(conn)) == 1


def test_trusted_duplicate_or_invalid_ids_preserve_existing_and_report_issue(client):
    from app import db
    from app.services import node_catalog
    source = import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        conn.execute("UPDATE sources SET trusted_upstream_id_key='provider-id' WHERE id=?", (source['id'],))
        before = node_catalog.list_active_nodes(conn)
        invalid = node_catalog.reconcile_source(conn, source['id'], [{**proxy(), 'provider-id': True}])
        assert invalid['issues'] and node_catalog.list_active_nodes(conn) == before
        duplicate = node_catalog.reconcile_source(conn, source['id'], [
            {**proxy('A'), 'provider-id': 'duplicate'}, {**proxy('B'), 'provider-id': 'duplicate'}])
        assert duplicate['issues'] and node_catalog.list_active_nodes(conn) == before


def test_restore_rejects_missing_catalog_state_or_current_revision(client):
    import copy
    import pytest
    from app import db
    from app.services import backups
    import_source(client, admin(client), [proxy()])
    with db.tx(immediate=True) as conn:
        original = backups.export_logical(conn)
        for table in ('catalog_state', 'node_revisions'):
            payload = copy.deepcopy(original)
            payload['tables'][table] = []
            with pytest.raises(ValueError, match='backup_invalid_reference'):
                backups.restore_logical(conn, payload)
