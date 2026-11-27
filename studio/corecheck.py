"""Validate an offline candidate against the pinned deployment core and frozen providers."""
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from . import store as s

def verify(c,cfg,text):
    from .compiler import dump,load,CID
    root=Path(os.getenv("STUDIO_CORE_DIR","/opt/studio-core"))
    binary=root/"mihomo"
    if not binary.is_file():
        if os.environ.get("STUDIO_REQUIRE_CORE")=="1":raise ValueError("缺少指定的 Mihomo 核心")
        return
    key=hashlib.sha256((s.digest(text.encode())+str(binary.stat().st_mtime_ns)+str(binary.stat().st_size)).encode()).hexdigest()
    if c.execute("SELECT 1 FROM corechecks WHERE key=?",(key,)).fetchone():return
    with tempfile.TemporaryDirectory(prefix="studio-core-") as tmp:
        dst=Path(tmp)
        for db in ("geoip.dat","geosite.dat","country.mmdb"):
            if (root/db).is_file(): (dst/db).symlink_to(root/db)
        local=load(text)
        for section in ("rule-providers","proxy-providers"):
            for n,item in local.get(section,{}).items():
                m=CID.fullmatch(item.get("url",""))
                if m:
                    rel="res/"+m[1]+"."+item.get("format","yaml")
                    f=dst/rel;f.parent.mkdir(exist_ok=True)
                    f.write_bytes(s.read_blob(c,m[1]))
                    item.update(url="http://127.0.0.1:9/unused",path=rel)
        f=dst/"config.yaml";f.write_text(dump(local).replace("{FEED_HOST}","v2.magichub.top"))
        try:
            result=subprocess.run([str(binary),"-d",tmp,"-f",str(f),"-t"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
        except (OSError,subprocess.TimeoutExpired):raise ValueError("核心校验未完成") from None
        if result.returncode:raise ValueError("Mihomo 核心拒绝候选配置")
    c.execute("INSERT OR IGNORE INTO corechecks VALUES(?)",(key,))
