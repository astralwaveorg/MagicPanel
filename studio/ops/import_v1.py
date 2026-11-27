"""One-shot import run with the old image, read-only legacy data and writable v2 store."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from urllib.parse import unquote, urlsplit

from studio import store as s, compiler as comp

def identity(prefix,text):
    return prefix+hashlib.sha256(text.encode()).hexdigest()[:20]

def migrate(legacy,destination):
    with tempfile.TemporaryDirectory() as tmp:
        scratch=Path(tmp)
        os.environ["MAGICPANEL_DATA_DIR"]=tmp
        from app import security
        from app.services.config_resolution import apply_device_overlay
        from app.compiler.render import dedupe_rules
        from app.routers.feed import _device_overlay
        shutil.copyfile(legacy/"secret.key", scratch/"secret.key")
        (scratch/"secret.key").chmod(0o600)
        src=sqlite3.connect(f"file:{legacy}/magicpanel.db?mode=ro",uri=True)
        c=sqlite3.connect(scratch/"snapshot.db")
        try:
            src.backup(c)
        finally:
            src.close()
        c.row_factory=sqlite3.Row
        live=c.execute("SELECT id FROM builds WHERE status='PRODUCTION' ORDER BY status_updated_at DESC LIMIT 1").fetchone()
        if not live:
            raise ValueError("没有旧版生产构建")
        root=legacy/"builds"/str(live[0])
        def artifact(name):
            if not name or "/" in name or name in (".",".."):
                raise ValueError("非法产物名")
            return root/(name+".yaml")
        ws={"templates":{},"devices":{},"rules":{},"resources":{},"sources":{},"origin_build":live[0]}
        for row in c.execute("SELECT * FROM users WHERE role='admin'"):
            destination.execute("INSERT INTO users VALUES(?,?,?)",(row["username"],row["salt"],row["password_hash"]))
        if not destination.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise ValueError("没有可迁移的管理员")
        for row in c.execute("SELECT * FROM rule_providers WHERE content!=''"):
            data=base64.b64decode(row['content'],validate=True) if row["format"]=="mrs" else row["content"].encode()
            key=s.put_blob(destination,data)
            ws["resources"][row["name"]]={"blob":key,"format":row["format"],"behavior":row["behavior"],"url":row["url"],"kind":row["kind"]}
        for row in c.execute("SELECT * FROM sources WHERE enabled=1"):
            ws["sources"][str(row["id"])]={"name":row["name"],"url":security.decrypt_text(row["url_enc"]) if row["url_enc"] else "",
                "ua":row["ua"],"headers":json.loads(security.decrypt_text(row["headers_enc"]) or "[]") if row["headers_enc"] else [],
                "interval":row["interval"],"filter":row["filter"],"snapshot_count":row["node_count"],"managed":False}
        def template(name,engine,platform,raw):
            cfg=comp.load(dedupe_rules(raw))
            order=[]
            for line in cfg.pop("rules"):
                k=identity("r",line)
                if ws["rules"].setdefault(k,line)!=line:
                    raise ValueError("规则标识冲突")
                order.append(k)
            for sect in ("rule-providers","proxy-providers"):
                for pn,v in cfg.get(sect,{}).items():
                    if v.get("type","http")!="http":
                        continue
                    if not v.get("url","").startswith("{FEED}/res/"):
                        raise ValueError("发现未固定的外部资源："+pn)
                    key=unquote(v["url"].split("/",3)[-1])
                    if sect!="rule-providers":
                        raise ValueError("此迁移需要先冻结独立节点 provider："+key)
                    v["url"]="studio:"+ws["resources"][key]["blob"]
            return dict(name=name,engine=engine,platform=platform,order=order,base=cfg)
        for t in c.execute("SELECT * FROM targets"):
            tid="t"+str(t["id"])
            f=artifact(t["name"])
            if not f.is_file():
                raise ValueError("缺少平台产物："+t["name"])
            raw=f.read_text()
            ws["templates"][tid]=template(t["name"],t["engine"],t["platform"],raw)
            for d in c.execute("SELECT * FROM devices WHERE target_id=?",(t["id"],)):
                if d["env"]!="production":
                    raise ValueError("测试设备不可静默切生产："+d["name"])
                did="d"+str(d["id"])
                own=artifact(d["name"])
                base=own.read_text() if own.is_file() else raw
                overlay=_device_overlay(c,d)
                if overlay: base=apply_device_overlay(base,overlay)
                other=template(t["name"],t["engine"],t["platform"],base)
                bind=tid
                if other!=ws["templates"][tid]:
                    bind=tid+"-"+did
                    other["name"]=d["name"]+" · 专属"
                    ws["templates"][bind]=other
                ws["devices"][did]={"name":d["name"],"template":bind,"enabled":True}
                s.new_token(destination,did)
        destination.execute("INSERT INTO draft VALUES(1,1,?)",(s.seal(s.encode(ws)),))
        release=comp.publish(destination,"迁移",1)
        c.close()
        return dict(old_build=live[0],release=release,templates=len(ws["templates"]),devices=len(ws["devices"]),resources=len(ws["resources"]),rules=len(ws["rules"]))
if __name__=="__main__":
    os.umask(0o077)
    s.init()
    with s.tx(True) as dest:
        if dest.execute("SELECT 1 FROM draft").fetchone():
            print("已有工作区，跳过初始化")
        else:
            print(json.dumps(migrate(Path("/legacy"),dest),ensure_ascii=False))
