# MagicPanel-默认 对齐目标形态：计划文档（2026-11-21）

真相源：`路由器/OpenClashConfig/custom/magicpanel-alignment-brief.md`；目标样本 `cfg/ClashMainConfig.ini`（只读）；现状样本 = 路由器 `/etc/openclash/config/MagicPanel.yaml`（build 300 产物，46 组 / 135 规则）。

## 一、网络架构（现状，改前确认）

- **路由器 R6S（10.0.1.1）是全屋主代理**：OpenClash 运行 MagicPanel-默认.yaml（Mihomo v1.19.34 内核），订阅来自 NAS MagicPanel，更新命令 `sh /usr/share/openclash/openclash.sh 'MagicPanel-默认'`。
- NAS（10.0.1.2）跑 MagicPanel 面板：构建产物、分发给路由器与全部设备订阅；不做日常代理。
- 家内设备（iPhone/AppleTV/Mac mini/MacBook/Windows/Android）订阅 MagicPanel 各目标产物；LVSP 设备走 Mihomo/Stash 订阅。
- 路由器是本次对齐的目标消费方；**实施全程不触碰路由器任何配置**，唯一例外是真相源验收第 2 条的订阅更新命令（在发布确认之后执行）。

## 二、目标形态与现状差异（核心清单）

### 策略组：46 → 57

| 动作 | 组 |
| --- | --- |
| 改造 | 🚀 默认代理 → 🚀 故障转移（fallback，SG 自建打头 16 级链）；🔍 谷歌服务 → 🇬 谷歌服务；🧠 人工智能 → 🤖 国外AI服务；💬 即时通讯/👥 海外社交/🪙 加密货币/🎵 TikTok → 同名 fallback 新链 |
| 新增节点池 | ♻️ 自动选择、加拿大/英国/德国/土耳其自动、🌐 其他地区自动、🏠 家宽自动、日本/美国/新加坡自建测速（双 lookahead 正则）、🚇 WireGuard |
| 新增业务组 | 📨 Telegram（直连优先 fallback）、🎧 Discord、📞 Talkatone、📹 Zoom、📺 Bahamut、⏬ PT站点、🤖 ChatGPT/Copilot/Grok/国内AI服务、🚀 GitHub、📦 容器服务、📚 学术资源、🚀 测速工具、🎥 AppleTV+、💾 OneDrive、💳 PayPal、🇸🇬 新加坡媒体（六合一 select）、🌍 国外域名、🔀 非标端口、🎯 全球直连 |
| 删除 | 🏢 自建优先、六个地区 select 组（美国/日本/台湾/韩国/新加坡/香港）、Perplexity/BBC/Twitch/Hulu/HBO Max/Bilibili 海外版/Disney+/Netflix/Netflix 日本/Prime Video/🇺🇸 Google 美国候选（语义并入新组） |
| 保留 | 🇯🇵 游戏 UDP 候选（机制保留，进 🎮 游戏平台候选第二位）、🏠 路由回家（LVSP 设备专属）、🇯🇵 日本自建（仅移动）并入新组后删除 |

### 规则：135 → 约 84 条（61 条目标语义 + MagicPanel 必要保留）

- 目标 GEOSITE 全部用 **mrs 规则集 RULE-SET 等价替换**（brief 第 123 行授权；规避 Stash 无 GEOSITE 的引擎白名单问题）
- 新增规则来源 30 个：Custom_OpenClash_Rules 6 个（直连/代理/SteamCDN/非标端口）+ pt-domains + geosite 类 23 个（xai/bing/category-ai-!cn/category-container/category-dev/category-scholar-!cn/category-speedtest/apple-tvplus/hbo/primevideo/dazn/viu/category-emby/bahamut/category-entertainment/paypal/category-ecommerce/category-cryptocurrency/gfw/discord/zoom/talkatone/geolocation-!cn）
- 停用不再引用的旧来源约 20 个（停用不删除，约束 35）
- 保留 MagicPanel 必要规则：面板域名直连 ×6、DNS DoH 出口 ×8、自建服务器 IP 直连（补新 SG IP 152.175.65.196/32）、shidongli 正则、DST-PORT 22、magic-process、QUIC 规则、路由回家 CIDR
- GEOIP,telegram/twitter/facebook/google 均带 no-resolve（满足 Fake-IP 校验）

### 硬校验冲突与处置（约束 1）

| 冲突 | 处置 |
| --- | --- |
| ai-cn（→国内AI服务）按目标在第 24 位，但硬校验要求 ai-cn 早于 openai/anthropic | ai-cn 提前到 AI 区最前（第 17 位前后），与 category-ai-!cn 不相交，无语义影响 |
| 模板 private 在最前，硬校验 private-ip 在尾块 | 按 MagicPanel 框架：private（域名）在头部第 1 位，private-ip 留尾块，记录差异 |
| 目标尾块 Custom_Port_Direct → 非标端口 | 落在硬校验 direct 位（cn → cn-ip → 非标端口 → private-ip → QUIC → MATCH），语义一致 |
| QUIC 规则（AND udp 443 REJECT）目标模板没有 | 保留（约束 34 定稿），记录差异 |

## 三、实施路径

1. **备份**：导出当前策略快照 + 生产产物到 NAS `/opt/magicpanel/data/router-maintenance/2026-11-21/`
2. **构造目标快照**（schema 2 JSON）：默认方案 = 新 57 组 + 新规则表；移动网络方案原样保留（不在本次范围）；rule_providers 全表 = 保留集 + 新增 30 集
3. `import_policy.py --dry-run` 核对 → 正式导入（自动备份数据库）
4. 构建 → 全产物校验通过（validate 顺序不变量 + Fake-IP 检查）
5. **向用户确认一次**（发布瞬断全屋网络）→ 发布测试 → 发布生产
6. 删除 Astral-PassWall-Mihomo 设备
7. 路由器订阅更新（真相源验收第 2 条命令）→ API 验收 + 分流抽查

## 四、明确不做

- Google 严格资格检测/自动跨区（brief 明确超范围）
- 路由器 cron、restore-stable-core.sh、dropbear、防火墙、网络配置、`/root/mp-final-prep/`（一律不碰）
- 单节点订阅链接（nodes feed）任何改动
- MagicPanel 应用代码的深度重构：**本轮不实施**（对齐是高风险策略变更，与应用重构同批会互相干扰验收），重构建议单独成文交用户决策

## 五、回退路径

- 策略层：`policy/snapshots/2026-11-21-before-alignment.json` 经 import_policy 回导（dry-run 先行）
- 产物层：`/opt/magicpanel/data/router-maintenance/2026-11-21/MagicPanel-默认.yaml` + 备份目录下 build 产物
- DB 层：import_policy 自动备份的 magicpanel.db 副本
- 路由器层：`/etc/openclash/backup/` 现有 OpenClash 备份机制 + 旧产物留在构建历史（构建不可变）
