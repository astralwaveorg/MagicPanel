# MagicPanel V2 实施状态与运行手册

日期：2026-11-16  
分支：`codex/magicpanel-v2`  
状态：**核心后端与候选运维脚本已完成；生产部署和最终网络切换仍按门禁分阶段执行。**

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

1. 生产 NAS 尚未部署本分支；当前生产仍运行旧镜像和旧策略。部署前必须完成数据备份、策略快照和回滚镜像记录。
2. `v2_runtime_activation` 仍为 `staged`。这是有意状态：没有完成真实 Stash/R6S 故障矩阵和预算复核前，不得改为 `active`。
3. Plan 02 Task 12 的新版 build manifest、versioned URL 与完整 artifact ACL 还未实现；当前 feed 兼容旧 URL。
4. Plan 03 只完成关键状态、选择和任务适配，不等于 U03–U09 全部浏览器旅程完成。
5. 旧 feed freeze 代码可用，但生产冻结必须以 R6S 实际 raw/缓存字节和 NAS live 逐项对比为基线；不能用当前 NAS 内容冒充旧客户端基线。
6. WireGuard、SQM、AdGuard Home、OpenClash 最终切换仍属 Router Final。本轮不重启 OpenClash、不刷新订阅、不改 WAN/LAN/PPPoE/DNS 转发。
7. 住宅 IP 当前不存在，探测授权为零。未来添加住宅资源时必须单独登记用途、硬配额和预算，不能默认进入通配检测。

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
