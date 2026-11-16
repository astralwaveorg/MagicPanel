"""默认方案收敛脚本的只读数据合同。"""
import json


def test_unified_variant_script_updates_default_and_stages_legacy(client):
    import sys
    from pathlib import Path
    from app import db
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.configure_unified_variant import GROUP_MEMBERS, apply_changes
    with db.tx() as conn:
        now = db.now()
        for index, name in enumerate(GROUP_MEMBERS):
            conn.execute("INSERT INTO proxy_groups(variant_id,name,type,sort,hidden,use_sources,"
                         "local_nodes,proxies,url,interval,timeout,tolerance,lazy,strategy,"
                         "targets,devices,local_first,created_at,updated_at) VALUES("
                         "0,?,'select',?,0,'[]','[]','[]','',600,8000,100,1,'','[]','[]',0,?,?)",
                         (name, index + 1, now, now))
        conn.execute("INSERT INTO variants(id,name,note,enabled,is_system,sort,created_at,updated_at) "
                     "VALUES(1,'自建美日','fixture',1,0,1,?,?)", (now, now))
        apply_changes(conn)
        google = db.one(conn, "SELECT proxies FROM proxy_groups "
                              "WHERE variant_id=0 AND name='🔍 谷歌服务'")
        ai = db.one(conn, "SELECT proxies FROM proxy_groups "
                          "WHERE variant_id=0 AND name='🧠 人工智能'")
        legacy = db.one(conn, 'SELECT enabled,note FROM variants WHERE id=1')
    assert json.loads(google['proxies'])[0] == '🇺🇸 美国NTT自动'
    assert json.loads(google['proxies']).index('🇸🇬 新加坡自动') < \
        json.loads(google['proxies']).index('🇯🇵 日本机房')
    assert json.loads(ai['proxies']).index('🇸🇬 新加坡自动') < \
        json.loads(ai['proxies']).index('🇯🇵 日本机房')
    assert GROUP_MEMBERS.keys() <= {
        '🔍 谷歌服务', '🧠 人工智能', '🇯🇵日本', '🎵 TikTok',
        '💻 开发工具', '👥 海外社交'}
    assert legacy['enabled'] == 0
