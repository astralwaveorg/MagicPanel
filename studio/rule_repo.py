"""Manage one public rule directory. Only an explicit commit can write to GitHub."""
import base64
import difflib
import hashlib
import http.client
import json
import re
from urllib.parse import urlencode
from . import compiler as cc, store as s

REPO="astralwaveorg/magic-sets"
BRANCH="main"
BASE="/repos/"+REPO
NAME=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,89}\.ya?ml\Z")
SHA=re.compile(r"[0-9a-f]{40}\Z")
LIMIT=300_000

def filename(value):
    if not isinstance(value,str) or not NAME.fullmatch(value):raise ValueError("文件名须为 rule/ 下的 YAML 文件，不含目录")
    return value

def github(method,path,body=None,token=""):
    conn=http.client.HTTPSConnection("api.github.com",timeout=12)
    headers={"User-Agent":"MagicPanel-Studio","Accept":"application/vnd.github+json","Content-Type":"application/json"}
    if token:
        if not isinstance(token,str) or not re.fullmatch(r"[A-Za-z0-9_]{12,255}",token):raise ValueError("GitHub 令牌格式无效")
        headers["Authorization"]="Bearer "+token
    try:
        conn.request(method,BASE+path,body=json.dumps(body).encode() if body is not None else None,headers=headers)
        res=conn.getresponse();raw=res.read(1_200_001)
        if res.status in (409,422):raise ValueError("GitHub 未接受提交；请刷新文件、核对差异后重试")
        if not 200<=res.status<300:raise ValueError(f"GitHub 返回 HTTP {res.status}，请检查文件、权限或请求额度")
        if len(raw)>1_200_000:raise ValueError("GitHub 返回内容过大")
        return json.loads(raw)
    except (OSError,http.client.HTTPException,json.JSONDecodeError):
        raise ValueError("GitHub 请求未完成；请刷新查看仓库状态") from None
    finally:conn.close()

def catalog():
    files=github("GET","/contents/rule?ref="+BRANCH)
    return {"repo":REPO,"branch":BRANCH,"files":[x["name"] for x in files if x.get("type")=="file" and NAME.fullmatch(x["name"])]}

def file(name):
    name=filename(name);r=github("GET","/contents/rule/"+name+"?ref="+BRANCH)
    if r.get("type")!="file" or r.get("encoding")!="base64" or not 0<r.get("size",0)<=LIMIT:raise ValueError("不是可编辑的 YAML 文件")
    raw=base64.b64decode(r["content"]);sha=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    if sha!=r["sha"]:raise ValueError("GitHub 文件校验失败")
    return {"name":name,"sha":sha,"content":raw.decode("utf-8-sig")}

def history(name):
    entries=github("GET","/commits?"+urlencode({"path":"rule/"+filename(name),"sha":BRANCH,"per_page":6}))
    return [{"sha":x["sha"],"message":x["commit"]["message"].split("\n",1)[0][:140]} for x in entries]

def validate(text):
    if not isinstance(text,str) or not 0<len(text.encode())<=LIMIT:raise ValueError("规则文件为空或超过 300 KB")
    doc=cc.load(text)
    if not isinstance(doc,dict) or set(doc)!={"payload"}:raise ValueError("规则文件只能包含 payload")
    lines=doc["payload"]
    if not isinstance(lines,list) or not lines or len(lines)>20000 or not all(isinstance(l,str) and l.strip() and len(l)<=1500 and not any(c in l for c in "\r\n\x00") for l in lines):raise ValueError("payload 需要非空的单行规则列表")
    return lines

def review(p):
    name=filename(p["name"]);content=p["content"];validate(content)
    sha=p.get("sha","")
    if sha and not SHA.fullmatch(sha):raise ValueError("文件版本无效")
    old=file(name) if sha else {"content":"","sha":""}
    if old["sha"]!=sha:raise ValueError("文件已在 GitHub 上变更，请重新打开")
    delta=list(difflib.unified_diff(old["content"].splitlines(),content.splitlines(),fromfile="GitHub",tofile="待提交",lineterm=""))
    if not delta and old["content"]==content:raise ValueError("没有正文变化")
    return {"diff":"\n".join(delta[:600]) or "文件末尾换行变更","truncated":len(delta)>600,
            "digest":s.digest(s.encode([name,sha,content]))}

def commit(p):
    result=review(p)
    if p.get("digest")!=result["digest"]:raise ValueError("正文或文件版本已变化，请重新预览差异")
    message=p.get("message","").strip()
    if not 1<=len(message)<=180 or not p.get("token"):raise ValueError("请填写提交说明和该仓库的写入令牌")
    data={"content":base64.b64encode(p["content"].encode()).decode(),"branch":BRANCH,"message":message}
    if p.get("sha"):data["sha"]=p["sha"]
    result=github("PUT","/contents/rule/"+filename(p["name"]),data,p["token"])
    return {"commit":result["commit"]["sha"]}

def apply(c,user,p,source):
    name=filename(p["name"])
    if source["sha"]!=p.get("sha"):raise ValueError("GitHub 文件已变化，请再核对一次")
    validate(source["content"])
    rev,w=s.workspace(c)
    if rev!=p.get("revision"):raise ValueError("草稿已变化，请刷新页面")
    key=name.rsplit(".",1)[0];beh=p.get("behavior");t=w["templates"].get(p.get("template"))
    if not t or beh not in ("domain","ipcidr","classical"):raise ValueError("请选择模板和规则类型")
    current=w["resources"].get(key)
    if current and (current.get("kind")!="repo" or current.get("repo_file",name)!=name or current.get("behavior")!=beh or current.get("format")!="yaml"):
        raise ValueError("已有同名资源，来源或类型不一致，未覆盖")
    cid=s.put_blob(c,source["content"].encode());spec={"behavior":beh,"format":"yaml","url":"studio:"+cid}
    # Use the same output validation as the compiler, before mutating the draft.
    from . import apple
    for engine in ("surge","shadowrocket"):apple.resource(c,spec,engine)
    refs=t["base"].setdefault("rule-providers",{})
    refs.setdefault(key,dict(type="http",path="./rules/"+key+".yaml",interval=86400,**spec))
    for target in w["templates"].values():
        entry=target["base"].get("rule-providers",{}).get(key)
        if entry:entry.update(spec)
    w["resources"][key]={**(current or {}),"blob":cid,"kind":"repo","repo_file":name,"repo_sha":source["sha"],"behavior":beh,"format":"yaml","url":"","managed":False}
    c.execute("UPDATE draft SET body=?,revision=revision+1 WHERE id=1",(s.encode_workspace(w),))
    s.event(c,user,"从 magic-sets 应用 "+name+" @ "+source["sha"][:9])
    return {"revision":rev+1,"resource":key}
