"""Only the v2 store is accessed. Validate and publish as one transaction; prior release remains readable."""
from studio import compiler as cc,store as s,platforms
s.init()
with s.tx(True) as c:
    rev,w=s.workspace(c)
    if w.get("profiles"):
        print("平台模板已就绪",len(w["profiles"]))
    else:
        outcome=platforms.from_baseline(w)
        c.execute("UPDATE draft SET revision=?,body=?",(rev+1,s.encode_workspace(w)))
        release=cc.publish(c,"平台模板初始化",rev+1)
        c.execute("UPDATE automation SET enabled=1,failed_revision=NULL,error=''")
        s.event(c,"系统","启用五个平台模板，保留原设备产物归档")
        print({**outcome,"release":release})

    from studio import delivery
    delivery.upgrade(c)
