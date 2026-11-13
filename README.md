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

它产出的是**给 Stash / Mihomo / OpenClash 消费的配置**。家庭部署里，路由器上的
OpenClash 拿这份配置做全屋透明代理与分流——那是消费方，不是本服务的一部分。

## 多套分流方案

策略组与分流规则支持**多套「方案」（variants）**：每个方案是一套完整、独立的
组与规则副本，构建时每个方案各出一份产物，订阅地址用 `?variant=<方案名>` 选择。

- **默认方案**是历史行为，完整机场分流（33 组 / 122 规则）；
- **自建美日**是精简方案：只有自建日美节点，客户端组列表只有
  🚀 默认代理 / 🇯🇵日本 / 🇺🇸美国 三个可见组（+ 隐藏自动测速组），
  分流按「AI/谷歌等 → 美国、低延迟/影音 → 日本、国内可达 → 直连」三向归位；
- 门户页设备卡片上选方案，复制地址 / 下载文件 / 一键导入 / 二维码 / 预览源码
  全部联动；不带参数的地址永远是默认方案，老订阅不受影响。

设计与约束见 [方案设计](docs/reference/方案设计-多套分流方案.md)。

## 有什么

| 页面 | 干什么 |
| --- | --- |
| 系统概览 | 生产版本、节点可用率、设备、策略规模、连接状态五块瓦片 + 运行状态自检 |
| 节点来源 | 机场订阅抓取与快照留存（支持自定义请求头、上传订阅文件、从 curl 导入）；本地单节点（自建、家宽、机房、专线）手动录入 |
| 规则来源 | 远程或内联的规则集，独立抓取与验收 |
| 策略组 | select / url-test / fallback / load-balance / relay，按来源聚合节点；支持多套**分流方案**，页头切换 |
| 分流规则 | 域名、IP、进程、规则集，按序匹配；可限定引擎平台、具体设备与所属方案 |
| 引擎平台 | 引擎 + 平台（Stash-macOS、Mihomo-Windows、OpenClash-Mihomo……），一套客户端对应一个 |
| 基础配置 | 产物顶层键分三层：引擎默认配置 → 引擎平台配置 → 设备独立配置 |
| 拓展模块 | 可复用的 YAML 片段（Stash 磁贴、Mihomo TUN、DNS 策略、脚本改写……） |
| 设备管理 | 每台设备一个固定订阅地址，一个订阅环境；拖拽排序；标注配置是否已更新；**点设备标题可预览配置源码**（YAML 语法高亮，走 `?preview=1`，不记拉取、不加 `#SUBSCRIBED`） |
| 自主维护 | magic-sets 仓库的文件管理器：语法高亮编辑、YAML 校验、提交与同步 |
| 构建发布 | 产物快照、校验结果、发布与回滚、版本对比 |
| 自动构建发布 | 定时抓取、测速，策略有变化就自动构建并发布 |
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

1. **基础配置** —— 引擎默认配置 → 引擎平台配置 → 设备独立配置，三层各自只存改动过的部分
2. **结构化内容** —— 节点、策略组、分流规则，由各自页面维护，任何配置层都不许覆盖
3. **拓展模块** —— 启用的 YAML 片段，与引擎匹配后深度合并（字典递归、列表追加）
4. **平台扩展** —— 单个引擎平台自己的片段，最后应用

订阅地址带令牌，令牌可随时轮换；旧地址立即失效，客户端换新地址即可。
带 `?variant=<方案名>` 时下发对应方案的产物，不带就是默认方案。

## 仓库结构

```text
server/app/            后端
  routers/              HTTP 接口（按业务分文件）
  services/             抓取、测速、发布、调度、备份
  compiler/             产物编译与校验
  db.py                 表结构与迁移
src/                    前端（Vue3 + Element Plus），views/ 里一个页面对应一个文件
scripts/                部署、备份、自检、策略快照脚本
policy/snapshots/       线上策略的无凭据快照（规则顺序 / 策略组 / 规则来源）
docs/                   文档
android/                管理端的安卓壳
official-example/       官方配置样例，核对引擎默认配置用
```

`policy/snapshots/*.json` 是规则与策略组的版本化存档——这些内容只存在数据库里，
git 看不到。导出/导入见 [AGENTS.md](AGENTS.md) 的「策略快照」一节。

## 开发与发布

**开工前先对齐代码**：仓库是唯一事实源，NAS 上的 `/opt/magicpanel` 是部署副本。

```bash
git pull --ff-only                              # 拉最新
git status --short                              # 应为空，脏工作区会把半成品发上去
```

本地自检与发布：

```bash
cd server && ../.venv/bin/python -m pytest tests -q     # 后端测试
npm run build                                            # 前端产物（输出到 server/app/static）

./scripts/deploy.sh            # 测试 → 同步代码 → 重建容器 → 健康检查 → 数据自检 → 域名验证
./scripts/deploy.sh --fast     # 跳过测试，适合只改前端时快速验证
./scripts/release.sh [版本]    # 打包 → 打标签推送 → 配了 GITHUB_TOKEN 时自动建 Release
```

`release.sh` 要求工作区是干净的（改动先提交），并会自己跑一遍后端测试。

### 两类改动，生效方式不同

| 类型 | 内容 | 怎么生效 |
| --- | --- | --- |
| 代码 | `server/`、`src/`、`scripts/` | `deploy.sh` 重建容器后立即生效 |
| 策略数据 | 规则、策略组、规则来源（数据库里） | 必须再走一次「创建构建 → 发布测试 → 发布生产」 |

**代码改完只是让面板跑新代码，订阅内容要生效还得发一版。** 渲染器（`compiler/render.py`）
的改动也算策略侧——自动构建的指纹只看策略快照，不看渲染器代码，必须手动发一次。

### 部署后怎么确认没坏

```bash
ssh archon@10.0.1.2 'docker inspect magicpanel --format "{{.State.Health.Status}}"'
ssh archon@10.0.1.2 'docker exec magicpanel curl -s -o /dev/null -w "%{http_code}\n" \
  -m 10 https://www.gstatic.com/generate_204'          # 期望 204（经路由器透明代理出网）
```

更细的流程、约束与核对清单见 [AGENTS.md](AGENTS.md)（Agent 必读）与
[开发文档](docs/开发文档.md)。

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
