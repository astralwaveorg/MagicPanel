"""自主维护：依赖文件库的克隆、文件管理、提交与规则集合同步。

用本地 git 仓库当被管理的仓库，不依赖网络。
"""
import subprocess

import pytest
from conftest import auth_headers, setup_admin


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@local",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def origin_repo(tmp_path):
    """造一个本地仓库：有 rule/ 目录与一个规则集合文件。"""
    repo = tmp_path / "origin"
    (repo / "rule").mkdir(parents=True)
    (repo / "rule" / "demo.yaml").write_text(
        "# 名称: demo\n# behavior: domain\n# 条目: 1\n"
        "# 说明: 演示集合\npayload:\n  - +.example.com\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("测试仓库\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _configure(client, h, url, **extra):
    body = {"enabled": True, "url": str(url), "branch": "main", "auth": "none"}
    body.update(extra)
    r = client.put("/api/v1/deps/settings", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_deps_flow_clone_files_commit_sync(client, origin_repo):
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    # 未配置：状态条显示未配置
    st = client.get("/api/v1/deps/status", headers=h).json()
    assert st["configured"] is False
    assert st["cloned"] is False

    _configure(client, h, origin_repo)
    st = client.get("/api/v1/deps/status", headers=h).json()
    assert st["configured"] is True
    assert st["cloned"] is False

    # 克隆
    r = client.post("/api/v1/deps/clone", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["commit"]
    st = client.get("/api/v1/deps/status", headers=h).json()
    assert st["cloned"] is True

    # 文件清单：rule/demo.yaml 与 README.md 都在，.git 不在
    files = client.get("/api/v1/deps/files", headers=h).json()["files"]
    paths = {f["path"] for f in files}
    assert "rule/demo.yaml" in paths
    assert "README.md" in paths
    assert not any(p.startswith(".git/") for p in paths)

    # 读写文件
    r = client.get("/api/v1/deps/file?path=rule%2Fdemo.yaml", headers=h)
    assert r.status_code == 200, r.text
    assert "payload:" in r.json()["content"]
    r = client.put("/api/v1/deps/file", headers=h, json={
        "path": "rule/other.yaml",
        "content": "# 名称: other\n# behavior: domain\n# 条目: 1\npayload:\n  - +.other.com\n",
    })
    assert r.status_code == 200, r.text
    files = client.get("/api/v1/deps/files", headers=h).json()["files"]
    assert any(f["path"] == "rule/other.yaml" for f in files)

    # 路径穿越要拦住
    r = client.put("/api/v1/deps/file", headers=h, json={
        "path": "../逃逸.yaml", "content": "x: 1"})
    assert r.status_code == 400

    # 提交
    r = client.post("/api/v1/deps/commit", headers=h, json={"message": "加一个集合"})
    assert r.status_code == 200, r.text
    assert r.json()["commit"]

    # 同步：仓库里的 rule/*.yaml 变成规则来源（kind='repo'）
    r = client.post("/api/v1/deps/sync", headers=h)
    assert r.status_code == 200, r.text
    providers = client.get("/api/v1/rule-providers", headers=h).json()
    names = {p["name"] for p in providers}
    assert "demo" in names and "other" in names
    demo = [p for p in providers if p["name"] == "demo"][0]
    assert demo["kind"] == "repo"
    assert demo["repo_path"] == "rule/demo.yaml"
    assert demo["behavior"] == "domain"
    content = client.get(
        f"/api/v1/rule-providers/{demo['id']}/content", headers=h).json()["content"]
    assert "+.example.com" in content


def test_deps_exclude_paths_and_settings(client, origin_repo):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _configure(client, h, origin_repo, exclude_paths=".git,.github,*.md")
    assert client.post("/api/v1/deps/clone", headers=h).status_code == 200

    files = client.get("/api/v1/deps/files", headers=h).json()["files"]
    paths = {f["path"] for f in files}
    assert "rule/demo.yaml" in paths
    assert "README.md" not in paths          # 被 *.md 排除
    # 被排除的路径也不能直接读写
    assert client.get("/api/v1/deps/file?path=README.md", headers=h).status_code == 400

    # 私钥与 token 只写不读
    r = client.put("/api/v1/deps/settings", headers=h, json={
        "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nxxx\n"})
    assert r.status_code == 200, r.text
    s = client.get("/api/v1/deps/settings", headers=h).json()
    assert s["has_private_key"] is True
    assert "private_key" not in s
    assert "xxx" not in str(s)


def test_deps_sync_creates_source_only_when_enabled(client, origin_repo):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _configure(client, h, origin_repo, auto_create_rule_sources=False)
    assert client.post("/api/v1/deps/clone", headers=h).status_code == 200
    r = client.post("/api/v1/deps/sync", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 0
    assert client.get("/api/v1/rule-providers", headers=h).json() == []
