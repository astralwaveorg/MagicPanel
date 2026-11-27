import time
import json
import threading
from . import store as s, service, compiler as cc, assistant as ai, fetch
LOCK=threading.Lock()

def refresh(kind,key,actor):
    if not LOCK.acquire(blocking=False):raise ValueError("已有刷新任务在运行")
    try:
        with s.tx() as c:
            revision,w=s.workspace(c)
            table="sources" if kind=="source" else "resources"
            row=w[table][key]
            url=row.get("url")
            if not url:raise ValueError("此项没有远程地址")
            if kind=="source" and not (row.get("template") and row.get("group")):raise ValueError("请先选择目标模板与策略组")
        try:body=fetch.get(url,row.get("ua") or "MagicPanel-Studio",row.get("headers") or [])
        except Exception:raise ValueError("远程来源不可用，已保留上次快照") from None
        if kind=="source":
            t=w["templates"][row["template"]]
            targets=[v for v in w["templates"].values() if v["policy"]==t["policy"]] if row.get("scope")=="policy" else [t]
            text=fetch.node_text(body);variants={e:ai.convert(text,e) for e in {v["engine"] for v in targets}}
            import copy
            occupied=set()
            for tmp in targets:
                nodes=copy.deepcopy(variants[tmp["engine"]])
                if row.get("snapshot_count",0)>20 and len(nodes)*3<row["snapshot_count"]:raise ValueError("节点数量大幅减少，保留原快照")
                group=next((g for g in tmp["base"]["proxy-groups"] if g["name"]==row["group"]),None)
                if group is None:raise ValueError("绑定的组已删除")
                prev=set(row.get("owned",[]))
                for n in nodes:n["name"]=row["name"]+" / "+service.label(n["name"])
                names=[n["name"] for n in nodes];occupied.update(names)
                tmp["base"]["proxies"]=[n for n in tmp["base"].get("proxies",[]) if n["name"] not in prev]+nodes
                for g in tmp["base"]["proxy-groups"]:
                    if "proxies" in g:g["proxies"]=[n for n in g["proxies"] if n not in prev-set(names)]
                group["proxies"]=[n for n in group.get("proxies",[]) if n not in prev]+names
                cc.compile_template(w,tmp)
            row.update(owned=sorted(occupied),snapshot_count=len(occupied))
        else:
            if row["format"]=="mrs":
                if not body.startswith(b"MRS") and not body.startswith(bytes.fromhex("28b52ffd")):raise ValueError("响应不符合 MRS 格式")
            elif row["format"]=="yaml":
                doc=cc.load(body)
                if not isinstance(doc,dict) or not doc.get("payload"):raise ValueError("响应不含有效规则")
            else:raise ValueError("不支持此规则资源格式")
        with s.tx(True) as c:
            oldrev,old=s.workspace(c)
            if oldrev!=revision:raise ValueError("刷新期间草稿已变化，请重试")
            if kind!="source":
                cid=s.put_blob(c,body);row["blob"]=cid
                for t in w["templates"].values():
                    e=t["base"].get("rule-providers",{}).get(key)
                    if e:e["url"]="studio:"+cid
            changed=old!=w
            if changed:c.execute("UPDATE draft SET revision=revision+1,body=?",(s.encode_workspace(w),));s.event(c,actor,"更新来源快照")
            c.execute("INSERT OR REPLACE INTO checks VALUES(?,?,?,?)",(kind,key,int(time.time()),""))
        return {"changed":changed}
    finally:LOCK.release()

def due():
    with s.tx() as c:
        _,w=s.workspace(c)
        checks={(r[0],r[1]):r[2] for r in c.execute("SELECT kind,key,at FROM checks")}
    now=int(time.time())
    for kind,rows in [("source",w["sources"]),("resource",w["resources"])]:
        for k,r in rows.items():
            if r.get("managed") and now-checks.get((kind,k),0)>=max(300,int(r.get("interval",86400))):
                try:refresh(kind,k,"自动刷新")
                except Exception:
                    with s.tx(True) as c:c.execute("INSERT OR REPLACE INTO checks VALUES(?,?,?,?)",(kind,k,now,"刷新未完成，沿用已有快照"))
                return
