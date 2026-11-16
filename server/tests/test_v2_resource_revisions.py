"""资源 revision 不可变合同。"""

# 真实 .mrs 是 zstd 帧，夹具用同样的头，免得自造标志位掩盖问题
MRS_ZSTD_FRAME = bytes.fromhex(
    '28b52ffd04589900006d72732d666978747572652d7061796c6f616411b84759')


def test_binary_revision_is_immutable_when_source_changes(client):
    from app import db
    from app.services.resource_revisions import freeze_bytes, read_revision
    with db.tx() as conn:
        old = MRS_ZSTD_FRAME + b'fixture'
        first = freeze_bytes(conn, kind='rule', name='r', body=old,
                             behavior='domain', format='mrs')
        again = freeze_bytes(conn, kind='rule', name='r', body=old,
                             behavior='domain', format='mrs')
        newer = freeze_bytes(conn, kind='rule', name='r', body=old + b'next',
                             behavior='domain', format='mrs')
        assert first['id'] == again['id'] and first['id'] != newer['id']
        assert read_revision(conn, first['id']) == old


def test_same_bytes_different_behavior_is_not_merged(client):
    from app import db
    from app.services.resource_revisions import freeze_bytes
    body = MRS_ZSTD_FRAME + b'fixture'
    with db.tx() as conn:
        domain = freeze_bytes(conn, kind='rule', name='same', body=body,
                              behavior='domain', format='mrs')
        ip = freeze_bytes(conn, kind='rule', name='same', body=body,
                          behavior='ipcidr', format='mrs')
        assert domain['id'] != ip['id']
