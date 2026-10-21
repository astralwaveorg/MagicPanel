# 全家庭代理总体方案

更新日期：2026-10-19。状态：**家庭服务迁移仍待审阅；本机已按另行授权清理其他代理，保留 Stash**。用户已购买 Stash Mac 授权，并明确计划 **Windows + 两台 macOS 均使用 Stash**。这项软件决定已纳入主方案；不能把“已购买”写成“已安装、已激活或已替换 Surge”。

完整研究、各生态比较与字段差异见[客户端选型与兼容性](Client-Selection-and-Compatibility.md)；云端实现见[远程配置管理开发规格](../development/Remote-Config-Console.md)；实时操作先读[设备运行上下文](Network-Operations-Context.md)。

## 每台设备具体运行什么

| 设备 | 最终目标 | 当前状态／要点 |
| --- | --- | --- |
| NanoPi R6S，10.0.1.1 | 仅基础路由、DHCP、普通 DNS、防火墙 | ImmortalWrt 24.10.4；不启用代理、不为代理改网关／DNS／WAN 映射；安全审阅独立处理 |
| Mac mini M4，10.0.1.8 | **Stash Mac**，可选 LAN HTTP／SOCKS 服务 | 当前仍是正常 Surge 6.8.1，NAS 已在使用；新方案未上线。无屏启动与恢复为切换前硬性验收 |
| MacBook M2 Pro | **Stash Mac**，独立客户端 | 已实查 Stash 4.4.0 运行，其他代理应用／核心已按授权卸载；Stash 扩展启用 |
| iPhone 17 Pro Max | **Stash iOS** | 已有购买；按需连接、独立出站；不依赖先回家 |
| Apple TV 4K | **Stash tvOS** | 已有 iOS 购买覆盖；用户已订购，未实查；独立代理、不作家庭网关 |
| Windows R9000K 2021 | **Stash Windows** | 用户明确选定；Windows OS 版本未核实，官方当前测试目标 Windows 11 x64；早期版需单独验收，CVR 只作恢复备选 |
| 小米 17 Pro Max，HyperOS 4 | **FlClash Android** 主用，Stash Android 试用候选 | 官方 Stash Android 仍是功能不完整的早期版；免费与否不能代表成熟或未来授权；待真实设备验收后再决定是否统一 |
| 飞牛 NAS，10.0.1.2 | 按应用继续使用 mini，不新增核心 | Debian 12、Xeon E-2176G、6C12T／32GB、有线千兆；应用／容器／daemon 消费范围待登记；不成为全家依赖 |

因此当前主线是 **五台 Stash + 一台 Android Mihomo 客户端 + NAS 按应用接入**。不以全平台同一界面牺牲稳定性；也不因旧方案选过 Mihomo 就拒绝用户已经购买的 Stash 方向。

## 购买与兼容性结论

以用户给出的 107 元／年计算约每月 8.9 元，对每天用 Mac、喜欢 Stash 体验、已有 iOS／tvOS 授权的情况值得。用户现已购买，无需再次确认或下单。官方当前 Mac 个人年费方案最多 3 台，数量可覆盖两台 Mac；具体订单档位／有效期／激活未读取。[官方价格](https://stash.ws/macos/pricing)

Mac 购买不是全平台一次解锁：iOS／tvOS 与 Mac 独立；Android 官方说明单独通过 Play 计费；Windows 当前早期版免费，未来拟与 Mac 共用桌面授权，但细则未确定。不能承诺“Windows + 两台 Mac 现在必然按同一授权计数”。[iOS](https://stash.ws/ios) · [Android](https://stash.ws/android) · [Windows](https://stash.ws/windows)

Windows 使用较少，可以先只发节点、策略组、普通分流和地区偏好；Apple 专属按需连接、Tile、未核实的脚本／重写不启用。即使同是 Stash，平台实现和成熟度也不等价。若 Windows 失败，关闭其接管恢复直连，必要时用云端生成的 CVR 备选配置；不能同时启动两份 VPN／TUN。

Stash 是自研加强内核，Mihomo 是独立核心，不是一个引擎两个名字。Android 与备用客户端需要专门渲染方言，不能把所有 YAML 当通用配置；详见[差异与官方依据](Client-Selection-and-Compatibility.md)。

## 网络结构：任何代理都不是家庭基础依赖

```text
默认路径：家庭设备 → R6S〔普通 DNS／路由〕→ 直连目标
本机代理：Stash／FlClash → R6S 或外出网络 → 机场节点
手动共享：指定应用／Wi-Fi HTTP 代理 → mini Stash → R6S → 目标
配置路径：独立云端策略源 → 按目标校验发布 → 各端 HTTPS 拉取与缓存
```

- 保留全家默认网关和基础 DNS 指向 R6S；不启用 mini／NAS／Apple TV 网关模式、透明代理或 LAN DNS 接管。
- mini 只对主动选择它的应用提供 LAN 显式代理。Stash 官方明确支持 Mac LAN HTTP／SOCKS；不要照文档另一个“网关模式”章节把家庭设备网关指向 mini。[LAN 模式说明](https://stash.wiki/features/provide-proxy-to-lan-device)
- 独立客户端直接连接机场，不强制外出回家；家庭上行按 100Mbps、下行 1000Mbps 理解，NAS／mini 千兆有线，不由 CPU 型号推断实际代理吞吐。
- 本机客户端、手动 mini 代理二选一，避免多层路径。HTTP 代理不保证全部 App／UDP／QUIC 覆盖，也不意味着安装 MitM 根证书。
- mini 停机会影响选择它的应用，包括经它再 DIRECT 的请求；关闭手动代理才能恢复原直连。未选择代理的设备应继续上网，不承诺所有已代理业务自动回退。
- 独立客户端自身 VPN／DNS 故障可能影响该设备，仍需验证关闭后的恢复；代理隔离不代表 R6S、宽带或家庭停电也无影响。

## 云端管理：同一策略源，按设备远程发布

推荐 **自有域名 + 独立 Linux VPS + 私有 Sub-Store + 目标模板 + 版本化发布**。不依赖 Stash 跨设备同步，不让 mini／NAS 是唯一发布点，不把机场订阅交给公共转换站。

1. 统一维护节点来源、个人例外、规则集合、策略组与地区偏好；Stash、Android Mihomo 从同一策略版本生成。
2. Stash 按 iPhone、MacBook、mini、TV、Windows 划分目标配置；mini 需要 LAN 入站，笔记本不默认向 LAN 开放；电视偏重视频地区，Windows 只开验证过的功能。
3. 每个设备固定专属 HTTPS 完整配置 URL；Stash 按官方服务商配置约定定时更新，Android 也导入 URL profile。配置、节点 provider、规则 provider 更新分别验收，不能只做节点订阅。
4. 一处修改，客户端随后拉取并生效；系统挂起、离线和更新周期决定延迟，不承诺即时推送。Stash 当前文档默认完整配置检查间隔 12 小时，可调整。[官方更新约定](https://stash.wiki/features/service-provider-subscription)
5. 原子发布带版本的完整配置及资源，失败保留旧版本；先单设备试用，再稳定发布。服务器“下载成功”不能冒充设备“已应用”。
6. 复用 Sub-Store 已有订阅与文件能力，Web 工作台重点补在线编辑、设备管理、复制地址／二维码、目标能力校验、灰度和回滚；不从零写内核或通用订阅解析器。

[开发文档](../development/Remote-Config-Console.md)包含技术栈、目录、数据模型、插件／规则分类、API、密钥边界、发布状态机和验收。它是规划，尚未创建云服务或应用。

## 智能与稳定的具体策略

通用、AI、视频、下载／游戏分别管理；优先固定地区与已验证出口，地区内故障切换。最低延迟不代表 AI 可登录、视频可解锁或持续带宽好；不要因几十毫秒波动频繁换国家。独立机场来源与 TCP／UDP 备选比多装几个 GUI 更能降低共同故障。

不自动向所有设备升级刚发布的客户端／核心。记录实际 App、内核、插件版本，校验后灰度；Windows 与 Android 早期版本单独验收。任何未支持规则／协议显式报告，不用静默 DIRECT 掩盖问题。

## 迁移与回退

mini 当前 Surge 正常，NAS 已在使用它；不能因买了 Stash 就停掉。先核对端口协议、鉴权和各消费者，优先兼容原 6152／6153；Stash 默认 7890 不等于必须更改所有消费者，能否保留端口／并行入口要查目标版本，不能假定 Mihomo 字段能直接使用。

mini Stash 的必须验收项：无屏重启、是否需登录、空闲／睡眠、断电恢复、授权／配置失效、LAN 限制、端口复用、NAS 业务、出口独立性。官方“开机启动”说明不能替代这些测试；若不通过，保留 Surge 并报告限制，不擅自改成自动登录或另一个核心。

实施步骤与消费者登记见[mini 迁移方案](Mac-mini-LAN-Proxy-Plan.md)。只读检查授权仍然有效，家庭方案未实施；另按明确指令完成[本机代理清理](audits/MacBook-Proxy-Cleanup.md)，没有改 mini／NAS／R6S 或停用 Surge。R6S 的[安全稳定性报告](audits/R6S-Security-Stability-Review.md)继续待独立审阅。
