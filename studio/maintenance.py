"""Private daily recovery set: paired encryption key + SQLite online backup."""
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from . import store as s

def backup():
    base=s.ROOT/"backups";base.mkdir(mode=0o700,exist_ok=True)
    target=base/time.strftime("%Y-%m-%d",time.gmtime())
    if target.exists():return
    tmp=Path(tempfile.mkdtemp(prefix=".partial-",dir=base))
    try:
        shutil.copyfile(s.ROOT/"master.key",tmp/"master.key");(tmp/"master.key").chmod(0o600)
        with sqlite3.connect(s.DB) as src,sqlite3.connect(tmp/"studio.sqlite3") as dest:
            src.backup(dest)
            if dest.execute("PRAGMA quick_check").fetchone()[0]!="ok":raise RuntimeError("备份校验失败")
        (tmp/"studio.sqlite3").chmod(0o600)
        tmp.rename(target)
    finally:
        if tmp.exists():shutil.rmtree(tmp)
    for old in sorted(base.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"))[:-14]:
        if old.is_dir() and not old.is_symlink():shutil.rmtree(old)
