# MagicPanel 远程配置管理：实现规格

日期：2026-10-19；状态：**已实现，本文描述当前代码的实际行为**。本文取代早期方案稿《Remote-Config-Console》，选型背景见[客户端选型与兼容性](../network/Client-Selection-and-Compatibility.md)。

MagicPanel 是家庭自用的代理订阅配置管理服务：一份策略、按目标编译、各设备用固定地址拉取。多位维护者共享同一份数据，账号只用于访问控制，不做资料隔离。

## 边界

- 不开发代理内核，不做流量中转，不提供旁路由或透明代理。
- 不依赖 Stash iCloud 同步；远程完整配置 feed 是唯一权威来源。
- 完整配置的变更走「候选构建 → 通道发布」；节点来源与规则来源的快照独立抓取、独立更新、独立验收。
- HTTP 200 只代表下载成功，不代表客户端已加载、VPN 已启动或规则已生效。服务器只记录下载事实，不推断设备状态。

## 技术栈与目录

| 层 | 实现 | 说明 |
| --- | --- | --- |
| 管理界面 | Vue 3 + Vite + Element Plus | 中文界面，桌面与移动端自适应 |
| API 与分发 | FastAPI（Python 3.12+） | 生产模式直接托管前端构建产物 |
| 数据 | SQLite（WAL） | 单实例单写入；运行数据在 `data/`，不进 Git |
| 配置渲染 | PyYAML | 按目标引擎生成方言 |
| 凭据加密 | cryptography（Fernet） | 订阅地址与节点快照加密落盘，主密钥在 `data/secret.key` |

```text
server/app/            # FastAPI 应用
  routers/             # auth / sources / rule_providers / policy / targets_devices / builds / feed / portal / snippets / misc
  compiler/            # render.py（按目标渲染）、validate.py（静态校验）
  services/fetcher.py  # 受限抓取（SSRF 防护、大小与超时限制）
  security.py          # 口令散列、令牌、Fernet 加密、审计写入
  db.py                # SQLite 连接与建表
server/tests/          # pytest 端到端用例
src/                   # Vue 前端（/portal 为独立展示页，不经后台布局）
scripts/dev.cjs        # npm run dev：同时启动 API 与 Vite
scripts/package.sh     # 打包可部署产物
data/                  # 运行数据（数据库、密钥、构建产物），已 gitignore
```

开发：`npm install && npm run dev`（前端 7100，API 8000，已配置代理）。生产：根目录 `Dockerfile` + `docker-compose.yml` 一条命令部署（见[部署文档](../deployment/1Panel-Docker-部署.md)），或 `scripts/package.sh` 产出裸机压缩包，解压后 `./run.sh` 启动。两种方式均以 `--proxy-headers` 启动，信任反代的 `X-Forwarded-*` 头生成订阅地址。

## 数据模型

| 表 | 要点 |
| --- | --- |
| users / sessions | 维护者账号（PBKDF2-SHA256），门户 PIN 散列存于 `users.portal_pin_hash`；会话只存令牌摘要，含独立 CSRF 令牌 |
| sources（节点来源） | 订阅地址 Fernet 加密（`url_enc`）；最近一次成功快照加密留存；失败不覆盖旧快照；`filter_unavailable` 控制是否只分发可用节点；`test_results` 记录逐节点测速结果 |
| rule_providers（规则来源） | 远程 / 内联两类；behavior、format、规则数与摘要 |
| proxy_groups（策略组） | select / url-test / fallback；成员引用、节点来源、过滤正则、测速参数 |
| rules（分流规则） | 有序、首条匹配；RULE-SET 引用规则来源；MATCH 兜底 |
| snippets（功能模块） | 脚本 / 复写 / 面板 / DNS / 通用五类 YAML 片段，按适用引擎（stash / mihomo / all）在构建时合并 |
| targets（发布目标） | engine（stash/mihomo）+ platform + 目标扩展 YAML（顶层整键覆盖） |
| devices（设备） | 绑定发布目标与通道；令牌存 SHA-256 摘要、前 10 位指纹与 Fernet 加密副本（`token_enc`，用于后台与门户重新展示地址） |
| builds（候选构建） | 不可变策略快照 + 逐目标校验结果；产物落盘 `data/builds/<id>/<目标>.yaml` |
| releases / pointers | 发布历史与通道指针；发布只移动指针，原子生效 |
| audit | 维护操作与设备下载记录；不含令牌与凭据 |
| settings | 对外基础地址、会话有效期、更新提示间隔 |

## 编译与校验

1. 构建时把来源、规则来源、策略组、规则、目标固化为 JSON 快照（`policy_sha` 为内容摘要），后续修改策略不影响已生成的构建。
2. 逐目标渲染：Mihomo 的节点来源鉴权键为 `header`，Stash 为 `headers`；DNS 段只发给 Mihomo（Stash 由客户端接管 DNS）；启用的功能模块按合并顺序与引擎匹配后深度合并（字典递归、列表追加、标量覆盖），目标扩展 YAML 最后应用、优先级最高。
3. 产物中的订阅地址一律为 `{FEED}` 占位，分发时才注入设备专属地址；产物本身不含令牌与节点凭据，可在界面上直接预览。
4. 所有 url-test / fallback 组自动加入「空组保护」占位节点（127.0.0.1:1），防止地区筛选为空时被客户端隐式改写为 DIRECT。
5. 静态校验：YAML 往返、策略组引用存在性、循环引用检测、空组、规则目标存在性、RULE-SET 引用、正则合法性、兜底 MATCH 存在、重复规则提示。任一错误使构建失败且不可发布。
6. 校验边界：Mihomo 目标在测速核心已安装时追加官方配置检查（`mihomo -t -f`，`{FEED}` 占位替换为回环地址，不发生真实请求），通过标记为「核心校验通过，实机行为待验收」；Stash 没有官方无头校验工具，结果只能标记为「静态通过，实机待验收」。

## 节点测速与不可用过滤

- 测速由固定版本的 Mihomo 核心（当前 v1.19.32）执行，与 Clash 系客户端同一机制：以节点快照生成临时配置启动本地核心（仅监听 127.0.0.1），经 external-controller 逐个发起 delay 测试（通过节点请求 `generate_204`，超时 5 秒，并发 16），结束后进程立即退出、临时目录删除。
- 协议兼容性由核心承担：SS / VMess / VLESS / Trojan / Hysteria2 / TUIC 等 Mihomo 支持的协议都能测；服务自身不实现任何代理协议。
- 结果口径必须如实理解：它反映**本服务器所在网络**到节点的连通性与延迟，不等于带宽、流媒体解锁能力，也不代表客户端所在网络的结果；UDP 行为未单独验证。
- 开启「只分发可用节点」后，feed 的节点子资源只包含测速通过的节点；订阅重新抓取后旧测速结果作废，需重新测速。未测速的节点按不过滤处理。
- 核心安装从 GitHub 固定版本发布页下载，httpx 失败时回退系统 curl；上游未提供逐文件校验值，安装后记录版本输出与 SHA-256 摘要供人工核对。下载可配置一次性代理（设置中的「核心下载代理」），测速本身不经代理。
- 构建产物引用的是 feed 子资源地址，过滤生效不需要重新构建或发布。

## 发布流水线

```text
编辑策略 → 创建候选构建（固定快照、逐目标渲染、静态校验）
→ 发到候选通道（单设备试用）→ 发布稳定 → 设备随后拉取
```

- 通道只有 stable / candidate 两条；设备各自绑定通道，候选通道用于灰度。
- 回滚即把通道指针移回任一成功的历史构建；客户端下次拉取才生效，已建立的连接不受影响。
- 节点来源与规则来源的快照更新不触发构建；它们经 feed 子资源独立分发，设备按 provider 自身的 interval 更新。

## 订阅协议与 API

管理接口（需会话 + CSRF）：`/api/v1/` 下的 sources、rule-providers、groups、rules、snippets、targets、devices、builds、channels、releases、overview、audit、settings、backup。设备令牌只在创建或轮换时返回一次；`POST /api/v1/devices/{id}/reveal` 可从加密副本还原订阅地址，操作记入审计。

| 接口 | 作用 |
| --- | --- |
| `POST /api/v1/sources/{id}/refresh` | 抓取订阅并留存快照，成功后作废旧测速结果 |
| `POST /api/v1/sources/{id}/test` | 用本地核心测速全部节点，结果随来源返回 |
| `GET /api/v1/core/status` / `POST /api/v1/core/install` | 测速核心状态与安装 |

分发接口（高熵 URL 令牌，无需会话）：

| 接口 | 作用 |
| --- | --- |
| `GET/HEAD /feed/{token}/config.yaml` | 设备完整配置；首行 `#SUBSCRIBED` 指向自身地址；带 ETag、`profile-update-interval`、`Cache-Control: private, no-cache` |
| `GET/HEAD /feed/{token}/res/provider/{name}` | 节点来源最近一次成功快照 |
| `GET/HEAD /feed/{token}/res/rule/{name}` | 规则来源快照（远程抓取或内联内容） |

无效令牌一律返回 404，不区分「不存在」与「已撤销」。GET 成功才计入下载次数与最近下载时间；HEAD 与 304 不计。

## 门户展示页

根路径 `/` 是独立于后台布局的门户展示页（管理端在 `/admin`），供快速查看与复制订阅地址，移动端自适应：

- 凭 4 位 PIN 进入；PIN 与维护者账号绑定（`users.portal_pin_hash`，只存散列），每位维护者在「设置」中管理自己的 PIN，任一有效 PIN 都可进入，撤销某人的 PIN 不影响其他人；全部撤销后门户页即关闭。PIN 连续输错 5 次锁定 10 分钟（单进程内存计数，任一 PIN 变更时重置）。
- PIN 只是查看门槛：订阅链接本身的安全性由地址中的高熵令牌承担，客户端拉取 feed 不需要 PIN。PIN 泄露不等于凭据泄露，撤销并重设即可。
- 展示内容：核心配置（设备订阅地址，按引擎分组，支持复制与二维码）、客户端资源（Stash / Mihomo / Clash Verge Rev / FlClash 官方入口）、分流规则（仅个人维护的非 RULE-SET 规则，点击复制）、已启用的功能模块（按分类，仅名称与备注）、各平台导入指引、连通性自检入口。
- 门户数据接口 `POST /api/v1/portal/data` 校验 PIN 后返回上述内容；没有任何维护者设置 PIN 时返回 404，门户页等同关闭。

## 安全模型

- 会话使用 HttpOnly + SameSite=Lax Cookie；写操作要求 `X-CSRF-Token` 与会话匹配。管理接口不开放 CORS。
- 订阅地址、节点快照、设备令牌副本用 `data/secret.key` 的 Fernet 密钥加密；主密钥不进入备份导出文件，需另行保管。
- 抓取默认仅允许 http/https 且拒绝环回 / 私网 / 保留地址；确需内网订阅须在来源上显式开启。单资源上限 10 MB、超时 20 秒、最多 3 次重定向。
- 令牌由密码学安全随机数生成；泄露后的处置是轮换或删除设备，已下发的节点凭据需联系机场重置。
- 备份导出为 JSON（含加密态数据与令牌摘要）；恢复会覆盖全部数据，需 `confirm=true` 并重新登录。

## 界面规范

- 界面默认暗色，可在侧边栏 / 顶栏手动切换亮色，选择持久保存在浏览器；门户展示页自带深色视觉，不随切换。
- 表格列出全部字段，不使用「更多」折叠；空状态说明原因与下一步。
- 状态用文字与色点双编码（如「● 抓取成功 / ● 抓取失败」），不单靠颜色。
- 版本号、摘要、令牌指纹、地址与路径一律等宽字体。
- 密钥类信息只在创建 / 轮换对话框显示一次，并说明泄露后果与撤销方式；列表只显示脱敏形式与令牌指纹。后台「复制地址」与门户页展示地址均从加密副本还原。
- 总览页提供各节点来源的可用率汇总（测速通过数 / 总数），供发布前确认节点质量。
- 术语固定：节点来源、规则来源、策略组、发布目标、候选构建、发布、稳定 / 候选通道、功能模块。

## 测试与验收

`server/tests/` 覆盖：初始化与登录、CSRF 拦截、多维护者共享数据、构建校验（缺兜底、空组、循环引用）、失败构建禁止发布、发布 - 拉取 - ETag/HEAD - 下载记录、无效令牌 404、子资源鉴权、令牌轮换失效、回滚、设置与备份、功能模块校验与构建合并、门户 PIN 全流程（未设置 404、错误 403、五次锁定 429、内容返回、轮换后地址同步）。运行方式：`cd server && ../.venv/bin/python -m pytest tests -q`。

实机验收仍需人工进行：各客户端导入订阅地址、确认更新后生效、断网保留旧配置——HTTP 200 不构成这些结论。

## 已知边界与后续

- 定时抓取尚未内置调度器；当前在页面上手动抓取，或用系统 cron 调用刷新接口。WebDAV 备份推送为预留方向，尚未实现。
- 已知边界：测速只反映服务器侧网络的连通性；客户端侧是否可用仍以实机为准。
- 设备「最近下载」只证明下载成功，不证明客户端已加载或规则已生效。
