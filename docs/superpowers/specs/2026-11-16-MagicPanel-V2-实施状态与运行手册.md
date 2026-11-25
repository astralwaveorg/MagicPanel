# MagicPanel V2 实施状态与运行手册

日期：2026-11-16  
分支：`codex/magicpanel-v2`  
状态：**核心后端、候选运维脚本与 NAS 生产代码镜像已完成部署；auto_stable_v1 仍 staged，Router Final 未执行。**

## 1. 本次已落地的能力

### 检测与自动恢复地基

- 新增 `probe_jobs` / `probe_items` / `probe_results` / `probe_reservations` / observer / path / adapter health / routing plan / resource revision / deployment bundle 等持久契约。
- 迁移入口为 `db.migrate_probe_delivery_v2()`，幂等；`v2_recovery_mode=auto_stable_v1`，但 `v2_runtime_activation=staged`。验收激活前不会自动外发检测。
- `services/recovery_policy.py` 是阈值唯一事实源：每周 04:00 全量、每日 08:00 地区抽样、300 秒当前路径哨兵、地区 ≤50% 两轮确认才扩大、全局 72 小时限次。
- 滚动预算按共享 30000 请求 / 2.5 GiB 与子池限制计算；子池不能绕过总池。
- 旧“来源同步测速”入口已改为 202 受管任务；手动测速和批量测速 UI 现在只提交任务，不直接启动核心。
- observer/path 独立资格、基础探针白名单、状态归一、硬故障确认、跨出口熔断、AI 无成本排序、Google US→SG→JP 严格档位均已实现纯函数合同。
- 预演令牌绑定 purpose、actor、输入摘要和 300 秒 TTL；预演零写，确认创建时重新核对目录 revision 和 observer 资格。

### 内容、资源和发布安全

- 规则抓取先执行严格验证：拒绝 HTML、坏 YAML、坏 MRS；失败保留上一份可用正文。
- 验证通过的 provider/rule 正文写入 `resource_revisions` + 加密 `private_blobs`；相同字节/元数据去重，不同 behavior 不合并。
- `rule_health` 独立区分 7 天 fresh、14 天 stale 和 expired；格式计数不再是资格判定。
- 发布入口新增 `expected_release_revision` + `idempotency_key` CAS；同 revision 并发只有一个成功，重复同 key 返回原结果，失败保留 testing/production 原指针。
- 缺核心时 `_unchecked_core_targets()` 不再被空集吞掉；未核心校验的 Mihomo 目标不能自动发布到生产。
- `release_state` 现在返回独立 `release_revisions`，UI 显示生产/测试指针版本。
- 新增旧 feed 冻结层：最终 envelope 和引用子资源加密存放，`ACTIVE` 原子切换；reader 只在已注册设备身份和精确 route 命中时返回冻结字节。解除冻结必须有 contract 与 owner 回执。
- DNS 意图只接受可表达的 exact/suffix，IDNA 规范化；共享 scope 冲突阻塞，不按最后发布者覆盖。

### UI 与运维候选

- Overview 将“节点可用率”改为“基础连通样本”，明确下载/拉取记录不等于业务加载成功。
- Overview 显示发布指针 revision；Sources 的测速按钮适配 202 任务返回。
- 新增 `deviceState()` 与 `probeSelection()`，设备三态和节点选择不再把“无观测”伪装成成功，也不允许同一 UID 跨 revision 混选。
- 新增离线 namespace 网络实验、路由器 DNS/gateway 守护候选、apply/rollback 脚本和验收 CLI。这些都是候选，不在生产路由器自动安装。

## 2. 当前边界与未完成项

1. 生产 NAS 已部署本分支核心镜像；这是代码/迁移部署，不是 `auto_stable_v1` 激活，也不代表 Router Final 完成。部署前已保存数据库备份、策略快照和回滚镜像。
2. `v2_runtime_activation` 仍为 `staged`。这是有意状态：没有完成真实 Stash/R6S 故障矩阵和预算复核前，不得改为 `active`。
3. Plan 02 Task 12 的新版 build manifest、versioned URL 与完整 artifact ACL 还未实现；当前 feed 兼容旧 URL。
4. Plan 03 只完成关键状态、选择和任务适配，不等于 U03–U09 全部浏览器旅程完成。
5. 旧 feed freeze 代码可用，但生产冻结必须以 R6S 实际 raw/缓存字节和 NAS live 逐项对比为基线；不能用当前 NAS 内容冒充旧客户端基线。
6. WireGuard、SQM、AdGuard Home、OpenClash 最终切换仍属 Router Final。本轮不重启 OpenClash、不刷新订阅、不改 WAN/LAN/PPPoE/DNS 转发。
7. 住宅 IP 当前不存在，探测授权为零。未来添加住宅资源时必须单独登记用途、硬配额和预算，不能默认进入通配检测。

## 2A. 2026-11-16 NAS 部署回执

- 部署前生产镜像：`sha256:1a02658dbea6a3944b2295df3592158f5f184b20c04703f19cb072a3f7c5646c`
- 部署后生产镜像：`sha256:dcbaa297961d6527cf46f58def4e08b7531b0880012ead0aae84f592ea1a3f00`
- 数据库备份：`data/magicpanel-backup-pre-v2-core-20261116.db`（11,198,464 字节）
- 策略快照：`policy/snapshots/2026-11-16-pre-v2-core.json`，digest `c49ecf7ad5616f85`
- 容器健康：healthy；启动时间 `2026-11-16T06:00:43.484152063Z`
- 数据自检通过；`probe_jobs`、`resource_revisions`、`release_state`、`operation_requests` 全部存在
- 运行模式：`auto_stable_v1`；激活状态：`staged`
- 线上检查：`/api/v1/setup/status`、`/`、`/admin/login` 均 200；旧设备 feed 200（97,092 字节）
- 受管 API 未登录访问：`/api/v1/probe-jobs` 与 preview 均 401
- 生产 release_state：production revision 1，testing revision 0；feed freeze 未 arm

首次迁移在生产备份副本中发现 Hysteria2 port-range 节点缺 `port`；已在迁移前用副本验证兼容，再把新镜像切上生产。守护进程旧 Docker proxy 只影响构建，通过临时 `DOCKER_CONFIG` 隔离绕过，未永久修改 NAS Docker 配置。

## 3. 执行命令

### 本地验证

```powershell
cd server
..\.venv\Scripts\python.exe -X utf8 -m pytest tests -q

cd ..
npm run test:ui
npm run build
.venv\Scripts\python.exe -X utf8 scripts\check_secrets.py --all
```

Windows 上 `test_core.py` 的两个 Linux 可执行夹具会跳过；这是平台边界，不是业务失败。

### 预演探测

```http
POST /api/v1/probe-jobs/preview
```

请求只需要安全字段：`variant_id`、`node_keys=[{node_uid,revision}]`、`service_ids`、`observer_id`、`trigger`。响应返回 blockers、expected revisions、preview token 和 digest。预演不写表、不消耗预算。

只有 preview 无 blockers 后，才可：

```http
POST /api/v1/probe-jobs
```

必须携带 preview token、`expected_preview_digest` 和不少于 8 字符的 `idempotency_key`。服务端会重新核对 catalog revision、observer 和输入 digest。

### 发布

新调用应同时携带：

```json
{
  "reason": "发布说明",
  "expected_release_revision": 0,
  "idempotency_key": "publish-2026-11-16-001"
}
```

同一环境 revision 已前进时返回 409；同一 idempotency key 和同一内容重复提交返回第一次结果。

### 旧 feed 冻结

只在独立 staging 先演练：

```bash
python -X utf8 scripts/freeze_feed_contract.py prepare --snapshot <private.json> --root <private-dir>
python -X utf8 scripts/freeze_feed_contract.py verify --root <private-dir>
python -X utf8 scripts/freeze_feed_contract.py arm --root <private-dir> --expected-sha <contract_sha>
```

`snapshot JSON` 的 route body 用 base64。生产 arm 前必须核对 R6S 实际缓存与 NAS live hash；release 必须有 owner load receipt。

## 4. NAS 部署顺序

1. 在 NAS 上导出当前逻辑备份和 `policy/snapshots/<date>-before.json`。
2. 记录当前 `magicpanel` 镜像 digest、启动时间、健康状态和数据库文件 hash。
3. 部署本分支工作区；`deploy.sh` 会迁移 schema、重建容器并跑健康检查。
4. 部署后核对：
   - `/api/v1/release-state` 返回 `release_revisions`；
   - SQLite 存在 `probe_jobs`、`resource_revisions`、`release_state`；
   - `v2_runtime_activation` 仍为 `staged`；
   - 旧设备 feed 仍返回 200；
   - `/api/v1/probe-jobs` 需要登录，GET 不触发探测。
5. 保持旧自动构建/发布观察至少一个周期。若异常，用部署前镜像 digest 回滚容器；不要只回滚 YAML。

## 5. 激活 auto_stable_v1 的门槛

满足以下条件前保持 `staged`：

- 实际 NAS observer 通过 path qualification，fixture 不能冒充生产 path。
- 真实 Stash Android/macOS/iOS 分别验证 cron/API、强制叶、PUT 后 GET 读回和蜂窝场景。
- R6S 与 NAS 视角分别完成基础探测和预算核算。
- 故障矩阵覆盖：单节点失败、地区池失败、全部节点失败、核心挂死、DNS 失效、残留接管、IPv6/UDP、国内冷 DNS 新建连接。
- Google 矩阵验证任一美国可用不降 SG；unknown/限流不能证明整档耗尽；三档失败不触发 BASIC_WAN。
- 预算预演展示实际节点数、服务目录、请求数和字节上界。
- 回滚演练确认发布指针、旧 feed、DNS bundle 和 owner receipt 恢复路径。

全部通过后，由维护窗口显式把 `v2_runtime_activation` 改为 `active`，并记录启用时间、revision、操作者和首轮复核回执。

## 6. Router Final 原则

- 先部署 NAS 并稳定，再处理 OpenClash。
- OpenClash 当前主路由运行态不动；不 `apk upgrade`。
- 最终切换前生成 UCI、nft、dnsmasq、AGH、SQM、WireGuard 备份。
- 采用分阶段候选 bundle：先 offline 验证，再 apply，再观察，失败 rollback。
- 核心整体故障由外部 gateway guard 撤接管进入 BASIC_WAN；普通节点、地区池或 Google 三档失败不得触发全屋原生 WAN。
- DNS guard 只允许受控本地端口 1053/5353 redirect；国内直连 DNS 不依赖代理核心。
- WireGuard 继续只回家内网，不承担默认出海路由。

## 7. 交付验收定义

“项目完成”不能只看后端测试通过。最终验收必须同时满足：

- 后端全量测试、UI 测试、构建、凭据扫描通过。
- NAS 生产镜像/迁移/旧 feed/发布指针回执可追溯。
- 至少一次受控 staging 冻结/arm/lookup/release 演练成功。
- 真实主用设备恢复能力验证，而不是仅 NAS shadow 结果。
- R6S 最终切换后 48 小时观察通过，期间国内服务、Google 档位、GitHub/TikTok/流媒体和国内冷启动均有证据。
- 已知限制、预算、规则过期、探测覆盖、未验证设备在 UI 和交付报告中可见。

## 2B. 2026-11-16 方案收敛与构建 259 回执

- 变更前策略快照：`2026-11-16-pre-unified-variant.json`，digest `2d5e8a6c1605278a`
- 变更后策略快照：`2026-11-16-post-unified-variant.json`，digest `8c0d908e882f0afe`
- 生产镜像：`sha256:edcd4100daf247b9d641c685bbbc85dfbdf5224fa0346e914d7b571a30d45aee`
- 新生产构建：#259；生产 release revision `2`，testing revision `1`
- `自建美日` 已停用；新构建 18 个产物，没有 `@自建美日` artifact
- 默认组修正：
  - Google/AI：US(NTT/机房/自动) -> SG -> JP；
  - TikTok：JP -> SG -> US NTT -> 区域/默认；
  - 开发/社交：NTT/机房优先，再默认代理；
  - 日本组移除美国 NTT 干扰成员；
  - 普通代理继续保留机场与自建容量。
- 数据自检通过。
- 旧订阅验证：无参数与 `?variant=自建美日` 均返回 200；正文 SHA 前 12 位同为
  `5267fdc9e1e3`；旧链接响应头 `X-MagicPanel-Variant-Fallback: default`。
- 第一次收敛尝试在嵌套写锁处回滚；脚本已拆分策略事务和构建/发布事务后重跑成功。

## 2C. 2026-11-16 路由器安全准备与构建 261 回执

- R6S 基线备份：`/root/mp-final-prep/20261116T151500/router-baseline.tar.gz`，26.4 MiB，SHA256 `c1d467b7438cd551fc787b7bee0c624911066261b31860f1f67855abe065668e`。
- 已持久修正 WireGuard peer 清单为 `client_phone client_macbook`；运行中两个 peer 均存在。这是配置一致性修复，不改默认路由。
- 已发现并修正默认组只改 `proxies` 投影的问题；现在通过 `node_refs.canonical_group()` 固化 `members_v2` 类型化引用。构建 #260 是错误中间态，已被 #261 替换。
- 生产构建 #261：production release revision `4`。
- 语义校验通过：
  - Google/AI：美国 NTT 自动 -> 美国机房 -> 美国自动 -> 新加坡自动 -> 日本机房 -> 日本自动 -> 空组保护；
  - TikTok：日本自动 -> 新加坡自动 -> 美国 NTT 自动 -> 区域/默认代理；
  - 开发/社交：美国 NTT 落地优先，再机房/区域/默认；
  - 日本组不含美国 NTT 落地。
- Mihomo 已移除废弃的 `global-client-fingerprint`；节点级 `client-fingerprint` 保留。生产镜像 `sha256:8269d734974d6fabb7af60df29e2cc75ad8037cda54a3ba79d92ba41f8125c78`。
- R6S 候选包：`/etc/openclash/candidates/mp261/OpenClash-Mihomo.yaml`，SHA256 `845a3d1d7f98ca62308fef24b04426a02a126bdc4b81250bf0b4b419332bca6c`，110 个规则缓存已随包，当前核心 `-t` 通过。
- 当前 OpenClash live 仍是旧 `MagicPanel-自建美日.yaml`，未切换；符合冻结要求。
- 策略快照：`2026-11-16-post-typed-groups.json`，digest `efcd038e013db7b8`。
- HK/KR DNS：`dns-hk.magichub.top` / `dns-kr.magichub.top` 仍无 A 记录；18443 未部署。因此仍阻塞 Router DNS Final，不能用公共 DoH 冒充可信控制面。
- 生产化 gateway/dns guard 未安装；仓库脚本当前仅限离线 namespace，不能直接上生产。外部守护生产 inventory 封包仍待完成。

## 2D. 2026-11-16 DNS 方案修订

用户已创建 `dns-hk.magichub.top` / `dns-kr.magichub.top` A 记录，但这两项不再作为 Router Final 必备。修订原因：自有 VPS 会把续费、单机、单域封锁和单地域故障引入家庭 DNS 关键路径；公共多源 DoH/DoT 是更合理的默认方向，但必须多运营方并用并分别实测，不能单一公共服务商。

> **2026-11-26 后记**：hka（103.38.83.78）已于 2026-11-23 退役，`dns-hk` 与 `kix` 的 A 记录已从 Cloudflare 删除；自建 DoH 候选仅剩 `dns-kr`（休眠，机器 armoci 在线）。

当前结论：

- HK/KR 18443 部署暂停；两 A 记录可休眠，不进入 R6S 候选配置。
- Router Final 不再因 HK/KR DNS 未部署而阻塞。
- 仍要求 DNS 不依赖 Mihomo 业务核心；海外解析源使用多公共端点健康检查与降级。
- 旧契约 §4 如与本节冲突，以 §4.0 修订为准。

## 2E. 2026-11-16 路由器配置修复与构建 262 切换回执

用户已在 OpenClash 切换 `MagicPanel-默认.yaml` 后，做了只读体检并完成以下受控修复：

1. **Smart 内核关闭**
   - 旧 Smart 内核 `alpha-smart-gc4df732` 已备份；
   - 安装官方稳定 Mihomo `v1.19.34 linux-arm64`；
   - release digest `sha256:daaf78a6240a282cdfd75bcbf98fe321f6bd52765cc29e79f344191198f0b50f`；
   - `smart_enable=0`、`core_type=Meta`；
   - 当前进程稳定运行 `Mihomo Meta v1.19.34`。

2. **关闭宽泛 CN-IP 提前旁路**
   - `china_ip_route=0`；
   - nft 不再把大段中国大陆 IP 提前 return；
   - 由 #262 规则集中 `cn` / `cn-ip` / 明确直连规则处理；
   - 百度、京东、淘宝、B站、Google 204、YouTube 204、GitHub 复测通过。

3. **修复规则缓存陈旧**
   - 旧路由器缓存曾含 Mihomo 不接受的 `PROCESS-NAME,qbittorrent*`；
   - MagicPanel feed 内容本身已是正确 `PROCESS-NAME,qbittorrent`；
   - 已刷新 `magic-process` provider，路由器缓存不再有非法通配。

4. **修正 `find-process-mode`**
   - MagicPanel 引擎默认是 `strict`，但 Mihomo/Linux 平台层覆盖为 `off`；
   - 已改为 `strict`，策略快照已导出；
   - 生产构建 #262 已发布。

5. **阻断 IPv6 泄漏**
   - 旧状态：LAN RA 开启、LAN→WAN IPv6 可直连，会绕过当前 IPv4-only Mihomo；
   - 已关闭 LAN RA/DHCPv6；
   - 新增防火墙规则 `Block-IPv6-LAN-WAN`，IPv6 全协议 DROP；
   - IPv6 出站测试失败符合预期，IPv4 业务正常。

6. **当前生产/路由状态**
   - NAS production build #262，verify success；
   - production revision 5，testing revision 4；
   - R6S live 配置：`/etc/openclash/config/MagicPanel-默认.yaml`；
   - 路由器 source SHA256：`579fe26e63aa373131e18f0a43c18c9472278312544d30ec9c68f4d06f00fbc3`；
   - 运行态由 OpenClash 合成，所以哈希不同属预期；
   - 进程 PID 19919，`Mihomo Meta v1.19.34`；
   - 当前策略快照 digest：`0458d5979f04eb00`。

7. **仍保留为分阶段项**
   - UDP 代理仍关闭，避免一次开启 IPv6/UDP/TPROXY 引入不可控风险；
   - IPv6 仍阻断，待 UDP/IPv6 分阶段验收后再开；
   - external gateway/dns guard 尚未生产化；
   - NAS 上 BT 直连超时/拒绝是日志噪音，属于 P2P peers 正常不可达，不代表家庭业务故障。

## 2F. 2026-11-16 核心锁定、密钥轮换与 WARNING 结论

用户手动把 OpenClash 核心切回 Smart alpha 以消除首页更新提示；这会使关键路由回到未验收内核。已恢复官方稳定 Mihomo `v1.19.34`，并增加每分钟核心锁定守护：

- R6S 私密守护：`/root/mp-final-prep/20261116T151500/restore-stable-core.sh`；
- 稳定核心备份：`/root/mp-final-prep/20261116T151500/mihomo-stable`；
- 期望 SHA256：`022da41e03ce70641a2f50c485b4f69ade8f1c7aeeece2cf1ec45c614a029441`；
- 若核心被覆盖，自动恢复并重启 OpenClash；
- crontab 标记：`magicpanel-core-lock`。

同时，截图中的 dashboard URL 包含 controller secret，已轮换 controller secret 和 proxy auth password；新值只保存在 R6S 私密文件，不进入仓库、日志或回复。旧 dashboard 链接不再可用，应从 LuCI/OpenClash 页面重新打开面板。

Mihomo 日志中的大量 WARNING 形如 `dial DIRECT (match RuleSet/cn-ip) 10.0.1.2 -> 中国IP:高端口`，来源是 NAS 上的 qBittorrent/Transmission/aria2 等 P2P peer 连接失败；端口特征包括 51413、16881、6881 和大量临时高位端口。这些是 P2P peer 正常不可达/拒绝/超时，不表示 Google、AI、GitHub、国内站点或透明代理主链路故障。当前无 level error/fatal。

不建议为了让日志好看而降级为 error；否则会掩盖真实探测/连接问题。如短期不需要 BT，可暂停对应容器/服务；如继续使用 BT，保留 WARNING 即可。
