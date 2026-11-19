"""独立 observer、路径资格与基础探针离线合同。"""
import pytest


def test_unknown_nas_path_is_not_vps_and_basic_probe_is_separate(client):
    from app import db
    from app.services import probe_observers as o
    from v2_helpers import at
    with db.tx() as conn:
        o.register(conn, {'id': 'nas', 'kind': 'nas', 'config_revision': 1, 'enabled': True})
        with pytest.raises(o.PathNotQualified):
            o.require_path(conn, 'nas', 1, 'ranking', at(1))
        assert o.admit_target('https://health.example.test/204', google=False,
                              country=None, egress_scope='unknown') is True
        assert o.admit_target('https://www.google.com/', google=True,
                              country='SG', egress_scope='google') is True
        for url in ('https://evil.example/', 'http://www.google.com/',
                    'https://www.google.com:8443/', 'https://user@www.google.com/'):
            assert o.admit_target(url, google=True, country='SG', egress_scope='google') is False


def test_qualify_requires_signed_path_and_scope(client):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app import db
    from app.services import google_evidence, google_receipts, probe_observers as o, probe_store
    from v2_helpers import admin, at, make_local

    make_local(client, admin(client))
    contract = {'scopes': ['ranking', 'google'], 'network': 'test', 'config_revision': 1}
    key = Ed25519PrivateKey.generate()
    record = {'version': 2, 'signed_at': at(0).isoformat(), 'nonce': 'nonce-fixture-1',
              'observation_sha': 'a' * 64}
    record['signature'] = key.sign(o.path_proof_message('nas', contract, record)).hex()
    with db.tx() as conn:
        for name in ('nas', 'other'):
            o.register(conn, {'id': name, 'kind': 'nas', 'config_revision': 1,
                              'public_key': key.public_key().public_bytes_raw().hex()})
        for observer_id, proof in (
            ('other', record), ('nas', {**record, 'nonce': 'nonce-fixture-2'}),
            ('nas', {**record, 'signed_at': at(1).isoformat()}),
            ('nas', {**record, 'observation_sha': 'b' * 64}),
        ):
            with pytest.raises(ValueError, match='path_signature_invalid'):
                o.qualify(conn, observer_id=observer_id, contract=contract, proof=proof, now=at(1))
        path = o.qualify(conn, observer_id='nas', contract=contract, proof=record, now=at(1))
        with pytest.raises(ValueError, match='path_nonce_reused'):
            o.qualify(conn, observer_id='nas', contract=contract, proof=record, now=at(1))
        assert path['state'] == 'verified'
        assert o.require_path(conn, 'nas', path['epoch'], 'ranking', at(2))
        with pytest.raises(o.PathNotQualified):
            o.require_path(conn, 'nas', path['epoch'], 'media', at(2))

        node = conn.execute("SELECT node_uid,current_revision FROM node_catalog").fetchone()
        receipt = {"observer_id": "nas", "path_epoch": path["epoch"],
                   "node_uid": node["node_uid"], "node_revision": node["current_revision"],
                   "measured_at": at(2).isoformat(), "control_sha256": "c" * 64,
                   "products": {host: {"state": "observed-ok", "country": "US",
                                       "egress_sha256": "e" * 64, "result_sha256": "d" * 64}
                                for host in o.GOOGLE_PROBE_HOST_ALLOWLIST}}
        signature = key.sign(google_receipts.message(receipt)).hex()
        queued = probe_store.enqueue(conn, trigger='fixture', observer_id='nas',
            nodes=[(node["node_uid"], node["current_revision"])], services=('google:critical',),
            schedule_key=None, now=at(1), deadline=at(7))
        result = google_receipts.ingest(conn, receipt, signature, now=at(2))
        assert result["state"] == "observed-ok"
        assert conn.execute("SELECT state FROM probe_jobs WHERE id=?", (queued["id"],)).fetchone()[0] == "queued"
        with pytest.raises(ValueError, match='google_receipt_duplicate'):
            google_receipts.ingest(conn, receipt, signature, now=at(3))
        stale = {**receipt, "node_revision": node["current_revision"] + 1}
        with pytest.raises(ValueError, match='google_receipt_invalid'):
            google_receipts.ingest(conn, stale, signature, now=at(3))
        with pytest.raises(ValueError, match='google_node_revision_stale'):
            google_receipts.ingest(conn, stale, key.sign(google_receipts.message(stale)).hex(), now=at(3))

        conn.execute("INSERT INTO probe_adapter_health "
                     "(probe_id,probe_version,state,updated_at) VALUES (?,?,?,?)",
                     ('google-critical', 'v1', 'healthy', at(2).isoformat()))
        assert google_evidence.observations(conn, now=at(3))[0]["measured_at"] == at(2).isoformat()
        conn.execute("UPDATE probe_results SET result_state='blocked'")
        assert google_evidence.observations(conn, now=at(3)) == []
        conn.execute("UPDATE probe_results SET result_state='observed-ok'")
        ambiguous = {**receipt, "measured_at": at(3).isoformat(),
                     "products": {**receipt["products"], "mail.google.com": {
                         **receipt["products"]["mail.google.com"], "state": "auth-required"}}}
        google_receipts.ingest(conn, ambiguous, key.sign(google_receipts.message(ambiguous)).hex(), now=at(3))
        assert [r["state"] for r in google_evidence.observations(conn, now=at(4))] == ["observed-ok", "unknown"]
        conn.execute("UPDATE probe_paths SET proof_json=json_remove(proof_json,'$.signature')")
        assert google_evidence.observations(conn, now=at(3)) == []
        with pytest.raises(o.PathNotQualified):
            o.require_path(conn, 'nas', path['epoch'], 'ranking', at(3))


def test_runner_records_small_result_without_material(client):
    from app.services import probe_observers as o
    from app.services import probe_runner
    from v2_helpers import at
    calls = []

    def transport(request, url, *, headers, body, max_read, deadline):
        calls.append({'url': url, 'max_read': max_read, 'deadline': deadline})
        return {'status': 204, 'body': b'', 'bytes_read': 0, 'bytes_written': 0}

    item = {'node_uid': 'node-a', 'node_revision': 1, 'service_key': 'basic',
            'observer_id': 'nas', 'path_epoch': 1, 'url': 'https://health.example.test/204',
            'google': False, 'country': None, 'egress_scope': 'unknown',
            'secret': 'never-leak'}
    result = probe_runner.run_item(item, transport, now=at(0))
    assert result['result_state'] == 'observed-ok'
    assert calls[0]['max_read'] == 8192
    assert calls[0]['deadline'] <= 6
    assert 'secret' not in str(result)
    assert result['request_count'] == 1
