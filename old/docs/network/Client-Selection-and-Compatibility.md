# 各平台客户端选型与兼容性决策

调研日期：2026-10-19；状态：供审阅；用户已购买 Mac 授权，本机已查 Stash 4.4.0 运行并完成其他代理卸载，其他设备安装与家庭迁移未实查。本文取代“按用户最初列出的客户端直接定案”的选型方式。现网事实见[运行上下文](Network-Operations-Context.md)。

## 选择标准与证据边界

按基础网络故障隔离、真实协议兼容、长期恢复能力、日常体验、远程配置维护成本排序。用户已确认购买 Stash Mac 授权，明确计划 Windows + 两台 macOS 都用 Stash；Windows 使用较少、可精简功能。购买是用户确认，MacBook 已实查 Stash 运行；账户激活数量与其他设备迁移尚未检查。

比较覆盖 Mihomo、Stash、sing-box、Xray 生态及 Apple 平台主要独立客户端，不以下载量、星数或“最新发布”作为稳定性证明。官方文档能证明声明的功能、限制与发布状态，不能证明在 HyperOS 4 上不被杀后台、特定机场永远可用或本家庭跑满千兆。下面是基于资料的明确推荐，最终部署仍要通过文末验收，不是全网实测冠军榜。

## 最终方案：落实已购买授权，五台主设备使用 Stash

| 设备 | 推荐运行什么 | 具体使用方式与理由 |
| --- | --- | --- |
| iPhone 17 Pro Max | **Stash iOS** | 已有授权；规则、按需连接、诊断与远程完整配置匹配需求；外出直接连机场 |
| MacBook M2 Pro | **Stash Mac，授权已购买** | 用户明确采用；原生网络集成与 Apple 端体验匹配需求。不依赖 iCloud 同步，订阅云端 MacBook 配置 |
| Apple TV 4K | **Stash tvOS** | 已有 iOS 购买覆盖；独立运行，云端下发 TV 配置，固定流媒体地区；不作家庭网关 |
| 小米 17 Pro Max | **FlClash Android arm64** | Mihomo、远程配置、按应用代理、快捷开关兼顾兼容与操作；保留 CMFA 为替换候选。Stash Android 暂作试用 |
| Windows R9000K | **Stash Windows** | 按用户最新选择；先使用共同节点与分流，关闭未经验证的专属功能；早期版本需验收，CVR x64 仅作恢复备选 |
| Mac mini M4 | **Stash Mac** | 按用户最新选择提供手动 LAN HTTP／SOCKS；不使用网关模式、不接管 LAN DNS。重点验收无人登录启动、重启与空闲恢复，未通过前保留 Surge |
| 飞牛 NAS | **继续按应用使用 mini 代理，不新增代理核心** | 登记应用、Docker daemon、容器各自作用域；不成为全家关键设备；保存加密备份 |
| NanoPi R6S | **只做基础路由，无代理** | 保留网关／DHCP／基础 DNS，代理失效不能影响未选择代理的家庭设备 |

五台 Stash 设备是 iPhone、Apple TV、MacBook、Mac mini、Windows。Android 仍建议 FlClash 主用、Stash Android 试用，因此保留 **Stash 与 Mihomo 两种输出**；Windows 的 Mihomo 输出仅用于 CVR 备选。统一的是云端策略与维护入口，不强求逐字相同 YAML。现有 Surge 继续正常服务 NAS；用户已决定软件方向，不等于已实施迁移。

免费路线的比较结论保留作后备：MacBook 可用 **Clash Verge Rev**，**ClashBar** 则是原生菜单栏轻量备选，两者都能订阅完整配置。它们不再是已购买 Stash 后的主方案。本机已按后续指令卸载 ClashBar／独立 Mihomo，不为保留备选而重新安装。

## 107 元年费与“全平台授权”分别判断

**用户已购买；下述只解释额度与边界，不再次要求购买。** 官方当前个人年费为 £12／最多 3 台设备，家庭 £18／6 台，终身 £48／6 台且写明 Stash 4。107 元是用户提供的成交价假设，不是本文核实的人民币官方价；税费、汇率和续费以结算为准。两台 Mac 数量在个人额度内；具体购买档位／有效期和已激活数量以用户账户为准，本文未读取订单。[官方价格](https://stash.ws/macos/pricing)

| 平台 | 买 Mac 年费后是什么情况 |
| --- | --- |
| macOS | 独立 Mac 授权；个人计划当前最多 3 台 |
| iOS／tvOS | 用户已有的一次性 App Store 购买覆盖，和 Mac 授权分开 |
| Android | 当前为早期版；官方说明 Google Play 单独计费，不能承诺永久免费或被 Mac 授权覆盖 |
| Windows | 当前早期版本免费；官方计划未来与 macOS 合为桌面授权，但时间、价格细则尚未确定，不能当作已兑现权益 |

以上来自 [iOS 授权说明](https://stash.ws/ios)、[Android 现状](https://stash.ws/android)、[Windows 现状与授权计划](https://stash.ws/windows)。因此“Stash 有各平台版本”成立，“买 Mac 就能获得全平台成熟、等价体验”不成立。Windows 官方目前测试目标为 Windows 11 x64；用户的 Windows 版本还未知。

Mac mini 的目标已改为 **Stash Mac**。官方明确支持 LAN HTTP／SOCKS 和开机启动，但这不足以证明未登录会话也能恢复代理；需验证无人登录启动、断电／空闲恢复、授权／更新失败和端口控制。现有快照中 FileVault 关闭，实施前再核对，不应为启动 GUI 擅自开启自动登录。[LAN 官方文档](https://stash.wiki/features/provide-proxy-to-lan-device) · [Mac 启动说明](https://stash.wiki/stash-mac)

若这项验收不通过，记录具体限制并保留现有 Surge，向用户提出受控替代方案；独立 Mihomo 仅为后备，不未经用户选择重新改回主方案。

## 开放比较后的取舍

| 候选路线 | 已核实的能力／定位 | 本家庭为什么选择或不作为主线 |
| --- | --- | --- |
| [Stash](https://stash.wiki/) | 自研加强内核、Clash 标准基础加扩展；Apple 网络集成、按需连接、HTTP 引擎 | Apple 主选；不是 Mihomo 换皮。Android／Windows 官方仍标早期；用户选择 Windows 使用 Stash，Android 暂保留稳定候选 |
| [Shadowrocket](https://apps.apple.com/us/app/shadowrocket/id932747118) | Apple 客户端，App Store 显示丰富协议与持续更新，包含 Apple TV | 有力备选，不应被说成协议少；但仍要维护自身配置方言，已有 Stash 无明显迁移收益 |
| [Loon](https://nsloon.app/en/docs/General/)／[Quantumult X](https://github.com/crossutility/Quantumult-X) | 分流、脚本／重写生态及各自配置模型 | HTTP 自动化需求很强时有价值；本任务主要是稳定代理与统一配置，引入新方言没有足够收益；不假定所有新协议均支持 |
| [Egern](https://egernapp.com/docs/configuration/example/) | 自身 YAML 配置、模块、脚本与订阅管理 | YAML 不代表 Mihomo 方言；是 Apple 体验候选，而不是无需适配的全平台方案 |
| [Surge](https://manual.nssurge.com/policies/overview.html) | 当前已有 HY2、AnyTLS、TUIC 等，不能沿用旧的协议印象 | 仍有自己的协议矩阵／配置体系，不能保证所有机场 VLESS 组合；现有 mini 保留到迁移，不重新围绕它做全家主线 |
| [ClashMi](https://github.com/KaringX/clashmi) | Mihomo 路线，覆盖 iOS 等多平台，原生 YAML 配置 | 进一步统一内核的强候选；但不能由引擎名称推出 Apple 后台体验和 Stash 等价。Mihomo 官方客户端表另提示其构建不可复现限制 |
| [ProjectClash](https://github.com/ProjectClash/Clash-Client) | iOS／macOS／tvOS 原生客户端，独立 Mihomo 派生核心与适配层 | Apple 上不止 Stash 可选；但要核对客户端锁定的核心提交，SDK 标签不等于商店版本。暂不为减少一种模板就替换已合用的 Stash |
| [FlClash](https://github.com/chen08209/FlClash)／[CMFA](https://github.com/MetaCubeX/ClashMetaForAndroid) | Android Mihomo 生态；FlClash 有远程完整配置、编辑、按应用代理和快捷开关 | FlClash 是 Android 主选，CMFA 为备选；HyperOS 后台恢复要设备验收，不能凭功能清单判断耗电 |
| [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev) | Windows／Mac／Linux，Mihomo、远程配置、Merge／Script、系统代理与 TUN | Windows 恢复备选及 Mac 免费备选；云端业务规则为权威，避免客户端本地脚本产生第二份规则源 |
| [ClashBar](https://github.com/Sitoi/ClashBar) | macOS 原生菜单栏、系统代理／TUN、远程核心管理、完整配置定时更新、SSID 配置绑定 | 轻量原生备选；SSID 绑定不是已经证明能自动关闭所有代理／VPN |
| [Sparkle](https://github.com/xishang0128/sparkle) | Electron Mihomo GUI，覆写与 Sub-Store 集成 | 值得比较的桌面替代，尤其偏爱本地订阅处理时；本方案云端做权威，不需每台桌面再维护独立 Sub-Store |
| [sing-box 官方客户端](https://sing-box.sagernet.org/clients/) | 官方列出 Android、Apple 含 tvOS、Windows／Linux；原生 JSON，有自己的规则集模型 | **完整可行的另一条主线**，不是因平台不齐被排除。若从零开始追求同源内核可优先评估；本家庭已有规则、Stash 体验与授权，迁移整个配置模型收益不足 |
| [Karing](https://github.com/KaringX/karing)／[Hiddify](https://github.com/hiddify/hiddify-app) | 面向易用连接的跨平台路线 | 导入 Clash 订阅不等于完整执行全部 Mihomo／Stash 语义；无法只凭“一键导入”承诺脚本、DNS、链式代理无损 |
| [v2rayN](https://github.com/2dust/v2rayN)／[v2rayNG](https://github.com/2dust/v2rayNG)／[NekoBox](https://github.com/MatsuriDayo/NekoBoxForAndroid) | Xray／sing-box 相关生态，适合对应核心与特定协议组合 | 当实际机场要求的传输不被目标客户端支持时有价值；全家统一规则仍需额外适配，不作为默认安装集合 |

传统单协议 VPN、商业 VPN 客户端不提供本任务需要的机场协议和规则编排能力；Tailscale 等远程组网用于维护网络，不替代机场客户端。全世界客户端无法有限时间穷举，本次覆盖的是能改变本家庭决策的主要路线；不宣称未列出的产品一定更差。

### 已核对的发布基线

以下是调研时正式发布入口的快照，**不是要求立即升级**，也不是所有 GUI 内置核心版本：

| 项目 | 版本／日期 | 官方发布入口 |
| --- | --- | --- |
| Stash iOS 商店 | 3.6.3／10-14 | [App Store](https://apps.apple.com/us/app/stash-rule-based-proxy/id1596063349) |
| Mihomo | 1.19.32／09-30 | [Release](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.32) |
| CVR | 2.5.8／10-09 | [Release](https://github.com/clash-verge-rev/clash-verge-rev/releases/tag/v2.5.8) |
| FlClash | 0.9.1／10-17 | [Release](https://github.com/chen08209/FlClash/releases/tag/v0.9.1) |
| CMFA | 2.11.35／09-30 | [Release](https://github.com/MetaCubeX/ClashMetaForAndroid/releases/tag/v2.11.35) |
| ClashBar | 0.3.6／09-30 | [Release](https://github.com/Sitoi/ClashBar/releases/tag/v0.3.6) |
| ClashMi | 1.0.31.1703／10-09 | [Release](https://github.com/KaringX/clashmi/releases/tag/v1.0.31.1703) |
| Sparkle | 1.26.9／09-30 | [Release](https://github.com/xishang0128/sparkle/releases/tag/1.26.9) |
| Sub-Store | 2.42.6／10-18 | [Release](https://github.com/sub-store-org/Sub-Store/releases/tag/2.42.6) |

FlClash 0.9.1 刚发布两天，发布说明包含桌面 TUN 设置行为变化；Android 主选不意味着直接向所有设备推最新版。Stash Mac／tvOS 分别登记实际安装版本，不能照搬 iOS 版本；ProjectClash 客户端 README 明确各商店版本分别维护、客户端源码没有独立发布标签。[Mihomo 客户端表](https://wiki.metacubex.one/en/startup/client/client/)也明确第三方客户端不一定包含最新核心。

## Mihomo 与 Stash：共享配置基础，不是同一个引擎

Stash 官方称自研加强内核，Mihomo 是独立开源核心。“兼容 Clash 标准”不能推出对方所有后来扩展都兼容。协议、传输、安全参数、策略语义、平台接管方式必须分别判断。

| 层面 | 真实差异与处理 |
| --- | --- |
| 节点协议 | 两者有大量交集，包括 SS／VMess／Trojan／VLESS／HY2／TUIC 等；但不能由协议名相同推出字段、版本、插件及传输等价。每个节点按目标版本编译与测试 |
| 新协议／传输 | 当前两份官方文档都列有 VLESS Encryption／XHTTP，不能写成“Stash 不支持 VLESS／Reality”或“Mihomo 一定缺 XHTTP”；按客户端内置核心、服务端参数与传输组合验证 |
| TLS 参数 | Mihomo VLESS 示例使用 `servername`；Stash 通用字段使用 `sni`。映射需按具体协议定义，不能全局替换键名 |
| 节点 provider | Mihomo 鉴权字段 `header`，Stash `headers`；更新与测速字段分别生成，不原样复制 |
| 规则 provider | domain／ipcidr 的 YAML／text 是首期共享基础；当前 Stash 也支持 domain／ipcidr MRS。复杂规则类型逐项校验，不宣称任意 classical 规则都跨端通用 |
| DNS／接管 | Mihomo 的 `tun` 和 DNS 字段不能当成 Stash Apple Network Extension 的同义配置；Apple、Android、Windows、共享服务器分别有模板 |
| HTTP 脚本／插件 | Stash HTTP 引擎、MitM、重写、Tile／定时脚本不是普通 Mihomo 路由功能；CVR 的 JS 是配置加工脚本，也不是 Stash HTTP 请求脚本运行时 |
| UDP／QUIC | TCP 连通不足以证明 UDP。Stash 文档注明默认限制代理转发 QUIC，需按目标业务核对；不要误写成两端行为天然一致或所有 QUIC 协议不可用 |
| 策略组／链路 | 选取共同策略语义，检测循环／空组；链式代理必须分别参考官方。禁止只改协议名称或把不支持功能悄悄降级成 DIRECT |

依据：[Stash 协议字段](https://stash.wiki/proxy-protocols/proxy-types)、[Mihomo VLESS](https://wiki.metacubex.one/config/proxies/vless/)、[Mihomo 传输](https://wiki.metacubex.one/config/proxies/transport/)、[Stash provider](https://stash.wiki/proxy-protocols/proxy-providers)、[Mihomo provider](https://wiki.metacubex.one/config/proxy-providers/)、[Stash 规则集](https://stash.wiki/rules/rule-set)、[Mihomo 规则集](https://wiki.metacubex.one/config/rule-providers/)。上述是差异检查清单，不是已经完成的转换器。

节点兼容键应至少包含 `协议 + 版本/加密 + 传输 + TLS/Reality + UDP封装 + 插件 + 客户端/核心版本 + 平台`。实际机场协议清单尚未取得，不能断言已覆盖全部订阅；不需要用户把含密码订阅贴到文档，后续本地脱敏检查即可。

### Windows 的 Stash 精简配置与恢复备选

Windows 主用 **Stash Windows**，从共同 Stash 策略生成独立 Windows 配置，保留节点、个人例外、LAN 直连、国内／国外分流、地区偏好、域名拒绝和已验证故障切换；先不发 Stash Apple 专用按需连接、Tile、未确认支持的脚本／MitM。官方声明共享 YAML 不等于早期版本已经实现所有 Apple 功能，必须在目标版本检查。

Windows 使用少降低的是功能需求，不降低协议正确性。若 Stash Windows 未通过休眠、TUN／服务恢复或节点测试，先关闭它恢复直连；需要代理时可用已验证 CVR 候选，另输出 Mihomo 配置，共享业务规则，仅移除明确不支持的功能。CVR 是恢复选项，不和 Stash 同时接管系统代理／TUN。此阶段仍保留一份 Mihomo 适配器，主要用于 Android 和备用。

## 让“智能”服务稳定，而不是频繁换出口

- 默认按业务分组：通用代理、AI、流媒体、下载／游戏；AI 与视频优先稳定地区，地区内再故障切换，避免最低延迟轻微变化就切国家。
- `url-test` 只测指定探测目标，不证明 AI 登录、流媒体解锁或真实带宽；智能测速不能等同于自动解锁。锁定已验证节点，失败后切同地区备用，再切备用来源。
- 手机按需连接、Android 按应用／快捷开关减少手动操作；SSID 检测只作为便利条件，不是可信网络鉴权，出门切换及位置权限要实测。
- 在家本机客户端和 mini 手动代理二选一；不要把手机订阅指向 mini 内网地址再期望出门可用。
- Android 的 VpnService 通常每个用户／资料只允许一个活动服务；不承诺 FlClash 与独立 Tailscale 同时启用。[Android 官方](https://developer.android.com/develop/connectivity/vpn)

## 统一管理必须真正覆盖完整配置

所有设备导入自己的固定 HTTPS 配置 URL，云端从共同规则与节点源渲染。Stash 同步可以不启用，绝不是系统权威来源。

| 目标 | 已确认的远程完整配置路径 | 仍需验收 |
| --- | --- | --- |
| Stash | 服务商配置首行 `#SUBSCRIBED <自己的完整配置URL>`；官方当前默认检查 12 小时，可在设置调整 | 各平台后台调度、当前连接重新加载、失效配置保留；不承诺秒级同步 |
| CVR | Remote profile；2.5.8 源码有自动更新开关、`update_interval` 与 `profile-update-interval` 处理 | 启用更新，核对本地 Merge／GUI 最终运行配置是否覆盖云端 |
| FlClash | URL profile，0.9.1 源码有自动更新开关和间隔设置 | HyperOS 省电下的调度、失败保留与重连 |
| ClashBar 备选 | 0.3.6 文档明确完整 YAML 订阅及按小时后台更新 | 本地设置优先级、重启连接影响 |
| mini Stash Mac | 使用自己的 Stash 服务商配置 URL，与 MacBook 区分入站／共享参数 | 无屏启动、配置更新后共享端口仍可用；不能仅凭 App 下载成功判定服务恢复 |
| 独立 Mihomo 后备 | 若以后选用，**另建拉取器**：下载、校验、备份、受控重载 | 不假定核心会自动替换顶层配置；当前不部署 |

原始依据：[Stash 更新约定](https://stash.wiki/features/service-provider-subscription)、[CVR 2.5.8 配置源码](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.5.8/src-tauri/src/config/prfitem.rs)、[FlClash 0.9.1 配置模型](https://github.com/chen08209/FlClash/blob/v0.9.1/lib/models/profile.dart)、[ClashBar 配置文档](https://github.com/Sitoi/ClashBar/blob/v0.3.6/docs/content/docs/configuration.mdx)。

“修改一处、所有地方生效”指单一来源、各端随后拉取；完整配置、节点 provider、规则 provider 是三种更新。离线／被系统挂起设备不会即时更新。服务器能知道成功下载，不能仅凭 HTTP 200 知道客户端已加载、VPN 已启动或策略已生效。

## 选型落地前的验收

1. 脱敏清点机场协议和传输；每类节点在目标客户端验证 TCP、DNS、UDP／QUIC 与证书，失败时记录具体组合，不泛称“Clash 不兼容”。
2. Stash Mac 授权已购买；验证 MacBook 休眠、网络切换、LAN／NAS、退出后 DNS 恢复；核对实际授权与激活数量，不再下单。
3. Android 验证锁屏一夜、Wi-Fi／蜂窝转换、HyperOS 自启动与省电权限、自动更新；记录电量条件，不编造耗电排名。
4. Windows 核实 OS 与 Stash 版本，验收游戏／UDP、后台服务、休眠恢复、TUN 关闭恢复；Apple 专属／未实现功能明确可见，CVR 后备单独验收。
5. Apple TV 到货后验收商店安装、订阅导入、待机恢复、视频地区；不把用户订购信息当硬件已检测。
6. mini 按[迁移方案](Mac-mini-LAN-Proxy-Plan.md)登记 NAS 消费者、保留 Surge、验证无屏启动／重启和稳定端口；不能只凭 M4 性能判定服务更可靠。
7. 云端关机、订阅 404／超时、空节点、坏 YAML、规则集失效时保留最后有效版本；未使用代理设备继续通过 R6S 正常联网。测试只在后续实施范围内进行。

云端工具选型、开发边界、数据结构与发布协议见[远程配置管理开发方案](../development/Remote-Config-Console.md)。
