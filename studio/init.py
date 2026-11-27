"""Create a new installation without access to v1. Read password via stdin, never argv."""
import argparse
import hashlib
import os
import secrets
import sys
from . import compiler as cc,store as s

def initialize(c,user,password):
    if c.execute("SELECT 1 FROM draft").fetchone():raise ValueError("已有工作区，拒绝重新初始化")
    if not user.strip() or len(password)<14:raise ValueError("必须指定管理员名与至少 14 个字符的密码")
    salt=secrets.token_hex(16)
    verifier=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),600000).hex()
    c.execute("INSERT INTO users VALUES(?,?,?)",(user,salt,verifier))
    w={"templates":{},"devices":{},"resources":{},"sources":{},"rules":{"r-final":"MATCH,默认出口"}}
    from .platforms import fresh
    fresh(w)
    c.execute("INSERT INTO draft VALUES(1,1,?)",(s.encode_workspace(w),))
    cc.publish(c,user,1)
    c.execute("UPDATE automation SET enabled=1")
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--admin",required=True)
    args=parser.parse_args()
    os.umask(0o077);s.init()
    with s.tx(True) as c:initialize(c,args.admin,sys.stdin.readline().rstrip("\n"))
    print("工作区已初始化 · 5 份平台模板 · #1")
