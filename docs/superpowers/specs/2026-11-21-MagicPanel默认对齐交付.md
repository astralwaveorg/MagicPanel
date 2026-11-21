# MagicPanel-默认 对齐交付（2026-11-21）

状态：**构建 #353 已通过全部硬校验，停在发布确认门**——按需求约束 3「发布生效前先向用户确认一次（发布瞬断全屋网络）」，确认问题已发出未获回复，发布动作等待用户一句话确认。确认后的完整执行步骤见文末「待执行」。

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

## 四、待执行（用户确认发布后）

```bash
# 1) 发布（面板 API 或界面：构建 #353 → 发布测试 → 发布生产）
# 2) 路由器订阅更新（真相源验收第 2 条；这是唯一触碰路由器的动作，仅执行该命令）
ssh root@10.0.1.1 "sh /usr/share/openclash/openclash.sh 'MagicPanel-默认'"
# 3) API 验收
ssh root@10.0.1.1 'SECRET=$(uci -q get openclash.config.dashboard_password); curl -s -H "Authorization: Bearer $SECRET" http://127.0.0.1:9090/proxies | python3 -m json.tool | grep -E "\"🇬 谷歌服务|\"🇸🇬 新加坡媒体|\"🚇 WireGuard"'
# 4) 分流抽查（dashboard 连接页）：google/youtube→🇬 谷歌服务；netflix→🇸🇬 新加坡媒体；
#    telegram→📨 Telegram（直连）；github→🚀 GitHub；qq.com→直连；BT 非标端口→🔀 非标端口（直连）
```

## 五、回退路径

- 策略层：`import_policy.py --in data/router-maintenance/2026-11-21/policy-before-alignment.json`（先 dry-run）→ 重新构建发布
- DB 层：导入时自动备份 `data/magicpanel.db.before-import-*`
- 路由器层：重新执行订阅更新即回到旧产物（构建历史不可变，旧产物 #348 仍在）；极端情况用 `/etc/openclash/backup/` 现有 OpenClash 备份

## 六、深度重构建议（本轮未实施，待用户决策）

对齐后 MagicPanel 的「多引擎全功能」形态与实际用途（路由器 OpenClash 主代理 + 少量设备订阅）之间有明显简化空间，建议单独立项：

1. 规则来源去重：对齐后 141 个来源里 77 个停用待清理；自维护 magic-* 层与上游 geosite 大量重叠（magic-google vs google、magic-us vs 美国自动筛选），可合并瘦身。
2. 移动网络方案（variant 2）是旧结构的完整副本（35 组/126 规则），对齐后与默认方案差异巨大——建议要么按新形态重做，要么停用归档。
3. 单媒体组机制（Netflix 日本/Disney+/HBO 等 10 个组）在新形态下被「新加坡媒体」六合一取代，渲染器的服务别名机制（_apply_service_groups）可大幅简化。
4. 探测流水线的 35 平台矩阵可裁剪到与分流目标匹配的 12-15 项（Netflix/Disney/ChatGPT/Claude/Gemini/Telegram 等）。
5. 文案已按 humanizer 口径全面过一轮；重构界面时同步复查。
