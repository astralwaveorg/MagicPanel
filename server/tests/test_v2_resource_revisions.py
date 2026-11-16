"""资源 revision 不可变合同。"""


def test_binary_revision_is_immutable_when_source_changes(client):
    from app import db
    from app.services.resource_revisions import freeze_bytes, read_revision
    with db.tx() as conn:
        old = b'MRS\x00fixture'
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
    body = b'MRS\x00fixture'
    with db.tx() as conn:
        domain = freeze_bytes(conn, kind='rule', name='same', body=body,
                              behavior='domain', format='mrs')
        ip = freeze_bytes(conn, kind='rule', name='same', body=body,
                          behavior='ipcidr', format='mrs')
        assert domain['id'] != ip['id']
