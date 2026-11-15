# MagicPanel V2：开源实践与节点能力检测研究

调研截止：**2026-11-15（as of 2026-11-15）**。开源提交时间统一使用 UTC；表中固定提交是本次核对点，不是自动升级目标。

本文整合较新 Mihomo/OpenClash 实践与节点属性、服务能力探测研究，为 V2 设计提供依据。**上游事实**来自官方文档、原仓库和固定版本源码；**设计建议**表示拟采用的产品方案；**待验证**表示需要后续隔离测试或真实客户端验证。本次没有开发、部署或修改生产策略，没有执行第三方检测脚本，没有使用真实用户账号。上游支持某项能力，不代表 MagicPanel 已实现、设备已支持或用户节点已通过实测。

## 1. 已确定的产品口径

- **所有已授权来源的节点都参与自动测试、分类和排名。**自建机房、多个机场使用共同的能力标准；可用性优先，再比较信誉证据、稳定性和性能。来源类别不形成“自建永远优先”的硬排序，机场实际更适用时可以胜出，也必须能接替故障自建。
- **前台海外 AI 一个通用策略**；后台保留各产品证据。Google/Gemini 复用既有 Google 路径并严格美→新→日，不增加一排供应商前台组。
- **用户最后澄清：Google 美国 → 新加坡 → 日本严格逐级回退**；任一美国可用则留美国，各档内比较质量/稳定性，只有整档明确失败才下移。[共同契约](Google选路策略.md)取代此前仅美国的解释。
- **AI 排名完全不使用成本。**价格、流量套餐、来源付费等级和计费倍率都不进入 AI 评分、平局决策或来源优先级。住宅是否获得使用授权属于准入条件；授权后的 AI 候选仍按质量排序。成本用于流媒体经济选择、未来住宅授权与预算管理，不用于降低 AI 质量。
- **默认每周执行一次全面深检、分类和排名更新**，支持手动触发。新节点、出口变化的补测可手工执行，或由显式主动开关启用，**主动补测默认关闭**；主备主动定时健康检查同样默认关闭，显式开启后也不再次执行全套深检。
- 住宅是未来资源，未采购时保持 `planned`，不成为系统运行前提。启用后默认排除吞吐测速、全来源大流量测试、客户端通用 `url-test` 与 provider `health-check`，按独立授权预算安排小请求。
- MagicPanel 不承载用户流量。面板能约束自身探测预算、路由准入和消费估算；真正的住宅业务流量/费用硬封顶依赖上游或独立受控网关。客户端已拿到凭据且离线时，“移出候选池”不等于即时撤销凭据。
- 保留用户现有方案、策略组及规则的展示顺序和 `sort`；新设计不构成整体重排授权。先以可解释的检测结果、候选建议和影子运行验证，再经现有构建/发布链路影响客户端。

## 2. 开源项目矩阵与精确参考点

选择依据是实现、维护与可验证性，不按 star 排名。提交日期按 GitHub commit 的 committer date 核对；`pushed_at` 可能来自任意 ref，不等同默认分支最后提交，`latest`、`Alpha`、`meta` 等也不是不可变版本。

| 项目与参考分支/发布 | 固定 commit | 提交时间（UTC） | 所查许可文件 | 可借鉴 / 不直接采纳 |
| --- | --- | --- | --- | --- |
| [MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo)，稳定版 [v1.19.34](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.34) | [0455d0d28c4526937380505153e65a843d8612e8](https://github.com/MetaCubeX/mihomo/commit/0455d0d28c4526937380505153e65a843d8612e8) | 2026-11-11 05:53:39 | [GNU GPL v3 文本](https://github.com/MetaCubeX/mihomo/blob/0455d0d28c4526937380505153e65a843d8612e8/LICENSE) | 借鉴准确的解析、provider 和组语义；不把 Alpha 或 Smart fork 功能说成稳定版能力 |
| [vernesong/OpenClash](https://github.com/vernesong/OpenClash)，dev；稳定发布为 [v0.48.002](https://github.com/vernesong/OpenClash/releases/tag/v0.48.002) | [8e9b4671192ab14b3f828cb963c1ec240b09e679](https://github.com/vernesong/OpenClash/commit/8e9b4671192ab14b3f828cb963c1ec240b09e679) | 2026-11-14 16:43:28 | [MIT](https://github.com/vernesong/OpenClash/blob/8e9b4671192ab14b3f828cb963c1ec240b09e679/LICENSE) | 借鉴运行环境契约和启动覆写审计；不把订阅 YAML 等同运行 YAML；下载内核和规则另核许可 |
| [Aethersailor/Custom_OpenClash_Rules（COCR）](https://github.com/Aethersailor/Custom_OpenClash_Rules)，main | [71238e7074382aca8fa75f4465e7fd96698ea938](https://github.com/Aethersailor/Custom_OpenClash_Rules/commit/71238e7074382aca8fa75f4465e7fd96698ea938) | 2026-11-15 04:21:28 | [CC BY-SA 4.0](https://github.com/Aethersailor/Custom_OpenClash_Rules/blob/71238e7074382aca8fa75f4465e7fd96698ea938/LICENCE) | 借鉴 YAML/LuCI 职责拆分、地区识别和例外记录；其 Fake-IP/主路由/大陆绕过假设不能整套套用 |
| [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)，meta 产物分支 | [f181fff77f5f243f69bfc12b45e0fa10bed899fc](https://github.com/MetaCubeX/meta-rules-dat/commit/f181fff77f5f243f69bfc12b45e0fa10bed899fc) | 2026-11-15 02:03:48 | 所查源码 ref `4178770badecb1b349fbcd62c737e0d7a2079729` 的 [GPL v3 文本](https://github.com/MetaCubeX/meta-rules-dat/blob/4178770badecb1b349fbcd62c737e0d7a2079729/LICENSE)；输入数据另保留归属 | 借鉴同语义 YAML/MRS 与可追溯规则产物；不把通用类别直接当用户业务意图 |
| [sub-store-org/Sub-Store](https://github.com/sub-store-org/Sub-Store)，master / [2.44.15](https://github.com/sub-store-org/Sub-Store/releases/tag/2.44.15) | [7f2de2f33b1e7af6cf5e092e2d8d3d50b8eb1212](https://github.com/sub-store-org/Sub-Store/commit/7f2de2f33b1e7af6cf5e092e2d8d3d50b8eb1212) | 2026-11-15 06:12:13 | [AGPL v3 文本](https://github.com/sub-store-org/Sub-Store/blob/7f2de2f33b1e7af6cf5e092e2d8d3d50b8eb1212/LICENSE) | 借鉴解析→归一化→过滤/命名→分引擎输出；不再叠一个公共转换服务，不引入任意远程 JS |
| [vernesong/mihomo](https://github.com/vernesong/mihomo)，Smart fork / Alpha 参考 | [c4df732a2c00731ea1a7c414500d161f5810f20e](https://github.com/vernesong/mihomo/commit/c4df732a2c00731ea1a7c414500d161f5810f20e) | 2026-11-14 17:08:20 | [GNU GPL v3 文本](https://github.com/vernesong/mihomo/blob/c4df732a2c00731ea1a7c414500d161f5810f20e/LICENSE) | 研究运行时连接成功率与性能反馈；只作独立实验平台，不跨引擎直接输出 |
| [oneclickvirt/UnlockTests](https://github.com/oneclickvirt/UnlockTests)，main，非 archived | [3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972](https://github.com/oneclickvirt/UnlockTests/commit/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972) | 2026-10-26 06:22:37 | [Apache-2.0](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/LICENSE) | 优先评估结构化窄适配器；逐模块审核请求与判据，不能把其 Yes 直接当账号/播放能力 |
| [lmc999/RegionRestrictionCheck](https://github.com/lmc999/RegionRestrictionCheck)，main，非 archived | [b6d4a6f9a87fc6eae6d3e62d0092ececcec8e844](https://github.com/lmc999/RegionRestrictionCheck/commit/b6d4a6f9a87fc6eae6d3e62d0092ececcec8e844) | 2025-12-08 03:20:40 | [AGPL-3.0](https://github.com/lmc999/RegionRestrictionCheck/blob/b6d4a6f9a87fc6eae6d3e62d0092ececcec8e844/LICENSE) | 广覆盖服务清单与人工对照；末次提交主要是推广文案，不代表所有检测近期修复，不作为全套定时脚本 |
| [xykt/IPQuality](https://github.com/xykt/IPQuality)，main，非 archived | [8e685686e1df89119d9aeb182a9dedbc88da19e3](https://github.com/xykt/IPQuality/commit/8e685686e1df89119d9aeb182a9dedbc88da19e3) | 2026-11-07 02:58:20 | [AGPL-3.0](https://github.com/xykt/IPQuality/blob/8e685686e1df89119d9aeb182a9dedbc88da19e3/LICENSE) | 多源 IP 属性交叉检查思路；不照搬总分、默认在线报告或黑名单/邮件全套扫描 |

本次稳定版 Mihomo 的 LICENSE 是 GPL v3，而所查仓库 API 元数据曾返回 MIT；RegionRestrictionCheck 的 README badge 写 GPL，而 LICENSE 标为 AGPL。**采用版本的具体许可文件优先于 badge、仓库摘要和项目名。**表中的 GPL/AGPL 文本名称不替代逐文件的授权范围判断。

RegionRestrictionCheck README 指向的历史上游 [CoiaPrant/MediaUnlock_Test](https://github.com/CoiaPrant/MediaUnlock_Test) 本次返回 404，未能核对现状与许可，不作为新依赖。较新的提交也不证明单项服务判据正确；未来接入时仍须跑版本化的正反样本。

## 3. DNS、provider、规则与策略组的跨引擎边界

### 3.1 同一策略意图分别编译

| 议题 | Mihomo 官方稳定版/当前文档 | Stash 当前官方文档 | 对 MagicPanel 的要求 |
| --- | --- | --- | --- |
| DNS 模式与链路 | `fake-ip` / `redir-host`；`respect-rules`；节点 bootstrap、`direct-nameserver` 等有各自职责 | 默认给应用 Fake-IP；DNS 跟随规则是 `follow-rule`，节点域名有独立解析链路 | 不靠字段同名猜等价；节点解析、国内直连、海外服务、家庭域分别定义意图 |
| provider 健康检查 | provider `health-check` 与组测试任务相关，固定版本存在下节所述文档/源码差异 | provider 有 `benchmark-url` / `benchmark-timeout`；组按自己的定时测试语义运行 | 分别生成字段并测实际行为；住宅的全部测试入口都要排除 |
| 自动选择/回退 | `url-test` 按指定端点延迟选，`fallback` 按顺序选可用成员 | 同名组有相近基本用途，但字段与运行行为独立 | 204 连通不等于服务能力；候选排名先由后台能力证据形成 |
| `relay` / 链式代理 | 所查 v1.19.34 解析器明确拒绝 `relay`，提示使用 `dialer-proxy` | 官方组文档仍列出 `relay`，节点也有代理链能力 | 不给两个引擎共用一份 relay YAML，不把“两个名字能串起来”当跨引擎兼容 |
| Smart | 官方稳定版解析器没有 `smart` 类型；OpenClash 提供的是独立 fork pre-release | 没有核实与该 fork 等价的能力 | 单独的 Mihomo 实验目标、版本与回滚路径；不下发给 Stash |
| MRS | `domain` / `ipcidr` 支持，`classical` 不支持 MRS | 当前文档同样支持 domain/ipcidr MRS | 以实际客户端版本验证；不能笼统写“Stash 不支持 MRS” |
| 空池 | 当前 Mihomo 文档有 `empty-fallback`，默认 `COMPATIBLE`；行为须按固定版验证 | 空远程代理集和空策略组都可能按 `DIRECT` 处理 | 构建和运行都检查有效成员；必须代理的业务不得因动态空池静默直连 |
| 规则附加参数/类型 | 依 Mihomo 白名单 | Stash 有 `no-track`、`pre-matching` 等，且部分带最低版本条件 | 每引擎独立白名单与版本门禁，不把未知字段“被忽略”当支持 |

上表依据：[Mihomo DNS](https://wiki.metacubex.one/config/dns/)、[Stash DNS](https://stash.wiki/features/dns-server)、[Mihomo provider](https://wiki.metacubex.one/config/proxy-providers/)、[Stash provider](https://stash.wiki/proxy-protocols/proxy-providers)、[Mihomo 固定版组解析器](https://github.com/MetaCubeX/mihomo/blob/0455d0d28c4526937380505153e65a843d8612e8/adapter/outboundgroup/parser.go#L187)、[Stash 策略组](https://stash.wiki/proxy-protocols/proxy-groups)、[Mihomo MRS](https://wiki.metacubex.one/config/rule-providers/)、[Stash MRS](https://stash.wiki/rules/rule-set)。这些都是上游能力记录，未确认用户已安装版本具备所有新字段。

### 3.2 provider 测试与 `urltestprovider` 议题

**已核事实：**当前 [Mihomo 组文档的 `url` 段落](https://wiki.metacubex.one/config/proxy-groups/#url)写明只检查显式 `proxies`，不检查 `use` 引入的 provider；但固定 v1.19.34 源码在显式组 URL 存在时，会调用 `addTestUrlToProviders`，并向 provider 注册健康检查任务。[源码调用位置](https://github.com/MetaCubeX/mihomo/blob/0455d0d28c4526937380505153e65a843d8612e8/adapter/outboundgroup/parser.go#L139)、[注册实现](https://github.com/MetaCubeX/mihomo/blob/0455d0d28c4526937380505153e65a843d8612e8/adapter/outboundgroup/parser.go#L251)

两者不能合并成“provider 永远不受组 URL 测试”或“所有 provider 一定测过”的笼统结论。应将显式 URL、provider 自带 URL、组类型、测试间隔、lazy 与实际安装版本组合验证，检查测试记录、候选变化和是否重复发请求。关于 `urltestprovider` 的讨论在本文归入 provider 健康检查议题；本次所查稳定版结构和官网没有该名称的通用 YAML 开关，**不据此生成 `urltestprovider` / `url-test-provider` 字段**。

### 3.3 DNS 与 OpenClash 的运行环境契约

官方 DNS 说明提供了域名规则与解析流程的区别；域名已命中代理时可交给代理解析，IP 规则可能先触发本地解析。节点域名必须有独立可达的 bootstrap，避免“先连代理才能解析代理”。国内服务保持国内可达解析，家庭域交给真正拥有内网答案的解析器；不通过堆很多上游解决职责不明。[Mihomo 解析流程](https://wiki.metacubex.one/config/dns/diagram/)

OpenClash 固定 dev 源码会依据 UCI 改写 DNS 模式、监听和嗅探等；面板产物中有 Fake-IP 不证明路由器正在运行 Fake-IP。实施时比较“面板意图 → 构建产物 → 下载原件 → 启动后的运行 YAML → 实际命中”。路由器的大陆 IP 绕过发生在内核外，可能让强制代理规则根本没有匹配机会，IPv4/IPv6 需要同时核对。[OpenClash 覆写源码](https://github.com/vernesong/OpenClash/blob/8e9b4671192ab14b3f828cb963c1ec240b09e679/luci-app-openclash/root/usr/share/openclash/yml_change.sh#L580)

**家庭网络设计建议：**以独立于代理核心的 real-IP DNS、`redir-host` 候选和显式基础联网故障模式开展验证，不将全屋全量 Fake-IP 作为优先方案。客户端缓存的 Fake-IP 可能在核心故障后继续依赖核心，不能仅切防火墙就宣称恢复全屋直连。先盘点 AdGuard Home、dnsmasq、OpenClash 的链路和回环风险，并通过核心退出、DNS 故障、旧缓存与 IPv4/IPv6 故障矩阵。Fake-IP 保留为终端配置与实验候选，须通过相同故障验收。Stash 的 `follow-rule` 不应仅为“统一字段”而全局开启；其官方说明也提示递归和 CDN 选择影响。

### 3.4 首命中、QUIC 与规则内容

两引擎普通规则从上往下首条命中。IP-ASN 反映目标网络，不是某个 AI 产品的身份；把云 ASN、共享认证/存储/CDN 域放到宽泛 AI 表头，会抢占媒体、开发和国内例外。AI 前台统一策略也不改变这个边界。按真实产物模拟首个命中，只修经确认的局部冲突，保留现有排序。[Mihomo 规则](https://wiki.metacubex.one/config/rules/)、[Stash 规则](https://stash.wiki/rules/rule-types)

`redir-port` 仅接管 TCP；Linux TProxy 可接管 TCP/UDP。未进入核心的 UDP 不会被 YAML 拒绝规则拦住。仅对已证明代理 UDP 不可靠的服务考虑 UDP/443 拒绝，让支持的应用回退 TCP；规则必须早于相应服务放行，不能全局封掉游戏/通话 UDP。UDP/443 只是常见 QUIC 条件，不能当完整协议识别。[Mihomo 端口](https://wiki.metacubex.one/config/inbound/port/)、[Stash 高效配置](https://stash.wiki/faq/effective-stash)

`pre-matching` 是提前拒绝机制，不是一般顺序错误的补丁；普通规则中的先行 DIRECT 未必保护它覆盖的例外。保留诊断连接证据，避免先加 `no-track` 把问题隐藏。规则行为与内容同时核对：domain 不解释 `DOMAIN-SUFFIX,...` 这类 classical 行；MRS 不承载混合 classical。项目小型自维护混合集合保留 classical，`ipcidr` 按既有约束加 `no-resolve`，`cn-ip` 保留允许解析的项目例外。

<!-- smart-review:start -->
### 3.5 Smart：自动转换、实际行为与受控取舍

**结论：默认不开全局自动Smart，仅保留独立实验目标。** 本节追加研究不改变每日分地区小样本、异常有界扩大和周深检的最新检测策略；Smart不能绕过国家、账号粘性、来源授权与探测预算。官方稳定Mihomo和Stash仍各用各自已核能力，不能因R6S有Smart二进制就向所有目标输出`type: smart`。

**现场事实（2026-11-15追加只读）：** R6S实际为`alpha-smart-g96feb2a`（构建时间2026-11-06 20:09:55 UTC），对应[完整源码ref 96feb2a175eb65b05ae2a60d222a279f90990695](https://github.com/vernesong/mihomo/commit/96feb2a175eb65b05ae2a60d222a279f90990695)，与本研究矩阵的后续`c4df732a2c00731ea1a7c414500d161f5810f20e`分开记录。UCI仅`smart_enable=1/core_type=Smart`；自动Smart转换、LGBM、采集、ASN偏好等开关未设置。当前活动运行YAML只有select 2/fallback 1/url-test 3，无smart组/Smart字段；实际工作目录没有Model.bin。故当前是“使用Smart fork运行普通组”，不是“已经在用Smart/LGBM自动优选”。没有切换、更新、下载模型或输出节点/controller secret。

**自动转换的准确范围：** [OpenClash yml_rules_change.sh @ 8e9b467](https://github.com/vernesong/OpenClash/blob/8e9b4671192ab14b3f828cb963c1ec240b09e679/luci-app-openclash/root/usr/share/openclash/yml_rules_change.sh#L407)与现场安装脚本的相关块一致：`auto_smart_switch=1`将url-test/load-balance转smart，保留其成员；select/fallback不直接转换。之后可对smart写入`collectdata/sample-rate/policy-priority/uselightgbm/prefer-asn/tolerance`。这会覆盖Google/AI依赖的隐藏子组，不能只比较前台组类型。`smart_enable`选择核心，与这个转换开关不同。上述UCI为0通常仅停止覆写，不清除外来配置已有Smart字段；顶层模型自动更新同样须检查最终值。[顶层LGBM覆写](https://github.com/vernesong/OpenClash/blob/8e9b4671192ab14b3f828cb963c1ec240b09e679/luci-app-openclash/root/usr/share/openclash/yml_change.sh#L518)

**源码事实与含义：**

| 事实/固定来源 | 对本项目的具体含义 |
| --- | --- |
| [SmartOption/NewSmart/InitSmart，运行ref](https://github.com/vernesong/mihomo/blob/96feb2a175eb65b05ae2a60d222a279f90990695/adapter/outboundgroup/smart.go)按域/目标网络与历史连接反馈选路、重试，含后台稳定/恢复/目标检查和主动probe | 不是只看一次ping，也不是纯被动无额外请求；provider/组健康任务与Smart自身任务分开统计。多连接选择不保证一个账号/API/静态域名族固定同一出口 |
| [组解析器 @ c4df732](https://github.com/vernesong/mihomo/blob/c4df732a2c00731ea1a7c414500d161f5810f20e/adapter/outboundgroup/parser.go#L152)对非select/relay的兼容provider可把interval=0归为300秒，显式组URL可注册provider检查 | 不拿0/lazy/周interval当“所有测试已关闭”；必须看具体成员模式与实际增量连接数，不暗恢复全库循环测速 |
| [权重输入 @ c4df732](https://github.com/vernesong/mihomo/blob/c4df732a2c00731ea1a7c414500d161f5810f20e/component/smart/weight.go)包含连接成功、延迟、吞吐、时长、目标网络及出口等特征 | 这是网络反馈评分，不是IP信誉、住宅真实性、账号/DRM或模型权限判定；不能继承为服务解锁Yes，也不以来源/价格名称权重替代AI质量证据 |
| [运行ref模型GetModel](https://github.com/vernesong/mihomo/blob/96feb2a175eb65b05ae2a60d222a279f90990695/component/smart/lightgbm/lightgbm.go#L539)在模型缺失/损坏时尝试下载；所查Smart组初始化在uselightgbm=true时调用它 | 关闭lgbm-auto-update不等于不会首次下载。预加载/配置检查须独立目录、禁网和模型digest；运行文件存在也不等于预测确实参与选路 |
| [运行ref构造函数](https://github.com/vernesong/mihomo/blob/96feb2a175eb65b05ae2a60d222a279f90990695/adapter/outboundgroup/smart.go#L184)采样率缺省1，只接受大于0且不超过1的覆写；采集由collectdata控制 | sample-rate=0不能禁采集。训练数据可能含目的域/IP与节点标识，按私密运行数据处理，不进仓库/普通DTO，不默认启用 |

**设计推断：** 全局转换没有服务白名单；country软权重不能编码“完整US耗尽才SG、完整SG耗尽才JP”。若成员严格限定同一当前允许国家，Smart不会凭空生成另一国节点，但也不能凭局部连通失败证明全档业务耗尽。因此首版Google及其递归子组保持非Smart；AI/账号风控/版权媒体同样保留中心合格池和稳定出口。首次仅允许同国2–3个已合格节点的无账号通用静态下载实验组，不包含住宅、DNS专用角色、回家/管理/DIRECT或混国隐藏组。

**有限实验门槛：** 先不用LGBM/collector/名称权重，关闭全局自动转换；独立实例、目录、缓存与授权来源，记录额外主动连接/请求/字节，超已审小样本预算即停。国家/首命中/空池/国内8/10秒故障case全部通过；至少3个同WAN时段可重复对照收益，成功率不低于对照、TTFB P95不劣，48小时灰度无关键会话无故换出口。模型实验另核代码/权重文件许可、发布/模型版本和SHA，不追滚动release自动更新。回滚整套binary/配置/组成员/资源及仅实验的Smart状态，不仅是LuCI开关；本轮没有进行这些实验。[家庭执行边界](家庭网络运行契约.md#9-openclashmihomo-与-smart-的明确选择)
<!-- smart-review:end -->

## 4. 检测分层：属性、网络、服务、真实体验分别记录

| 层级 | 可自动观测 | 不能由此推出 |
| --- | --- | --- |
| L0 资源档案 | 来源、原始名、稳定 ID、接入协议、运营者声明类别、授权用途 | 名字写“US/家宽/原生”就是真实落地或住宅 |
| L1 真实出口与属性 | 经指定节点的小型出口回显、IP family、ASN/组织、GeoIP、数据商风险声明及版本 | 入口 IP 等于出口；ASN 证明住宅；多个协议是多个独立出口 |
| L2 路径与协议 | DNS、TCP/UDP、TLS、HTTP 版本、超时/首字节、短采样性能 | NAS 成功等于路由器/手机/tvOS 成功；204 成功等于业务成功 |
| L3 公开服务入口 | 首页/API 认证环节、明确地区/代理拒绝、有限公开地区/目录线索 | 登录、付费权益、模型额度、完整片库、DRM 或账号信誉 |
| L4 实际设备体验 | 用户主动确认的具体应用、操作、内容、地区、持续时间 | 一次成功证明所有设备、未来会话或全部服务永久可用 |

**入口与出口必须分开。**节点 `server` 是连接入口；中转、代理链、服务定向出站会使出口不同。一个 IP 查询站只证明到该站的出口；服务地区证据独立保存，不能把回显 US 自动继承给所有目的站。同出口的多条协议可共享 ASN 属性，协议健康仍分别检测；同机同 IP 不构成独立容灾。

**住宅与纯净度不是网络事实的简单二分。**MaxMind 的住宅代理标签描述疑似匿名网络与住宅 ISP，并提供置信度、最近观测和共享基础设施误判说明；IPinfo 也使用观测窗口与 last seen。没有标记不等于没有滥用史，住宅标签不等于优质服务信誉。保存每个数据商声明、数据版本、置信度、观测时间和分歧，不平均不同量表的欺诈分数，也不把邮件黑名单直接转成 AI 风险结论。[MaxMind 字段](https://dev.maxmind.com/geoip/docs/databases/anonymous-ip/binary/)、[MaxMind 置信度](https://support.maxmind.com/knowledge-base/articles/anonymizer-and-proxy-data-maxmind)、[IPinfo 观察窗口](https://ipinfo.io/developers/residential-proxy-api)、[IPinfo Extended](https://ipinfo.io/developers/privacy-extended-api)

### 4.1 结果状态与证据关联

传输维度使用 `reachable / timeout / dns-error / tls-error / connection-error`；业务结果维度独立，不能压成一个“可用灯”：

| 结果 | 解释 | 对排名/运维的含义 |
| --- | --- | --- |
| `observed-ok` | 仅在本 probe scope 得到预期证据，例如“公开首页可达” | 不升级成账号或真实播放能力 |
| `auth-required` | 到达认证环节，需要凭据或授权 | 传输可达；业务能力未知，不是失败，也不是已通过 |
| `blocked` | 有拒绝证据 | reason 区分 `geo-explicit / proxy-explicit / access-denied-unspecified`；一个 403 不猜成 IP 脏 |
| `challenge` | JS/WAF/验证码挑战 | 记录并停止，不刷出口撞探，不尝试绕过 |
| `rate-limited` | 429 或明确限流 | 按 Retry-After/退避处理，不标为永久坏节点 |
| `unknown` | 响应改版、字段缺失、冲突或判据不足 | 保留原因；不能默认 Yes 或 No |
| `stale` | 旧证据超过使用期限 | 旧值可查看，不能冒充当前结果 |
| `not-tested / skipped` | 尚未测或因禁测、预算等未执行 | 显示覆盖缺口，不能静默当作节点失败 |
| `manual-confirmed` | 用户主动确认的设备/操作与时间 | 有范围、有时效，与自动证据并列 |

OpenAI 官方将 401 认证、403 不支持地区、429 限流/额度区分；无凭据 401 不证明 API 推理可用。Reddit 官方也说明 hosted netblock 可能必须 OAuth/登录，因此匿名受限不能直接推断信誉差。Cloudflare `cf-mitigated: challenge` 可以作为挑战页证据，200 还需检查内容与预期结构；缺少该头不证明没有其他 WAF。[OpenAI 错误](https://developers.openai.com/api/docs/guides/error-codes)、[Reddit 接入](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data)、[Cloudflare Challenge](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)

每条观测关联 `node_ref + egress_id + observer + path_fingerprint + probe/version + measured_at + valid_until`。路径至少包含核心版本、接入协议、代理链、DNS 路径、IPv4/IPv6、HTTP 协议和关键配置版本；指纹/日志不得包含原始凭据。出口或路径变化使对应证据失效，保留历史供解释。

## 5. 统一 AI 能力矩阵与媒体排名

### 5.1 AI 一套前台策略，后台保留多项事实

能力注册表覆盖用户指定的全部海外 AI，明确网页、API、桌面客户端等产品差异。Claude/GPT/Muse/Grok 是矩阵中的不同列，不是新增前台策略组；新服务没有可靠 probe 时必须标 unknown，不能借用 OpenAI 成功补齐。Muse 的具体产品入口尚待确认，不能猜成某个同名站点后发探测。矩阵也可保留服务域名族与共享依赖的边界，避免整段云 ASN 误归 AI。

### 5.1.1 Google 全业务覆盖与地区优先验证

下表是需版本化扩充的覆盖起点，**不是穷尽规则包或已实测清单**。每项都要覆盖页面、认证、API、静态/下载、必要长连接与平台差异。

| 产品族 | 代表域名与需扩展的依赖 |
| --- | --- |
| 搜索、Scholar、新闻、翻译、地图 | `google.com` 及地区域名、`scholar.google.com`、`news.google.com`、`translate.google.com`、`maps.google.com` |
| 账号与 OAuth | `accounts.google.com`、`oauth2.googleapis.com`、`myaccount.google.com`；第三方应用调用 Google 登录也属此依赖 |
| Gemini、AI Studio、NotebookLM | `gemini.google.com`、`aistudio.google.com`、`generativelanguage.googleapis.com`、`notebooklm.google.com`、经核实的产品 API |
| Gmail、Calendar、Chat、Meet、Groups | `gmail.com`、`googlemail.com`、`mail.google.com` 及相应产品端点；邮件非 443 协议、Meet UDP 单列 |
| Drive、Docs/Sheets/Slides、Sites、Takeout | 相应 `*.google.com` 产品域、`drive.usercontent.google.com` 及下载/协作依赖 |
| YouTube、Music/TV/Kids、嵌入播放 | `youtube.com`、`youtu.be`、`youtube-nocookie.com`、`youtubekids.com`、`googlevideo.com`、`ytimg.com`、`ggpht.com`、`youtube.googleapis.com` |
| Photos、One、Play、Android/Chrome 更新 | `photos.google.com`、`one.google.com`、`play.google.com`、`android.clients.google.com`、`update.googleapis.com` 及核实的下载域 |
| FCM/注册/推送 | `mtalk*.google.com`、`android.apis.google.com`、`device-provisioning.googleapis.com`、`firebaseinstallations.googleapis.com` |
| 自营开发与云控制面 | `cloud.google.com`、`console.cloud.google.com`、`developers.google.com`、`ai.google.dev`、明确的自营 API；第三方云客户不因托管商自动纳入 |
| 关联依赖 | 经核实的 `gstatic.com`、`googleusercontent.com`、字体、reCAPTCHA、Safe Browsing、PKI、Public DNS、Ads/Analytics/Tag Manager；已有 REJECT 维持，放行时必须美国 |

一手依据：[Gemini API](https://ai.google.dev/api/generate-content?hl=en)、[Workspace Drive 网络要求](https://knowledge.workspace.google.com/admin/drive/drive-and-sites-firewall-and-proxy-settings?hl=en)、[固定版本 YouTube 集合](https://github.com/MetaCubeX/meta-rules-dat/blob/f181fff77f5f243f69bfc12b45e0fa10bed899fc/geo/geosite/youtube.yaml)。国家域、`googleapis.cn` 等国内形式域名也不能仅凭后缀获得直连豁免，应按真实归属审定。

FCM 常见 TCP 5228–5230/443，官方还说明其可能绕过允许 bypass 的 VPN；Meet 存在 UDP 媒体路径。只写 Google HTTP/443 规则不满足完整要求，需检查手机 VPN bypass、端口/进程直连、路由器 UDP、IPv6 与长连接。[FCM 官方网络要求](https://firebase.google.com/docs/cloud-messaging/network-configuration)、[Meet 官方网络要求](https://knowledge.workspace.google.com/admin/meet/prepare-your-network-for-meet-meetings-and-live-streams?hl=en)

固定上游 `google.yaml` 本身含 `+.run.app`。`run.app`、`appspot.com`、`web.app`、`firebaseapp.com`、`cloudfunctions.net` 等共享托管后缀以及整个 Google ASN 不等于全部 Google 自营业务；应审查归属，以第三方云客户作负例，不能整包置顶后宣称完成精确覆盖。[固定 Google 集合](https://github.com/MetaCubeX/meta-rules-dat/blob/f181fff77f5f243f69bfc12b45e0fa10bed899fc/geo/geosite/google.yaml)

各档地区资格追踪“首命中→可见组→递归叶节点/代理链→目的范围出口”，不能只凭节点名/入口/语言/账号地区；分别留美国、新加坡、日本证据。目录绑定 ref/hash/回归版本，不宣称静态表穷尽。

通用健康推荐受控非 Google 目标，避免与服务可用性混淆；Google 专项允许在美国、新加坡、日本候选执行。整档耗尽需完整适用候选证据，未测/限流/预算跳过/适配器异常不算全部美国失败。网关整体故障政策另审，不把地区偏好升级为额外全模式绝对美国阻断。

**建议决策次序：**先确认资源授权与明确可用性；再比较所需 AI 的覆盖和证据完整性、信誉线索、近期成功率与连续失败、出口/长会话稳定性，最后比较时延和性能。为当前合格出口设置防抖保持；部分满足与证据不足单列。**全程不读取成本字段作为 AI 排名输入**；自建与机场都按同一质量证据竞争。

统一候选次序可供前台使用，但后台必须保存向量与排序原因。不能把一个加权总分隐藏成“纯净度”，也不能让极低延迟补偿某个必要 AI 的明确拒绝。所需产品覆盖范围、最低证据等级和允许地区应显式设置，避免“所有 AI”被无法验证的边缘产品永久卡住；默认覆盖用户指定产品，不擅自删减。

技术证据与服务资格声明独立：Anthropic **2026-11-12 生效**的地区政策比旧帮助页更新，且覆盖实际所在地等条件；出口识别为 US/JP 不自动证明账号资格。ChatGPT 也有官方支持地区清单。面板只展示观测的技术范围，不把住宅或出口国家当作账号能力承诺。[Anthropic 当前政策](https://www.anthropic.com/legal/supported-regions)、[ChatGPT 支持地区](https://help.openai.com/en/articles/7947663-chatgpt-supported-countries)

### 5.2 Apple TV 与流媒体按服务、地区和持续体验选路

Apple TV 硬件是一台运行多种应用的设备，不能用一个“Apple TV 解锁”布尔值代表 Netflix、Disney+、Apple TV 服务及第三方频道。服务能力分别记录地区、目录线索、实际播放、DRM/清晰度与持续体验；地区内比较合格线路，成本可在流媒体合格候选间参与经济选择，不能为了便宜跳到内容不匹配地区。

Netflix 公开目录页能提供有限线索，官方说明 VPN 连接可能只显示全球授权内容；首页或少数片名页面不证明完整播放。Apple 官方也区分 App、订阅、体育以及租借/第三方权益。真实播放受账号、订阅、DRM、设备和 CDN 影响，无账号探测保留“未验证”。持续播放验收建议由用户在自己设备主动进行，记录具体服务/内容/地区、连续时长、重缓冲和出口变化，而不是让后台偷偷下载长视频。[Netflix 官方说明](https://help.netflix.com/en/node/114701)、[Apple TV 权益与地区](https://support.apple.com/en-ie/118404)

登录开发服务、Reddit/TikTok 同样重视出口稳定和域名族一致性；TikTok 推荐还受交互、语言、设备与位置等因素影响，网络探测不能推算推荐质量或账号风控结果。[TikTok 推荐机制](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content)

## 6. 默认每周全面深检，基础健康与补测分开

| 任务 | 默认触发 | 范围与结果 |
| --- | --- | --- |
| 全面深检、分类、排名 | **每周一次**；可手动运行 | 全部已授权来源节点进入队列；逐节点检查协议/路径，按实际出口去重属性查询；覆盖配置的 AI/媒体等能力矩阵 |
| 新节点/出口变化补测 | 手工执行；或显式主动开关启用，**默认关闭** | 对受影响节点/能力补测，不重测无关全池；未主动补测的等待周检，状态如实标未测/过期 |
| 基础健康 | 主备主动定时检查默认关闭；显式开启后仅小池小请求 | 仅判断轻量连通与故障恢复，不重跑风险数据库/全服务/吞吐任务；旧生产检查另经审查迁移 |
| 故障复核 | 被动事件默认仅记录/提示；手工诊断或 M5 独立开启自动复核后执行 | 设备/事件来源授权不等于启用自动复核；有限重试、范围补测、退避；probe 自身故障不等同所有节点故障，无遥测设备不假定即时恢复 |
| 未来住宅 | 独立授权、使用时复核及小请求计划 | 默认无吞吐、无通用 url-test/provider 健康检查；未授权不因 AI 候选耗尽被启用 |

周检是任务周期，不要求所有节点同时向同一站发请求。每节点都进入可追踪队列，按来源/地区/真实出口错峰；尚未轮到或限流暂停必须显示覆盖进度和原因，不因抽样就把未测节点永久排除。同出口的属性查询可以去重，协议连通性不能合并；入口看起来相同也不能未经确认就去重出口能力。

能力记录默认有效至下一轮周检的预定到期时间，并显示测量年龄；明确失败、出口/协议/DNS 改变可提前失效。网络健康的时效更短，由实际运行检查更新。周检样本不承诺一周内服务必定可用，也不通过设置 6–12 小时 TTL 暗中把默认深检变成每日多轮。

**探测预算示例（设计初值）：**单节点一次非吞吐深检可预约最多 20 次请求、2 MiB 载荷/任务总上限，含重定向次数、超时、单响应与解压后体积限制；300 节点一轮的预约上限约 600 MiB。实际应先用少量自有小端点测开销再调参数，握手、代理封装、重传需额外留余量。若未来非住宅吞吐短采样启用，应独立授权与计量，不能把几 MiB 短样本称作晚高峰持续带宽保证。

住宅的示例上限可从单次 256 KiB、少量请求起步，默认吞吐 0；具体数值由购买方案与用户授权确定，不把此示例当费用承诺。面板在调度前预约探测请求/字节/API 次数，超额跳过，完成后用进程/接口或核心流量核算；HTTP Range/HEAD 可能被忽略或返回不同结果，必须在流式读取处硬截断。

第三方数据 API 的调用额度影响探测任务调度，不能作为 AI 质量分数。业务住宅硬配额必须由上游/网关执行；面板消费估算有延迟，客户端离线和已下发凭据不受候选池即时控制。

## 7. 稳定会话、故障恢复与空池保护

以下为相应自动化显式启用后的设计；默认周计划、主动健康检查关闭且设备无反馈时，不能承诺即时自动切换。旧生产的 600 秒检查不在本次文档阶段直接修改。

1. 统一 AI 及账号敏感服务保持当前合格出口，延迟小幅变化、单次 probe 超时、unknown 不立即换 IP。切换理由应是明确不可用或经验证的质量变化，不能因来源类别阻止机场胜出。
2. 协议故障优先选择同出口的健康协议；整机/出口故障再选独立故障域。多条同 IP 协议不能虚增容灾数量。备选必须有足够新鲜的相应能力证据，地区变化需符合服务要求。
3. 可用作影子运行起点的阈值：连接失败连续 2–3 次、间隔复核；恢复连续 3 次成功并有 30–60 分钟冷却。它们是待调参数，不是当前实现；服务挑战/限流不能变成换大量 IP 连续撞探。
4. 切换通常影响新连接，不保证已建 TLS/WebSocket/HTTP3 会话不断；默认不批量断开连接。设备端实际重连与业务体验另外验收。
5. 构建检查每个方案/平台的有效成员；运行时也检查动态 provider 更新后的成员。Stash 空 provider/空组可能 DIRECT，因此必须代理业务要有明确、真实的备用与耗尽提示，不能只套一个空隐藏组。
6. 区分“零有效成员”“所有成员健康失败”“provider 更新失败但缓存仍在”“正则/重命名导致零匹配”；四者不能统一处理成删除。来源更新失败不应用空文件覆盖上次良好内容。
7. AI/媒体/社交域名族的认证、API、静态资源与必要 CDN 保持审定的一致出口边界；通用云/认证/遥测域不全局独占。用首命中模拟和客户端实际命中检查抢占，参考此前只读诊断中的 TikTok 域名族分裂案例。[历史诊断](../network/2026-11-15-代理配置深度诊断与优化方案.md)

## 8. 检测适配器的技术与许可边界

### 8.1 已抽查模块的判据局限

| 固定 UnlockTests 模块 | 当前实现能说明的事 | 本产品采用界限 |
| --- | --- | --- |
| [Claude.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/Claude.go) / [AIStatus.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/AIStatus.go) | 首页、trace、状态码与国家表的启发式结果 | 映射为入口/地区证据，不当作登录、付费能力或账号资格 |
| [ChatGPT.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/ChatGPT.go) | 混合 cookie requirements、旧 iOS 域与 trace | 不直接复制未公开稳定性的端点、模拟头和跨产品 Yes 判定；优先正式公开接口与清楚 scope |
| [Apple.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/Apple.go) | Apple 地区端点线索 | 不能标成“Apple TV 已解锁” |
| [Netflix.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/Netflix.go) | 少量片名页面/字段与 CDN 线索 | 不等于实际播放；不复制内置第三方令牌；页面改版归 unknown |
| [Reddit.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/Reddit.go) / [TikTok.go](https://github.com/oneclickvirt/UnlockTests/blob/3df881bbde0bf4eb56787b4eb9e6ea53b3ffd972/transnation/TikTok.go) | 匿名页面状态与地区字段 | 不推导账号信誉、App 视频和推荐能力；认证要求独立 |

### 8.2 推荐接入方式

采用“MagicPanel 自有窄接口 → 版本化受控 adapter → 可选受限 worker”。每个 probe 声明用途、目标 allowlist、方法、scope、版本、许可/来源、最大请求/字节/时间、解析证据与失败分类。不执行远程下载后直接运行的脚本，不允许自动安装依赖、更新自身或上传报告，不把订阅送到公共转换站。

Apache-2.0 模块仍需检查依赖与被复制文件的来源，保留许可与必要 NOTICE；GPL/AGPL/CC 内容按采用的 ref/具体文件记录归属、修改和分发方式。复制/修改 AGPL 组件并通过网络提供服务时，需确认相应源码提供义务，**进程或容器隔离本身不免除许可要求**。先借鉴行为和接口设计与复制上游实现是不同动作；未来确需复制时再按具体组合核对，不能只凭仓库 badge 下结论。

worker 不挂载生产数据库、Docker socket、宿主根目录或完整凭据库；仅取得任务需要的临时连接引用，输出版本化、脱敏 JSON。节点凭据、订阅 URL、cookie、Authorization 不进入证据和日志。限制重定向目的地、内网访问与响应体积，避免 adapter 变成任意网络请求入口。

请求使用可识别的产品身份；无账户探测遇认证、验证码或挑战即返回相应状态，不使用真实用户会话。Reddit Data API 本身需要获准接入与认证，不能把匿名抓取当免费健康检查。[Reddit Data API](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki)、[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)

## 9. 建议的数据与交付结构

下表是设计建议，不是当前数据库；未来字段变更走幂等迁移。

| 数据对象 | 必要内容 | 约束 |
| --- | --- | --- |
| 资源档案 | 稳定资源/节点 ID、来源、原始/展示名、声明类别、授权、planned/active、用途 | 来源后缀防重名；不靠名称推断地区/住宅 |
| 出口观测 | 实际 IP/family、目标范围、observer、路径指纹、时间 | 入口/出口分开；同 IP 多协议属性可共享、健康不共享 |
| 属性声明 | 数据商、dataset/version、值、置信度、last seen、获取/失效时间 | 保留分歧，不合成“绝对纯净” |
| 能力观测 | 产品/scope、probe/version、传输与结果状态、reason、地区、HTTP、时效、流量、摘要 | unknown/auth-required 不自动计为成功；默认不保存完整响应或 cookie |
| 周检任务 | 周期/触发原因、全节点队列、覆盖进度、跳过/退避、版本 | 默认每周；部分失败可继续，不能因探测器坏了清空全池 |
| 排名建议 | AI 统一次序/媒体服务地区次序、完整向量、理由、输入证据、有效期 | AI 不读成本；所有来源按质量竞争；当前发布配置独立 |
| 预算账本 | 探测预留/实际请求字节、第三方调用额度、住宅授权/消费估算 | 明确只有探测预算能由面板直接硬控；业务硬封顶依赖执行端 |
| 构建证据 | 规则内容 hash、来源 ref、核心/编译器版本、快照 digest、设备验证 | 固定来源、可回滚，不以滚动 latest 代替不可变证据 |

建议先完成可解释观测和影子排名，再决定自动生成候选的方式；共同策略意图分别输出 Mihomo/Stash，OpenClash 另有运行环境契约。Smart 仅作为可选择的实验目标。失败状态不能静默转成 DIRECT，旧发布和最后一次良好来源内容保留到可安全替换。

## 10. 来源表

以下为本研究使用的主要一手来源，访问日期均为 2026-11-15；固定版本与许可另见第 2、8 节。官网内容会继续变化，实施时需结合实际客户端版本复核。

| 类别 | 一手来源 | 支持的结论 |
| --- | --- | --- |
| Mihomo DNS | [DNS 配置](https://wiki.metacubex.one/config/dns/)、[解析流程](https://wiki.metacubex.one/config/dns/diagram/) | 模式、解析职责与路由的关系 |
| Mihomo provider/组 | [provider](https://wiki.metacubex.one/config/proxy-providers/)、[组字段](https://wiki.metacubex.one/config/proxy-groups/)、[url-test](https://wiki.metacubex.one/config/proxy-groups/url-test/)、[fallback](https://wiki.metacubex.one/config/proxy-groups/fallback/) | 健康检查、显式成员/来源、过滤与顺序语义 |
| Mihomo 固定源码 | [parser.go @ 0455d0d](https://github.com/MetaCubeX/mihomo/blob/0455d0d28c4526937380505153e65a843d8612e8/adapter/outboundgroup/parser.go) | relay 移除、无官方稳定 smart、组 URL 注册 provider 测试任务 |
| 规则与接管 | [Mihomo 规则](https://wiki.metacubex.one/config/rules/)、[规则集合](https://wiki.metacubex.one/config/rule-providers/)、[入站端口](https://wiki.metacubex.one/config/inbound/port/) | 首命中、MRS 行为边界、TCP/UDP 接管 |
| Stash | [DNS](https://stash.wiki/features/dns-server)、[provider](https://stash.wiki/proxy-protocols/proxy-providers)、[组](https://stash.wiki/proxy-protocols/proxy-groups)、[规则](https://stash.wiki/rules/rule-types)、[规则集合](https://stash.wiki/rules/rule-set) | 跨引擎字段、版本条件、空池 DIRECT、MRS |
| OpenClash/Smart | [启动覆写固定源码](https://github.com/vernesong/OpenClash/blob/8e9b4671192ab14b3f828cb963c1ec240b09e679/luci-app-openclash/root/usr/share/openclash/yml_change.sh)、[Smart pre-release](https://github.com/vernesong/OpenClash/releases/tag/mihomo) | 下载原件与运行文件不同；Smart 来自独立 fork |
| COCR | [固定 YAML 说明](https://github.com/Aethersailor/Custom_OpenClash_Rules/blob/71238e7074382aca8fa75f4465e7fd96698ea938/cfg/yaml/README.md)、[官方项目 wiki](https://github.com/Aethersailor/Custom_OpenClash_Rules/wiki/OpenClash-%E8%AE%BE%E7%BD%AE%E6%96%B9%E6%A1%88) | 配置职责和适用前提；不整体替代用户方案 |
| Sub-Store | [固定 processors](https://github.com/sub-store-org/Sub-Store/blob/7f2de2f33b1e7af6cf5e092e2d8d3d50b8eb1212/backend/src/core/proxy-utils/processors/index.js)、[producers](https://github.com/sub-store-org/Sub-Store/tree/7f2de2f33b1e7af6cf5e092e2d8d3d50b8eb1212/backend/src/core/proxy-utils/producers) | 归一化、命名、按引擎输出的流水线 |
| IP 属性 | [MaxMind 字段](https://dev.maxmind.com/geoip/docs/databases/anonymous-ip/binary/)、[置信度与误判](https://support.maxmind.com/knowledge-base/articles/anonymizer-and-proxy-data-maxmind)、[IPinfo Residential](https://ipinfo.io/developers/residential-proxy-api)、[Extended](https://ipinfo.io/developers/privacy-extended-api) | 住宅代理标签、时效、置信度、数据商分歧 |
| AI 官方 | [OpenAI 错误](https://developers.openai.com/api/docs/guides/error-codes)、[ChatGPT 地区](https://help.openai.com/en/articles/7947663-chatgpt-supported-countries)、[Anthropic 当前政策](https://www.anthropic.com/legal/supported-regions) | 认证/地区/额度不同，出口不能证明账号资格 |
| 媒体官方 | [Netflix VPN 说明](https://help.netflix.com/en/node/114701)、[Apple TV 订阅与地区](https://support.apple.com/en-ie/118404) | 公开目录、播放、账号权益和设备体验分开 |
| 社交与挑战 | [Reddit hosted netblock 接入](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data)、[TikTok 推荐机制](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content)、[Cloudflare Challenge](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/) | 匿名拒绝、账号体验和 WAF 状态的边界 |

## 11. 待验证清单

- [ ] 记录实际 Mihomo/OpenClash/Stash 版本、核心 fork 与能力；官网新字段不直接当作设备已有。
- [ ] 对 Mihomo provider 测试的文档/源码差异做最小隔离实验：组显式/空 URL、provider URL、lazy、interval、use/proxies、重复请求、住宅排除；不生成未确认的 `urltestprovider` 字段。
- [ ] 在批准测试环境加载 Mihomo/Stash 产物，验证 relay/dialer-proxy、MRS、健康检查字段和规则参数，不依赖静态 YAML 通过。
- [ ] 测试四种空池/故障：来源失败保留缓存、正则零匹配、空 provider/组、所有成员不健康；必须代理业务不静默 DIRECT。
- [ ] 核对 R6S 启动后 DNS/IPv6/TCP/UDP 接管、大陆绕过与嗅探；独立 real-IP DNS、redir-host 候选及基础联网故障模式须通过核心退出/DNS 失败/旧缓存故障矩阵，不能假定全屋 Fake-IP 可无感退直连。
- [ ] 对国内业务、AI/Google、TikTok、共享 CDN/云 ASN、家庭域和媒体地区服务做首命中模拟；只做获准局部调整，不重排现有整表。
- [ ] probe 样本覆盖正常 200、200 挑战、401、明确/不明确 403、429、登录 302、字段消失、TLS/DNS/超时、IPv6 和不同协议；未知内容必须 unknown。
- [ ] 模拟 probe 整体改版或服务整体故障，不能把全部节点清空；可单独停用坏 probe，保留最近事实与覆盖缺口。
- [ ] 统一 AI 矩阵覆盖用户指定产品；单 OpenAI 成功不代替全 AI，AI 排名输入/平局逻辑完全不使用成本，机场能在同标准下胜出和接替。
- [ ] 默认周检覆盖全部已授权节点，队列错峰和暂停原因可见；新节点/出口变化主动补测默认关闭，补测不暗中升级成高频全套扫描；同出口属性去重不吞掉协议测试。
- [ ] 验证真实出口与入口区分、按目的站分流、同 IP 多协议与不同 observer 的证据不会互相错误继承。
- [ ] 在用户自己的实际设备主动验证媒体地区与持续播放，记录内容/地区/时长/重缓冲，不把目录可见或 Apple 地区端点当全播放证明。
- [ ] 验证住宅默认无吞吐、无通用 url-test/provider health-check；预算并发预留、体积截断、退避与禁测真实生效；业务硬配额必须确认执行端。
- [ ] 复核拟采用 adapter 的固定 ref、文件许可证/NOTICE、依赖、网络目标和隐私行为；不执行远程脚本，不复制内置第三方令牌，不记录真实账号会话。
- [ ] 影子运行覆盖日常与晚高峰，检查误判、切换抖动、实际探测流量和回滚；通过既有发布与客户端验收后，才启用自动候选更新。
