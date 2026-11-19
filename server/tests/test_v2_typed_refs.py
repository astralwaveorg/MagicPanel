import pytest

from conftest import auth_headers, setup_admin


def test_group_ref_cannot_cross_variant(client):
    from app.services.node_refs import resolve_refs
    with pytest.raises(ValueError, match='group_cross_variant'):
        resolve_refs([{'kind':'group','ref':'8'}], variant_id=0,
                     groups=[{'id':8,'variant_id':1,'name':'同名组'}], nodes=[])


def test_node_position_dedup_and_disabled(client):
    from app.services.node_refs import resolve_refs
    refs = [{'kind':'builtin','ref':'DIRECT'}, {'kind':'node','ref':'node'}, {'kind':'node','ref':'node'}]
    nodes = [{'node_uid':'node','emit_name':'New (机房)','enabled':True}]
    assert resolve_refs(refs, variant_id=0, groups=[], nodes=nodes) == ['DIRECT','New (机房)']
    with pytest.raises(ValueError,match='reference_ambiguous'):
        resolve_refs([{'kind':'node','ref':'node'},{'kind':'node','ref':'other'}],variant_id=0,groups=[],
                     nodes=nodes+[{'node_uid':'other','emit_name':'New (机房)','enabled':True}])
    nodes[0]['enabled'] = False
    with pytest.raises(ValueError, match='node_disabled'):
        resolve_refs(refs, variant_id=0, groups=[], nodes=nodes)


def test_cycle_and_invalid_reference(client):
    from app.services.node_refs import resolve_refs
    groups = [{'id':1,'variant_id':0,'name':'a','members_v2':[{'kind':'group','ref':'2'}]},
              {'id':2,'variant_id':0,'name':'b','members_v2':[{'kind':'group','ref':'1'}]}]
    with pytest.raises(ValueError, match='reference_cycle'):
        resolve_refs([{'kind':'group','ref':'1'}], variant_id=0, groups=groups, nodes=[])
    for ref in [{'kind':'x','ref':'DIRECT'}, {'kind':'group','ref':1}, {'kind':'builtin','ref':'UNKNOWN'}]:
        with pytest.raises(ValueError):
            resolve_refs([ref], variant_id=0, groups=[], nodes=[])


def test_api_typed_copy_rename_delete_preserves_order(client):
    from conftest import setup_admin, auth_headers
    from app import db
    h = auth_headers(setup_admin(client))
    def post(path, body):
        response = client.post('/api/v1/'+path,headers=h,json=body)
        assert response.status_code == 201,response.text
        return response.json()
    a = post('groups',{'name':'a','proxies':['DIRECT'],'use_sources':[]})
    node = post('local-nodes',{'name':'fixture','node_type':'机房','protocol':'ss','server':'n.example.com','port':8388,
                              'params':{'cipher':'aes-256-gcm','password':'fixture-only'}})
    with db.connect() as conn:
        uid = conn.execute('SELECT node_uid FROM node_catalog WHERE local_node_id=?',(node['id'],)).fetchone()[0]
    refs = [{'kind':'group','ref':str(a['id'])},{'kind':'node','ref':uid},{'kind':'builtin','ref':'DIRECT'}]
    b = post('groups',{'name':'b','members_v2':refs,'use_sources':[]})
    assert b['members_v2'] == refs
    assert b['proxies'] == ['a','fixture (机房)','DIRECT']
    r = post('rules',{'type':'MATCH','target_ref_v2':{'kind':'group','ref':str(b['id'])}})
    assert isinstance(r['target_ref_v2'],dict)
    from app.routers.builds import collect_snapshot
    from app.compiler.render import render_target
    import yaml
    with db.connect() as conn:
        snapshot = collect_snapshot(conn)
    output = yaml.safe_load(render_target(snapshot,{'name':'stash-ios','engine':'stash','platform':'ios','extra_yaml':''}))
    assert next(g for g in output['proxy-groups'] if g['name'] == 'b')['proxies'] == ['a','fixture (机房)','DIRECT']

    duplicate = client.post('/api/v1/groups',headers=h,json={'name':'bad','members_v2':[],'proxies':[]})
    assert duplicate.status_code == 400
    copied = post('variants',{'name':'copy','copy_from':0})
    cg = client.get('/api/v1/groups',params={'variant':copied['id']},headers=h).json()
    ca, cb = cg
    assert cb['members_v2'][0]['ref'] == str(ca['id'])
    assert cb['members_v2'][1]['ref'] == uid
    before = [(g['id'],g['sort']) for g in client.get('/api/v1/groups',headers=h).json()]
    changed = client.put('/api/v1/local-nodes/'+str(node['id']),headers=h,json={
        'name':'renamed','node_type':'中转','protocol':'ss','server':'n.example.com','port':8388})
    assert changed.status_code == 200,changed.text
    for vid in (0,copied['id']):
        current = client.get('/api/v1/groups',params={'variant':vid},headers=h).json()
        assert current[1]['proxies'] == ['a','renamed (中转)','DIRECT']
    assert before == [(g['id'],g['sort']) for g in client.get('/api/v1/groups',headers=h).json()]
    renamed_group = client.put('/api/v1/groups/'+str(a['id']),headers=h,json={
        'name':'renamed group','proxies':['DIRECT'],'use_sources':[]})
    assert renamed_group.status_code == 200,renamed_group.text
    current = client.get('/api/v1/groups',headers=h).json()
    assert current[1]['members_v2'][0]['ref'] == str(a['id'])
    assert current[1]['proxies'][0] == 'renamed group'
    with db.tx() as conn:
        conn.execute("UPDATE proxy_groups SET members_format='legacy',members_v2='[]' WHERE id=?",(cb['id'],))
    blocked = client.delete('/api/v1/local-nodes/'+str(node['id']),headers=h)
    assert blocked.status_code == 409
    assert len(blocked.json()['detail']['references']) == 2
    assert client.delete('/api/v1/groups/'+str(a['id'])+'?force=1',headers=h).status_code == 200
    assert client.get('/api/v1/groups',params={'variant':copied['id']},headers=h).json()[1]['proxies'][0] == 'a'
    assert client.delete('/api/v1/local-nodes/'+str(node['id'])+'?force=1',headers=h).status_code == 200


def test_legacy_adapter_ambiguity_and_local_first(client):
    from app.services.node_refs import legacy_refs
    nodes = [{'node_uid':'n','emit_name':'same','local_node_id':4}]
    with pytest.raises(ValueError,match='reference_ambiguous'):
        legacy_refs(['same'],variant_id=0,groups=[{'id':1,'variant_id':0,'name':'same'}],nodes=nodes)
    refs = legacy_refs(['DIRECT','same','same'],variant_id=0,groups=[],nodes=nodes,local_ids=[4],local_first=True)
    assert refs == [{'kind':'node','ref':'n'},{'kind':'builtin','ref':'DIRECT'}]
    with pytest.raises(ValueError,match='reference_missing'):
        legacy_refs(['old alias'],variant_id=0,groups=[],nodes=nodes)


def test_snapshot_rejects_invalid_typed_and_ignores_stale_projection(client):
    from app.services.node_refs import resolve_snapshot
    snap = {'groups':[{'id':1,'variant_id':0,'name':'a','members_format':'typed-v2',
                       'members_v2':[{'kind':'builtin','ref':'DIRECT'}],'proxies':['stale']}], 'rules':[]}
    assert resolve_snapshot(snap)['groups'][0]['proxies'] == ['DIRECT']
    snap['groups'][0]['members_v2'] = [{'kind':'node','ref':'missing'}]
    with pytest.raises(ValueError,match='node_missing'):
        resolve_snapshot(snap)


def test_migration_keeps_ids_sorts_and_unknown_groups_legacy(client):
    from conftest import setup_admin, auth_headers
    from app import db
    from app.services import node_refs
    import json
    h = auth_headers(setup_admin(client))
    a = client.post('/api/v1/groups',headers=h,json={'name':'a','proxies':['DIRECT']}).json()
    b = client.post('/api/v1/groups',headers=h,json={'name':'b','proxies':['DIRECT']}).json()
    with db.tx() as conn:
        conn.execute("UPDATE proxy_groups SET sort=47,members_format='legacy',members_v2='[]',proxies=? WHERE id=?",
                     (json.dumps(['DIRECT','unknown alias']),a['id']))
        conn.execute("UPDATE proxy_groups SET sort=13,members_format='legacy',members_v2='[]' WHERE id=?",(b['id'],))
        before = [tuple(r) for r in conn.execute('SELECT id,sort FROM proxy_groups ORDER BY sort,id')]
        node_refs.migrate_refs(conn)
        node_refs.migrate_refs(conn)
        assert [tuple(r) for r in conn.execute('SELECT id,sort FROM proxy_groups ORDER BY sort,id')] == before
        rows = {r['id']:dict(r) for r in conn.execute('SELECT * FROM proxy_groups')}
        assert rows[a['id']]['members_format'] == 'legacy'
        assert rows[a['id']]['members_v2'] == '[]'
        assert rows[b['id']]['members_format'] == 'typed-v2'
        assert len(list(conn.execute('SELECT * FROM catalog_issues WHERE origin=?',(f"group:{a['id']}",)))) == 1


def test_typed_backup_restores_identity_and_rejects_damaged_ref(client):
    from conftest import setup_admin, auth_headers
    from app import db
    from app.services import backups
    from copy import deepcopy
    h = auth_headers(setup_admin(client))
    a = client.post('/api/v1/groups',headers=h,json={'name':'a','proxies':['DIRECT']}).json()
    b = client.post('/api/v1/groups',headers=h,json={'name':'b','members_v2':[{'kind':'group','ref':str(a['id'])}]}).json()
    with db.connect() as conn:
        conn.execute('BEGIN')
        payload = backups.export_logical(conn)
    with db.tx() as conn:
        backups.restore_logical(conn,payload)
        assert conn.execute('SELECT members_v2 FROM proxy_groups WHERE id=?',(b['id'],)).fetchone()[0] == payload['tables']['proxy_groups'][1]['members_v2']
    damaged = deepcopy(payload)
    damaged['tables']['proxy_groups'][1]['members_v2'] = '[{"kind":"group","ref":"9999"}]'
    with pytest.raises(ValueError,match='backup_invalid_reference'):
        with db.tx() as conn:
            backups.restore_logical(conn,damaged)
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM proxy_groups').fetchone()[0] == 2


@pytest.mark.parametrize('mode', ['inline','provider'])
def test_source_rename_keeps_frozen_typed_proxy_and_suffix(client,mode):
    from v2_helpers import admin, import_source, proxy
    from app import db,security
    from app.services import node_catalog,source_nodes
    from app.routers.builds import collect_snapshot
    from app.compiler import render,validate
    import yaml
    h = admin(client)
    source = import_source(client,h,[proxy('old')])
    with db.tx() as conn:
        conn.execute('UPDATE sources SET mode=?,suffix=? WHERE id=?',(mode,'-fixture',source['id']))
        # Initial catalog emit_name was created before this fixture suffix change.
        conn.execute("UPDATE node_catalog SET emit_name='old-fixture' WHERE source_id=?",(source['id'],))
        entry = node_catalog.list_active_nodes(conn)[0]
        node_catalog.reconcile_source(conn,source['id'],[proxy('new')])
        conn.execute('UPDATE sources SET snapshot_enc=?,nodes_meta=? WHERE id=?',
                     (security.encrypt_text(source_nodes.dump([proxy('new')])), '[{"name":"new"}]',source['id']))
    group = client.post('/api/v1/groups',headers=h,json={'name':'fixed','use_sources':[],
        'members_v2':[{'kind':'node','ref':entry['node_uid']}]} )
    assert group.status_code == 201,group.text
    client.post('/api/v1/rules',headers=h,json={'type':'MATCH','target':'fixed'})
    with db.connect() as conn:
        snapshot = collect_snapshot(conn)
    assert not validate.validate_policy(snapshot)[0][0]
    target = {'engine':'stash','platform':'ios','name':'stash-ios','extra_yaml':''}
    output = yaml.safe_load(render.render_target(snapshot,target))
    fixed = next(n for n in output['proxies'] if n['name'] == 'old-fixture')
    assert fixed['password'] == 'example-test-password'
    assert next(g for g in output['proxy-groups'] if g['name'] == 'fixed')['proxies'] == ['old-fixture']
    assert not any(n['name'].endswith('-fixture-fixture') for n in output['proxies'])
    assert 'proxy-providers' not in output
    snapshot['sources'][0]['mode'] = mode
    snapshot['groups'][0]['use_sources'] = [source['name']]
    if mode == 'provider':
        with pytest.raises(ValueError,match='typed_provider_dynamic_conflict'):
            render.render_target(snapshot,target)
    else:
        output = yaml.safe_load(render.render_target(snapshot,target))
        assert len([n for n in output['proxies'] if n['name'] == 'old-fixture']) == 1
    from app.services import backups
    with db.connect() as conn:
        conn.execute('BEGIN')
        payload = backups.export_logical(conn)
    with db.tx() as conn:
        backups.restore_logical(conn,payload)
        assert conn.execute('SELECT emit_name FROM node_catalog').fetchone()[0] == 'old-fixture'



def test_backup_keeps_disabled_typed_identity_state(client):
    from v2_helpers import admin,make_local
    from app import db
    from app.services import backups
    h = admin(client)
    node = make_local(client,h)
    group = client.post('/api/v1/groups',headers=h,json={'name':'fixed','local_nodes':[node['id']],'proxies':['DIRECT']})
    assert group.status_code == 201,group.text
    assert client.patch(f"/api/v1/local-nodes/{node['id']}/enabled",headers=h,json={'enabled':False}).status_code == 200
    with db.connect() as conn:
        conn.execute('BEGIN')
        payload = backups.export_logical(conn)
    with db.tx() as conn:
        backups.restore_logical(conn,payload)
        assert conn.execute('SELECT enabled FROM node_catalog').fetchone()[0] == 0
        assert conn.execute('SELECT members_format FROM proxy_groups').fetchone()[0] == 'typed-v2'
def node(client,h,name):
    r=client.post('/api/v1/local-nodes',headers=h,json={'name':name,'protocol':'ss','server':'fixture.example','port':8388,'params':{'cipher':'aes-256-gcm','password':'fixture-only'}})
    assert r.status_code==201,r.text
    return r.json()

def test_batch_clear_local_nodes(client):
    h=auth_headers(setup_admin(client)); a=node(client,h,'a')
    group=client.post('/api/v1/groups',headers=h,json={'name':'group','proxies':['DIRECT'],'local_nodes':[a['id']],'use_sources':[]}).json()
    r=client.patch('/api/v1/groups/batch',headers=h,json={'ids':[group['id']],'local_nodes':[]}); assert r.status_code==200,r.text
    group=client.get('/api/v1/groups',headers=h).json()[0]
    assert group['members_v2']==[{'kind':'builtin','ref':'DIRECT'}],group

def test_batch_replace_local_nodes(client):
    h=auth_headers(setup_admin(client)); a=node(client,h,'a'); b=node(client,h,'b')
    group=client.post('/api/v1/groups',headers=h,json={'name':'group','proxies':['DIRECT'],'local_nodes':[a['id']],'use_sources':[]}).json()
    r=client.patch('/api/v1/groups/batch',headers=h,json={'ids':[group['id']],'local_nodes':[b['id']]}); assert r.status_code==200,r.text
    group=client.get('/api/v1/groups',headers=h).json()[0]
    assert group['proxies']==['DIRECT','b (本地)'],group

def test_batch_members_keep_unselected_categories_in_place(client):
    h = auth_headers(setup_admin(client))
    a, b, c = (node(client, h, name) for name in ('甲', '乙', '丙'))
    child = client.post('/api/v1/groups', headers=h, json={
        'name': '备用', 'proxies': ['DIRECT'], 'use_sources': [],
    }).json()
    r = client.post('/api/v1/groups', headers=h, json={
        'name': '测试组', 'type': 'fallback', 'use_sources': [],
        'proxies': ['DIRECT', a['display_name'], child['name'], b['display_name'], 'REJECT'],
    })
    assert r.status_code == 201, r.text
    gid = r.json()['id']

    def patch(expected, **changes):
        response = client.patch('/api/v1/groups/batch', headers=h, json={'ids': [gid], **changes})
        assert response.status_code == 200, response.text
        assert response.json()['updated'] == 1
        groups = client.get('/api/v1/groups/page', headers=h).json()['items']
        assert next(g for g in groups if g['id'] == gid)['proxies'] == expected

    patch(['DIRECT', b['display_name'], '备用', c['display_name'], 'REJECT'],
          local_nodes=[b['id'], c['id']])
    patch(['REJECT', b['display_name'], '备用', c['display_name'], 'DIRECT'],
          proxies=['REJECT', '备用', 'DIRECT'])
    patch([b['display_name'], c['display_name']], proxies=[])
    patch(['DIRECT'], proxies=['DIRECT'], local_nodes=[])


def test_batch_cannot_break_relay_chain(client):
    h = auth_headers(setup_admin(client))
    a, b = (node(client, h, name) for name in ('甲', '乙'))
    r = client.post('/api/v1/groups', headers=h, json={
        'name': '接力', 'type': 'relay', 'use_sources': [],
        'proxies': [a['display_name'], b['display_name']],
    })
    assert r.status_code == 201, r.text
    group = r.json()
    response = client.patch('/api/v1/groups/batch', headers=h, json={
        'ids': [group['id']], 'local_nodes': [], 'hidden': True,
    })
    assert response.status_code == 200, response.text
    assert response.json()['updated'] == 0
    assert response.json()['skipped'][0]['id'] == group['id']
    assert client.get('/api/v1/groups', headers=h).json()[0] == group


def test_hidden_rule_build_guard(client):
    from app.compiler.render import render_target
    from app.compiler.validate import validate_policy
    h=auth_headers(setup_admin(client))
    g=client.post('/api/v1/groups',headers=h,json={'name':'hidden','proxies':['DIRECT'],'hidden':True}).json()
    rejected=client.post('/api/v1/rules',headers=h,json={'type':'MATCH','target_ref_v2':{'kind':'group','ref':str(g['id'])}})
    assert rejected.status_code==400
    assert rejected.json()['detail']=='reference_hidden'

    # 旧数据/历史快照仍要有构建期防线，不能只依赖写入期校验。
    snapshot={'sources':[],'local_nodes':[],'node_catalog':[],'rule_providers':[],'variants':[{'id':0,'name':'默认','enabled':True}],
        'groups':[{'id':g['id'],'variant_id':0,'name':'hidden','type':'select','hidden':True,'proxies':['DIRECT'],'local_nodes':[],'members_format':'legacy'}],
        'rules':[{'variant_id':0,'type':'MATCH','value':'','target':'hidden','enabled':True,'targets':['*'],'devices':['*']}]}
    assert validate_policy(snapshot)[0][0]
    try:
        render_target(snapshot,{'name':'stash-ios','engine':'stash','platform':'ios','extra_yaml':''})
    except ValueError as exc:
        assert str(exc)=='reference_hidden'
    else:
        raise AssertionError('hidden render was allowed')

def test_pure_snapshot_no_db(client,monkeypatch):
    from app.services.node_refs import resolve_snapshot
    from app import db
    monkeypatch.setattr(db,'connect',lambda:pytest.fail('live DB read'))
    s={'groups':[{'id':1,'variant_id':0,'name':'a','members_format':'typed-v2','members_v2':[{'kind':'builtin','ref':'DIRECT'}]}],'rules':[{'variant_id':0,'target_ref_v2':{'kind':'group','ref':'1'}}]}
    assert resolve_snapshot(s)['rules'][0]['target']=='a'

def test_unknown_format_backup_fails(client):
    from app import db
    from app.services import backups
    h=auth_headers(setup_admin(client))
    client.post('/api/v1/groups',headers=h,json={'name':'a','proxies':['DIRECT']})
    with db.connect() as conn:
        conn.execute('BEGIN'); payload=backups.export_logical(conn)
    row=payload['tables']['proxy_groups'][0]
    row['members_format']='typed-v3'; row['members_v2']='[{"kind":"group","ref":"9999"}]'
    with db.tx() as conn:
        with pytest.raises(ValueError,match='backup_invalid'):
            backups.restore_logical(conn,payload)
