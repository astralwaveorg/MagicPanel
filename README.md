# MagicPanel

一份策略，编译成各家客户端能直接用的订阅配置。

MagicPanel 是个自托管的代理订阅配置服务：把机场订阅、规则集、分流规则、策略组、节点来源统一维护在一处，按客户端（Stash / Mihomo）编译成产物，发布出去，每台设备拿一个固定地址自动更新。

**文档**：[使用文档](docs/使用文档.md) ·
[开发文档](docs/开发文档.md) ·
[配置文档](docs/配置文档.md) ·
[部署文档](docs/deployment/1Panel-Docker-部署.md) ·
[在线阅读](https://astralwaveorg.github.io/MagicPanel/)（推 main 自动发布，配置见 `.github/workflows/pages.yml`）

## 它是什么

- **一个容器**：FastAPI + SQLite，前端 Vue3 编译进镜像，运行时只管数据目录。
- **两个入口**：根路径 `/` 是门户页（输 4 位 PIN 就能看订阅地址），`/admin` 是管理端。
- **一条流水线**：抓取上游 → 编译产物 → 校验 → 发布 → 设备按地址拉取。
- **一份数据**：多位维护者共享同一套策略，账号只决定谁能改。

## 它不做什么

- 不开发代理内核，不做流量中转。
- 不提供旁路由，不做透明代理。
- 不做公网 SaaS：设计前提是自托管、数据不出门。

## 有什么

| 页面 | 干什么 |
| --- | --- |
| 系统状态 | 当前生效的版本、构建产物、来源与节点可用性、测速链路是否真的直连 |
| 节点来源 | 机场订阅抓取与快照留存；本地单节点（自建、家宽、机房、专线）手动录入 |
| 规则来源 | 远程或内联的规则集，独立抓取与验收 |
| 策略组 | select / url-test / fallback / load-balance / relay，按来源聚合节点 |
| 分流规则 | 域名、IP、进程、规则集，按序匹配；可限定引擎平台或具体设备 |
| 引擎平台 | 引擎 + 平台（Stash-macOS、Mihomo-Windows……），一套客户端对应一个 |
| 产物配置 | 产物顶层键分三层：引擎默认配置 → 引擎平台配置 → 设备独立配置 |
| 功能模块 | 可复用的 YAML 片段（Stash 磁贴、Mihomo TUN、DNS 策略、脚本改写……） |
| 设备管理 | 每台设备一个固定订阅地址，一个订阅环境 |
| 构建发布 | 产物快照、校验结果、发布与回滚、版本对比 |
| 自动发布 | 定时抓取、测速，策略有变化就自动构建并发布 |
| 审计日志 | 谁在什么时候改了什么 |
| 设置 | 账号与 PIN、头像、备份与恢复、WebDAV、测速核心 |

每个页面的按钮、字段和边界条件都写在 [使用文档](docs/使用文档.md) 里。

## 快速开始

### Docker（推荐）

```bash
git clone git@github.com:astralwaveorg/MagicPanel.git /opt/magicpanel
cd /opt/magicpanel
docker compose up -d --build
docker compose ps          # STATUS 应为 healthy
```

编排文件把数据目录 `./data` 挂到容器 `/app/data`，里面是数据库、主密钥、构建产物和测速核心，**记得纳入备份**。容器只监听 `127.0.0.1:47100`，对外由反向代理接管 TLS。

完整步骤（1Panel、反向代理、备份、升级）见 [部署文档](docs/deployment/1Panel-Docker-部署.md)。

### 裸机运行

```bash
npm install && npm run build                  # 前端产物要编进包里
./scripts/package.sh                          # 产出 dist/magicpanel-<时间戳>.tar.gz
tar xzf dist/magicpanel-*.tar.gz && cd magicpanel
./run.sh                                      # 自动建虚拟环境装依赖，监听 127.0.0.1:8000
```

生产环境请放在反向代理之后启用 HTTPS，并在「设置」里填对外基础地址。

### 本地开发

```bash
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
npm install
npm run dev        # 前端 127.0.0.1:7100，API 127.0.0.1:8000，已代理 /api 与 /feed
```

打开 <http://127.0.0.1:7100/admin>，第一次访问会引导创建第一位维护者账号。

## 订阅长什么样

设备拉到的 `config.yaml` 由四层合并而成，优先级由低到高：

1. **产物配置** —— 引擎默认配置 → 引擎平台配置 → 设备独立配置，三层各自只存改动过的部分
2. **结构化内容** —— 节点、策略组、分流规则，由各自页面维护，任何配置层都不许覆盖
3. **功能模块** —— 启用的 YAML 片段，与引擎匹配后深度合并（字典递归、列表追加）
4. **平台扩展** —— 单个引擎平台自己的片段，最后应用

订阅地址带令牌，令牌可随时轮换；旧地址立即失效，客户端换新地址即可。

## 仓库结构

```text
server/app/            后端
  routers/              HTTP 接口（按业务分文件）
  services/             抓取、测速、发布、调度、备份
  compiler/             产物编译与校验
  db.py                 表结构与迁移
src/                    前端（Vue3 + Element Plus），views/ 里一个页面对应一个文件
scripts/                部署、备份、自检脚本
docs/                   文档
android/                管理端的安卓壳
official-example/       官方配置样例，核对引擎默认配置用
```

## 开发与发布

```bash
cd server && ../.venv/bin/python -m pytest tests -q     # 后端测试
npm run build                                            # 前端产物（输出到 server/app/static）
```

推到 NAS：

```bash
./scripts/deploy.sh            # 测试 → 同步代码 → 重建容器 → 健康检查 → 数据自检 → 域名验证
./scripts/deploy.sh --fast     # 跳过测试，适合只改前端时快速验证
./scripts/release.sh [版本]    # 打包 → 打标签推送 → 配了 GITHUB_TOKEN 时自动建 Release
```

`release.sh` 要求工作区是干净的（改动先提交），并会自己跑一遍后端测试。

代码改完只是让面板跑新代码，**订阅内容要生效还得在「构建发布」里发一版**。

## 安卓客户端

管理端的 Android 原壳（Kotlin + WebView），源码在 `android/`，产物 `dist/MagicPanel-1.0.2.apk`（`dist/` 不入库，需自行构建）。

- 回到门户首页：点侧边栏的 logo 标题
- 刷新走工具栏按钮，不用下拉手势
- 包名 `top.magichub.panel`，minSdk 24 / targetSdk 35，已签名
- App 内「⋮ → 面板地址」可切换部署地址，不用重新打包

构建与签名说明见 [android/README.md](android/README.md)。

## 文档

| 文档 | 给谁看 | 内容 |
| --- | --- | --- |
| [使用文档](docs/使用文档.md) | 使用者 | 每个页面的完整操作说明 |
| [开发文档](docs/开发文档.md) | 维护者、Agent | 架构、改动落点、测试与发布流程 |
| [配置文档](docs/配置文档.md) | 维护者、Agent | 配置的数据结构与修改路径 |
| [开发规格](docs/development/MagicPanel-开发规格.md) | 维护者 | 已实现细节的完整规格 |
| [产物构成](docs/development/MagicPanel-构建与发布-产物构成.md) | 维护者 | 一次构建固化了什么 |
| [接口清单](docs/development/接口清单与安卓客户端说明.md) | 维护者 | 全部接口与安卓壳约定 |
| [部署文档](docs/deployment/1Panel-Docker-部署.md) | 部署者 | 1Panel + Docker 上线步骤 |

## 说明

仅供个人与家庭内部使用。仓库里的机场订阅、节点凭据与设备令牌属于使用者自己的数据，别提交到公开仓库——`scripts/check_secrets.py` 会在推送前拦一次。
