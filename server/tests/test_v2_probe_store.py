"""V2 探测与资源发布持久契约。"""


def test_v2_migration_is_idempotent_and_activation_staged(client):
    from app import db
    from app.services.probe_models import NodeKey
    with db.tx() as conn:
        db.migrate_probe_delivery_v2(conn)
        before = conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        db.migrate_probe_delivery_v2(conn)
        after = conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        names = {row[1] for row in after}
        assert {'probe_jobs', 'probe_items', 'probe_results',
                'probe_reservations', 'resource_revisions',
                'build_manifests', 'deployment_bundles'} <= names
        assert db.get_setting(conn, 'v2_recovery_mode', '') == 'auto_stable_v1'
        assert db.get_setting(conn, 'v2_runtime_activation', '') == 'staged'
        assert before == after
    assert NodeKey('fixture-a', 1) != NodeKey('fixture-a', 2)
