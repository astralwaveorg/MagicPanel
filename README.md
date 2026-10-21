# MagicPanel

家庭自用的代理订阅配置管理服务：一份策略、按目标编译（Stash / Mihomo）、各设备用固定订阅地址拉取。多位维护者共享同一份数据，账号仅用于访问控制。

- 根路径 `/`：门户展示页，凭维护者的 4 位 PIN 查看并复制订阅地址；PIN 与维护者账号绑定，可在后台按人撤销；已登录的维护者免 PIN
- `/admin`：管理端（中文界面，桌面 / 移动端自适应；默认暗色，可切换亮色）
- 后端：FastAPI + SQLite，生产模式直接托管前端产物
- 边界：不开发代理内核、不做流量中转、不提供旁路由或透明代理

## 功能

- **节点来源**：订阅抓取、快照留存、Mihomo 核心拨测（可选过滤不可用节点）；支持一键抓取、一键测速、批量改抓取/测速间隔、批量删除（校验策略组引用）；每个来源可独立关闭“自动抓取”或“自动测速”；关闭自动抓取后只使用本地快照；启用“只分发可用节点”的来源抓取后自动补测，自动发布前要求有可用测速结果
- **本地节点**：手动填写服务器、端口、协议与凭据，协议字段由 schema 动态渲染；节点带类型标签（本地/自建/家宽/机房/专线/中转/落地），启用的节点以 `名称 (类型)` 直接写入产物，并可在策略组中勾选；参数加密落盘；Stash 与 Mihomo 的协议键名分别渲染（Hysteria2 用 `auth`/`down-speed` 与 `password`/`down`）
- **产物配置**：按引擎维护产物的顶层全局键（端口、模式、日志、IPv6、profile、DNS 与任意自定义键），表单由服务端 schema 驱动、高级 YAML 兜底；提供官方精简预设、产物预览与「保存并构建发布」；结构化内容（节点/策略组/规则）由各自页面维护，不允许被覆盖
- **规则来源**：远程 / 内联规则集，独立抓取与验收；支持名称 / URL 模糊搜索、分页跳转、一键抓取远程来源、批量改间隔、批量删除（校验分流规则引用）
- **策略组**：select / url-test / fallback / load-balance / relay，引擎差异自动处理；支持拖动排序
- **分流规则**：含 PROCESS-NAME、RULE-SET、no-resolve 等，按序编译，支持拖动排序
- **功能模块与平台扩展**：Stash 的 http / cron / script-providers 与 Mihomo 的 tun / sniffer 等平台差异以 YAML 整键覆盖维护；引擎平台支持拖动排序
- **构建与发布**：单一版本生命周期状态机（已构建 / 测试中 / 生产中 / 已下线），生产与测试环境各自至多一条生效版本；构建校验、产物摘要、一键回滚、下载记录；顶部显示当前生产 / 测试版本、策略摘要与发布来源、时间；只有从未发布过的构建可删除
- **自动发布**：服务端定时抓取上游、按间隔自动测速；策略变化时自动构建，校验通过后按配置发布到生产 / 测试环境；“立即运行一次”强制执行一轮并记录运行历史；发布历史保留最近 10 条；客户端更新间隔与服务端自动构建间隔统一为 1 小时
- **设备**：文件名决定下载到的配置文件名，设备名用于后台与门户展示；每台设备固定订阅地址与独立订阅环境（生产 / 测试）
- **测速核心**：后台在线安装（自动解析最新版本）或本地上传 .gz / .zip / 裸二进制

设计与行为细节见 [docs/development/MagicPanel-开发规格.md](docs/development/MagicPanel-开发规格.md)；构建与发布的产物构成、固定与动态内容、权限边界见 [docs/development/MagicPanel-构建与发布-产物构成.md](docs/development/MagicPanel-构建与发布-产物构成.md)；发布状态机的四态与约束见 [docs/development/MagicPanel-开发规格.md](docs/development/MagicPanel-开发规格.md)。

## 开发

```sh
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
npm install
npm run dev          # API 127.0.0.1:8000，前端 127.0.0.1:7100（已代理 /api 与 /feed）
```

打开 http://127.0.0.1:7100/admin ，首次访问会引导创建第一位维护者账号。

## 测试

```sh
cd server && ../.venv/bin/python -m pytest tests -q
```

## 部署

Docker（推荐，含 1Panel 反向代理步骤）：

```sh
docker compose up -d --build   # 数据持久化在 ./data，监听 127.0.0.1:47100
```

完整步骤见 [docs/deployment/1Panel-Docker-部署.md](docs/deployment/1Panel-Docker-部署.md)。

已配置 NAS 环境后，日常迭代用一键脚本：

```sh
./scripts/deploy.sh          # 测试 → 同步工作区 → 重建容器 → 健康检查 → 域名验证
./scripts/deploy.sh --fast   # 跳过测试，快速验证前端改动
./scripts/release.sh [版本]  # 打包 → 打标签推送 → 配置 GITHUB_TOKEN 时自动创建 Release
```

也可以不用 Docker，打包后裸机运行：

```sh
./scripts/package.sh   # 构建前端并产出 dist/magicpanel-<时间戳>.tar.gz
tar xzf magicpanel-*.tar.gz && cd magicpanel
./run.sh               # 首次运行自动创建虚拟环境并安装依赖，监听 127.0.0.1:8000
```

生产环境应置于反代之后启用 HTTPS，并在“设置”中填写对外基础地址。
运行数据（数据库、加密密钥、构建产物）位于 `data/`，备份时请同时保存 `data/secret.key`（与备份文件分开存放）。

内置定时任务随应用启动，按单进程运行；如需临时关闭可设置环境变量 `MAGICPANEL_SCHEDULER=0`，日常开关在“自动发布”页面。


## 安卓客户端

管理端的 Android 原壳（Kotlin + WebView），源码在 `android/`，产物：

```
dist/MagicPanel-1.0.2.apk
```

- 回到 Magic Panel 首页：点侧边栏的 logo 标题（管理端顶部「☰ → MagicPanel」也一样）
- 刷新走工具栏按钮（不再用下拉手势，避免向下滑动被刷新劫持）

- 包名 `top.magichub.panel`，minSdk 24 / targetSdk 35
- 已签名（v2 + v3），可直接安装；小米 17 Pro Max、一加 13 等 Android 15/16 机型已适配
- App 内「⋮ → 面板地址」可切换部署地址，不必重新打包
- 构建与签名说明见 [`android/README.md`](android/README.md)
- 接口清单与客户端能力说明见 [`docs/development/接口清单与安卓客户端说明.md`](docs/development/接口清单与安卓客户端说明.md)
