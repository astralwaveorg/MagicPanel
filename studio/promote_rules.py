"""Re-render an unchanged released draft. Keep the former artifact available for rollback."""
import argparse
import json
from . import compiler as cc, store as s

def promote(c,release,revision):
    current=c.execute("SELECT r.id,r.revision,d.revision FROM live JOIN releases r ON r.id=live.release CROSS JOIN draft d").fetchone()
    if tuple(current or ())!=(release,revision,revision):raise ValueError("生效版本或草稿已变化，未发布")
    def artifacts(rid):
        return json.loads(s.unseal(c.execute("SELECT body FROM client_catalogs WHERE release=?",(rid,)).fetchone()[0]))
    before=artifacts(release)
    c.execute("UPDATE draft SET revision=revision+1")
    rid=cc.publish(c,"更新客户端规则格式",revision+1);after=artifacts(rid)
    for pid,p in before["deliveryProfiles"].items():
        for eng,t in p["adapters"].items():
            t2=after["deliveryProfiles"][pid]["adapters"][eng]
            for net,old in before["targets"][t].items():
                new=after["targets"][t2][net]
                if not old.get("error") and new.get("error"):raise ValueError(f"{pid}/{eng}/{net} 不可用，未发布")
                if eng in ("stash","mihomo") and old.get("config")!=new.get("config"):raise ValueError("基础配置发生变化，未发布")
    return rid

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--expected-release",required=True,type=int);p.add_argument("--expected-revision",required=True,type=int);args=p.parse_args()
    with s.tx(True) as c:print("已发布 #"+str(promote(c,args.expected_release,args.expected_revision)))
