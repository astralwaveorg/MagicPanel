# MagicPanel-默认 对齐交付（2026-11-21）

状态：**已完成。** 构建 #353 发布生产（2026-11-21 08:27:29，release_rev 73）。路由器侧由向阳自行切换到目标模板路径（OpenClash.yaml，57 组，与目标样本组清单一致），订阅地址不变、OpenClash 自动更新——向阳明确「不用管路由器」，真相源验收第 2 条的订阅更新命令因此不再需要由 ZCode 执行。

## 一、已完成

1. **备份**（约束 2）：NAS `/opt/magicpanel/data/router-maintenance/2026-11-21/` 下有 `policy-before-alignment.json`（variants 2 / rules 252 / groups 70 / providers 109）与生产产物 `MagicPanel-默认-build331.yaml`、`build348.yaml`；快照副本回存仓库 `policy/snapshots/2026-11-21-before-alignment.json`。
2. **目标快照构造**：`scripts/build_alignment_snapshot.py` 从备份快照转换生成 `policy/snapshots/2026-11-21-target-alignment.json`（digest 重算）。
3. **导入**：`import_policy.py` 官方路径（自动 DB 备份 `magicpanel.db.before-import-*`），写入 rules 212 / proxy_groups 94 / rule_providers 141。
4. **构建 #353**：verify=success，34 份产物全部通过（含顺序不变量与 Fake-IP 检查）。
5. **产物语义验收**（真相源第六节第 1 项）：组数 59（目标 57 + 游戏UDP池 + 路由回家）；🇬 谷歌服务 / 🇸🇬 新加坡媒体 / 🚇 WireGuard 存在；AI 组链 = 美国自建测速 → 家宽自动（仅出现一次）→ 日本自建测速；🚀 故障转移 SG 自建打头；Telegram 直连优先；非标端口直连默认；规则尾块 cn → cn-ip → Custom_Port_Direct（非标端口）→ private-ip → QUIC → MATCH；google(#50) 早于 category-ai-!cn(#51)、apple-tvplus(#59) 早于 apple(#60)、netflix(#63) 早于 media(#73)。
6. **Astral-PassWall-Mihomo 设备已删除**（id 22，令牌失效，审计记录）。剩余 13 台设备。
7. 单节点订阅链接（nodes feed）全程未动。

## 二、变更清单

- **新增规则来源 30 个**：Custom_OpenClash_Rules 6 个（Custom_Direct_Domain/Custom_Direct_Classical_IP/Custom_Proxy_Domain/Custom_Proxy_Classical_IP/Steam_CDN_Classical/Custom_Port_Direct）+ pt-domains + geosite 类 23 个（discord/zoom/talkatone/xai/bing/category-ai-!cn/category-container/category-dev/category-scholar-!cn/category-speedtest/category-game-platforms-download/apple-tvplus/hbo/primevideo/dazn/viu/category-emby/bahamut/category-entertainment/paypal/category-ecommerce/category-cryptocurrency/gfw/geolocation-!cn/steam），client_interval 21600。
- **策略组 46 → 59**：新增 24（16 池中的 10 个新池 + 14 个新业务组）；改造 8（谷歌/AI/游戏/Telegram 等换链）；删除 19（六个地区 select、自建优先、Perplexity、单媒体组等——语义并入新组）。
- **规则 135 → 91**：GEOSITE 目标全部用 mrs RULE-SET 等价替换（brief 第 123 行授权）；Google 早于国外 AI、apple-tvplus 早于 apple 等关键顺序落实；AI 组链美国自建 → 家宽 → 日本自建。
- **停用来源**：因移动网络方案仍引用部分旧集合，本轮停用 0 个、全部保持启用（约束 35 停用≠删除的保守执行）；待移动网络方案下次重构后再清理。

## 三、与目标的框架性差异（按约束 1 记录）

1. private-ip 留在 MagicPanel 尾块（模板在头部第 2 位）——构建器硬校验顺序 cn → cn-ip → direct → private-ip → MATCH 不可违背；头部以 private 域名集合承担同等语义。
2. ai-cn（国内AI服务）提前到 AI 区最前（目标在第 24 位）——硬校验要求 ai-cn 早于 openai/anthropic；ai-cn 与 category-ai-!cn 不相交，提前无语义影响。
3. QUIC 规则（AND udp 443 REJECT）保留——目标模板无此规则，但这是 MagicPanel 约束 34 的定稿配置。
4. 游戏日本 UDP 池按约束 5 保留：🇯🇵 游戏 UDP 候选（hidden fallback，filter 匹配神龙机场日本 01-04）进入 🎮 游戏平台候选第二位，直连仍是默认。
5. Google 严格资格检测/自动跨区未实现（brief 明确超范围）。

## 四、发布与路由器状态（最终）

- **发布**：#353 发布生产（08:27:29），release_rev 73；生产指针 = #353 PRODUCTION。
- **路由器**：向阳已自行切换到目标模板路径——OpenClash 当前生效配置 `/etc/openclash/config/OpenClash.yaml`（07:43 更新，57 组，组清单与目标样本逐一对应：🚀 故障转移 SG 自建打头、Telegram 直连优先、新加坡媒体六合一、非标端口直连默认）。纯节点订阅地址不变，OpenClash 自动更新拉取；ZCode 未执行任何路由器写操作，真相源验收第 2 条命令由向阳自行管理。
- **设备侧**：#353 产物为全部 13 台设备的订阅源，按 profile-update-interval 自动更新；节点名变化后客户端本地选中节点需重选一次。
- **分流抽查口径**：产物规则表顺序已核对（google #50 早于 category-ai-!cn #51、apple-tvplus #59 早于 apple #60、netflix #63 早于 media #73、github #54 早于 category-dev #55、cn #85 早于 MATCH 末行）；运行时连接级抽查由向阳在 dashboard 连接页自行观察（google/youtube→🇬 谷歌服务、netflix→🇸🇬 新加坡媒体、telegram→📨 Telegram 直连、github→🚀 GitHub、cn 域名→直连、BT 非标端口→🔀 非标端口直连）。

## 五、回退路径

- 策略层：`import_policy.py --in data/router-maintenance/2026-11-21/policy-before-alignment.json`（先 dry-run）→ 重新构建发布
- DB 层：导入时自动备份 `data/magicpanel.db.before-import-*`
- 路由器层：重新执行订阅更新即回到旧产物（构建历史不可变，旧产物 #348 仍在）；极端情况用 `/etc/openclash/backup/` 现有 OpenClash 备份

## 六、优化批次（2026-11-21 追加，向阳确认立项后实施）

向阳确认两项决策后实施：设备订阅按「内网的不需要，LVSP/安卓/iOS 保留」处置；深度重构立项。

已落地：

1. **设备**：Astral-Macmini-Stash、Astral-AppleTV-Stash 已删除（内网设备走路由器主代理）；剩余 11 台 = Astral 6 台（iPhone/Android×2/MacBook/Windows×2）+ LVSP 5 台，全部保留订阅。
2. **移动网络方案归档**：variant 2 enabled=0（35 组/126 规则数据保留，可恢复）；停用后 20 份 @移动网络 产物退出构建矩阵，旧 variant 订阅请求回退默认产物（兼容窗，约束 42）。
3. **来源瘦身 141 → 63**：删除 78 个仅移动网络引用的旧来源（bm7 全家、magic-* 旧层、云服务商集合、地区专属集合等）；剩余 63 个全部被默认方案规则表或 DNS 基线引用，无无引用来源。
4. **死规则全量分析**：43 个可分析集合全量条目首命中仿真——零死集合，最高覆盖率 0.5%（cn 110177 条里 496 条被上游 Custom_Direct 先命中，属正常交叉）。规则表无垃圾条目。
5. 构建 #354 发布生产（release_rev 75），OpenClash 产物与 #353 逐行 diff 为零——设备订阅内容零变化，无网络瞬断。
6. 回归：后端 970 passed / 前端 86 passed / 16 视图冒烟全过。

单媒体组渲染器路径（_apply_service_groups）已因规则目标改为「新加坡媒体」而自然失效，代码清理延后到应用重构专项；无法全量分析的 4 个集合（Custom_Direct_Domain/Custom_Proxy_Domain 为 mrs 无文本版、magic-process/magic-reject 为小体量自维护集）语义无害。
