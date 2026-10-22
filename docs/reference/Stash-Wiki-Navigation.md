# Stash Wiki 查阅导航

核对日期：2026-10-19。用于本仓库中 Stash 配置维护和后续代理查阅。

已交叉核对[官网侧栏](https://stash.wiki/)、[站点地图](https://stash.wiki/sitemap-0.xml)和[官方 AI 索引](https://stash.wiki/llms.txt)，并读取各页面正文与章节标题。下表覆盖 44 个中文页面及其 44 个英文对应页面，核对时全部返回 HTTP 200。英文版本单独列出，便于对照术语；不包含站外购买、社交媒体及图片资源。

## 查阅方法

- 修改本仓库的 Stash 配置时，先查配置样例，再查对应功能页。本仓库不存放客户端配置样例，样例以官方文档与 `official-example/` 为准。
- 按任务定位下方入口；查具体参数时打开原文，不把导航摘要当作完整配置规范。
- 涉及兼容性时，同时核对目标平台更新日志和功能页中的最低版本／Beta 标记。
- 本文是链接索引，更新后应重新核对；Stash、Mihomo 和 Surge 的扩展字段需分别确认支持情况。

## 按任务快速定位

| 要处理的任务 | 优先阅读 |
| --- | --- |
| 编写或调整 YAML | [配置样例](https://stash.wiki/configuration/example-config) → [覆写](https://stash.wiki/configuration/override) |
| 节点订阅、筛选、自动切换 | [远程代理集](https://stash.wiki/proxy-protocols/proxy-providers) → [策略组](https://stash.wiki/proxy-protocols/proxy-groups) → [延迟测试](https://stash.wiki/proxy-protocols/proxy-benchmark) |
| 添加分流或远程规则 | [规则类型](https://stash.wiki/rules/rule-types) → [规则集合](https://stash.wiki/rules/rule-set) |
| 排查 DNS、Fake-IP、解析回环 | [DNS 服务](https://stash.wiki/features/dns-server) → [主机名映射](https://stash.wiki/features/hosts) → [IPv6](https://stash.wiki/faq/ipv6-compatible) |
| HTTPS 改写／脚本不生效 | [HTTP 引擎](https://stash.wiki/http-engine/intro) → [MitM](https://stash.wiki/http-engine/mitm) → [强制 HTTP 引擎](https://stash.wiki/http-engine/force-http-engine) → [改写脚本](https://stash.wiki/script/rewrite-requests) |
| 内网互联、家庭出口、网关 | [内网穿透](https://stash.wiki/features/nat-traversal) → [局域网代理](https://stash.wiki/features/provide-proxy-to-lan-device) |
| 远程控制或自动化 | [HTTP API](https://stash.wiki/features/http-api)／[URL Schema](https://stash.wiki/faq/url-schema)／[定时任务](https://stash.wiki/script/scheduled-tasks) |
| 闪退、耗电、吞吐问题 | [高效配置](https://stash.wiki/faq/effective-stash) → [网络性能](https://stash.wiki/features/network-performance-enhance) → 对应平台更新日志 |

## 全站页面导航

### 入门与平台

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [Stash 简介](https://stash.wiki/) | 了解产品覆盖的平台与主要能力。 | [EN](https://stash.wiki/en) |
| [快速上手](https://stash.wiki/get-started) | 查找远程订阅、本地文件的导入入口。 | [EN](https://stash.wiki/en/get-started) |
| [Stash Mac](https://stash.wiki/stash-mac) | 查找 Mac 原生功能、进程分流和网关模式。 | [EN](https://stash.wiki/en/stash-mac) |

### 更新日志

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [iOS 更新日志](https://stash.wiki/release-notes/ios) | 核对 iOS 版本的功能变更与修复。 | [EN](https://stash.wiki/en/release-notes/ios) |
| [macOS 更新日志](https://stash.wiki/release-notes/macos) | 核对 Mac 版本的功能变更与修复。 | [EN](https://stash.wiki/en/release-notes/macos) |
| [tvOS 更新日志](https://stash.wiki/release-notes/tvos) | 核对 Apple TV 版本的功能变更与修复。 | [EN](https://stash.wiki/en/release-notes/tvos) |

### 配置文件

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [配置样例](https://stash.wiki/configuration/example-config) | 编写主配置时查 YAML 字段及完整示例。 | [EN](https://stash.wiki/en/configuration/example-config) |
| [覆写配置（Override）](https://stash.wiki/configuration/override) | 查 .stoverride、合并顺序、替换／追加及参数。 | [EN](https://stash.wiki/en/configuration/override) |
| [策略组图标](https://stash.wiki/configuration/proxy-group-icon) | 查 proxy-groups.icon 图片地址的写法。 | [EN](https://stash.wiki/en/configuration/proxy-group-icon) |

### 分流规则

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [规则类型](https://stash.wiki/rules/rule-types) | 查域名、IP、端口、进程、逻辑规则及附加选项。 | [EN](https://stash.wiki/en/rules/rule-types) |
| [规则集合](https://stash.wiki/rules/rule-set) | 查 rule-providers、集合格式、更新和 RULE-SET 引用。 | [EN](https://stash.wiki/en/rules/rule-set) |

### 代理协议与策略

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [协议类型](https://stash.wiki/proxy-protocols/proxy-types) | 查各协议字段、传输选项、TLS 和 UDP 参数。 | [EN](https://stash.wiki/en/proxy-protocols/proxy-types) |
| [策略组](https://stash.wiki/proxy-protocols/proxy-groups) | 查自动选择、故障转移、负载均衡、手选及组合。 | [EN](https://stash.wiki/en/proxy-protocols/proxy-groups) |
| [远程代理集](https://stash.wiki/proxy-protocols/proxy-providers) | 查订阅节点的后台更新、过滤和策略组引用。 | [EN](https://stash.wiki/en/proxy-protocols/proxy-providers) |
| [延迟测试](https://stash.wiki/proxy-protocols/proxy-benchmark) | 查测试 URL、超时和禁用测试的设置。 | [EN](https://stash.wiki/en/proxy-protocols/proxy-benchmark) |
| [代理链](https://stash.wiki/proxy-protocols/dialer-proxy) | 查 dialer-proxy 上游代理及多级链路组合。 | [EN](https://stash.wiki/en/proxy-protocols/dialer-proxy) |

### HTTP 引擎

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [HTTP 引擎简介](https://stash.wiki/http-engine/intro) | 查 HTTP 引擎的入站条件和连接处理流程。 | [EN](https://stash.wiki/en/http-engine/intro) |
| [MitM](https://stash.wiki/http-engine/mitm) | 查 HTTPS 解密、CA 证书信任和域名列表。 | [EN](https://stash.wiki/en/http-engine/mitm) |
| [强制 HTTP 引擎](https://stash.wiki/http-engine/force-http-engine) | 查 Tunnel 流量如何进入 HTTP 引擎。 | [EN](https://stash.wiki/en/http-engine/force-http-engine) |
| [HTTP 重写](https://stash.wiki/http-engine/rewrite) | 查 URL、请求头、正文重写、jq、Mock 和脚本入口。 | [EN](https://stash.wiki/en/http-engine/rewrite) |

### JavaScript 脚本

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [管理脚本](https://stash.wiki/script/manage-script) | 查 script-providers 声明、更新和下载请求头。 | [EN](https://stash.wiki/en/script/manage-script) |
| [语法与接口](https://stash.wiki/script/syntax-and-interface) | 查脚本环境、$done、存储、定时器和 HTTP 客户端。 | [EN](https://stash.wiki/en/script/syntax-and-interface) |
| [改写 HTTP](https://stash.wiki/script/rewrite-requests) | 查 request／response 对象、正文和脚本引擎选项。 | [EN](https://stash.wiki/en/script/rewrite-requests) |
| [面板（Tile）](https://stash.wiki/script/tile) | 查首页面板配置、脚本返回值和折叠面板。 | [EN](https://stash.wiki/en/script/tile) |
| [定时任务](https://stash.wiki/script/scheduled-tasks) | 查 cron 脚本配置和运行条件。 | [EN](https://stash.wiki/en/script/scheduled-tasks) |

### 网络与控制功能

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [内网穿透](https://stash.wiki/features/nat-traversal) | 查 StashLink、内置 Tailscale 和设备互联。 | [EN](https://stash.wiki/en/features/nat-traversal) |
| [内置 DNS 服务](https://stash.wiki/features/dns-server) | 查上游 DNS、分域名解析、Fake-IP、回退及规则跟随。 | [EN](https://stash.wiki/en/features/dns-server) |
| [主机名映射](https://stash.wiki/features/hosts) | 查 hosts／proxy-hosts、通配域名和多地址映射。 | [EN](https://stash.wiki/en/features/hosts) |
| [为局域网设备提供代理](https://stash.wiki/features/provide-proxy-to-lan-device) | 查 HTTP／SOCKS、个人热点和网关模式。 | [EN](https://stash.wiki/en/features/provide-proxy-to-lan-device) |
| [MTProto 代理服务器](https://stash.wiki/features/mtproto) | 查 Telegram 代理监听、连接入口和数据中心分流。 | [EN](https://stash.wiki/en/features/mtproto) |
| [HTTP API](https://stash.wiki/features/http-api) | 查认证、状态、策略组、资源更新和诊断接口。 | [EN](https://stash.wiki/en/features/http-api) |
| [服务提供商订阅](https://stash.wiki/features/service-provider-subscription) | 查配置自动更新和流量／到期信息展示。 | [EN](https://stash.wiki/en/features/service-provider-subscription) |
| [网络性能增强](https://stash.wiki/features/network-performance-enhance) | 查 DNS 缓存、并发查询、并发连接和多网络使用。 | [EN](https://stash.wiki/en/features/network-performance-enhance) |
| [按需启动](https://stash.wiki/features/on-demand) | 查持续运行、蜂窝网络开关和 Wi-Fi SSID 排除。 | [EN](https://stash.wiki/en/features/on-demand) |

### 常见问题

| 中文页面 | 查阅内容 | English |
| --- | --- | --- |
| [编写高效配置](https://stash.wiki/faq/effective-stash) | 排查内存占用，查 DNS、规则集合和 QUIC 建议。 | [EN](https://stash.wiki/en/faq/effective-stash) |
| [防止代理被检测](https://stash.wiki/faq/proxy-detected) | 查仅使用 Tunnel 代理与 HTTP 引擎的配合。 | [EN](https://stash.wiki/en/faq/proxy-detected) |
| [授权与激活](https://stash.wiki/faq/license-activation) | 查设备授权、反激活、License Key 和激活故障。 | [EN](https://stash.wiki/en/faq/license-activation) |
| [TestFlight 相关](https://stash.wiki/faq/testflight) | 查测试版申请及授权注意事项。 | [EN](https://stash.wiki/en/faq/testflight) |
| [应用推送通知](https://stash.wiki/faq/ios-push-notifications) | 排查 APNs 路由和部分应用收不到通知的问题。 | [EN](https://stash.wiki/en/faq/ios-push-notifications) |
| [IPv6 兼容性](https://stash.wiki/faq/ipv6-compatible) | 查 IPv4／IPv6 连接选择和 Tunnel 行为。 | [EN](https://stash.wiki/en/faq/ipv6-compatible) |
| [URL Schema](https://stash.wiki/faq/url-schema) | 查 stash://、clash:// 和链接导入／开关命令。 | [EN](https://stash.wiki/en/faq/url-schema) |
| [越狱修改内存限制](https://stash.wiki/faq/jailbreak-ios-memory-limit) | 查越狱设备的 Jetsam 配置与内存限制。 | [EN](https://stash.wiki/en/faq/jailbreak-ios-memory-limit) |
| [无法安装帮助程序](https://stash.wiki/faq/stash-mac-helper) | 排查 Mac Helper 安装、后台权限及修复步骤。 | [EN](https://stash.wiki/en/faq/stash-mac-helper) |
| [与其他 VPN 冲突](https://stash.wiki/faq/conflict-with-vpn) | 查通过绑定网卡处理 VPN 共存的入口。 | [EN](https://stash.wiki/en/faq/conflict-with-vpn) |

## 常用章节直达

以下锚点取自实际页面标题，便于跳过长页；只列常用章节，完整内容见上方页面入口。

- **覆写语法与参数**：[语法参考](https://stash.wiki/configuration/override#%E8%AF%AD%E6%B3%95%E5%8F%82%E8%80%83) · [常见覆写示例](https://stash.wiki/configuration/override#%E5%B8%B8%E8%A7%81%E8%A6%86%E5%86%99%E7%A4%BA%E4%BE%8B) · [使用 #!replace 语法的覆写示例](https://stash.wiki/configuration/override#%E4%BD%BF%E7%94%A8-replace-%E8%AF%AD%E6%B3%95%E7%9A%84%E8%A6%86%E5%86%99%E7%A4%BA%E4%BE%8B) · [使用 #!append 语法的覆写示例](https://stash.wiki/configuration/override#%E4%BD%BF%E7%94%A8-append-%E8%AF%AD%E6%B3%95%E7%9A%84%E8%A6%86%E5%86%99%E7%A4%BA%E4%BE%8B) · [合并示例](https://stash.wiki/configuration/override#%E5%90%88%E5%B9%B6%E7%A4%BA%E4%BE%8B) · [覆写参数](https://stash.wiki/configuration/override#%E8%A6%86%E5%86%99%E5%8F%82%E6%95%B0)。
- **各代理协议**：[Shadowsocks / Shadowsocks2022](https://stash.wiki/proxy-protocols/proxy-types#shadowsocks--shadowsocks2022) · [ShadowsocksR](https://stash.wiki/proxy-protocols/proxy-types#shadowsocksr) · [SOCKS5](https://stash.wiki/proxy-protocols/proxy-types#socks5) · [HTTP](https://stash.wiki/proxy-protocols/proxy-types#http) · [VMess](https://stash.wiki/proxy-protocols/proxy-types#vmess) · [Snell](https://stash.wiki/proxy-protocols/proxy-types#snell) · [Trojan](https://stash.wiki/proxy-protocols/proxy-types#trojan) · [AnyTLS](https://stash.wiki/proxy-protocols/proxy-types#anytls) · [TrustTunnel](https://stash.wiki/proxy-protocols/proxy-types#trusttunnel) · [Hysteria](https://stash.wiki/proxy-protocols/proxy-types#hysteria) · [Hysteria2](https://stash.wiki/proxy-protocols/proxy-types#hysteria2) · [VLESS](https://stash.wiki/proxy-protocols/proxy-types#vless) · [TUIC](https://stash.wiki/proxy-protocols/proxy-types#tuic) · [Juicity](https://stash.wiki/proxy-protocols/proxy-types#juicity) · [Mieru](https://stash.wiki/proxy-protocols/proxy-types#mieru) · [MASQUE](https://stash.wiki/proxy-protocols/proxy-types#masque) · [WireGuard](https://stash.wiki/proxy-protocols/proxy-types#wireguard) · [Tailscale](https://stash.wiki/proxy-protocols/proxy-types#tailscale) · [SSH](https://stash.wiki/proxy-protocols/proxy-types#ssh) · [DIRECT with Specified Interface](https://stash.wiki/proxy-protocols/proxy-types#direct-with-specified-interface)。
- **策略组类型**：[策略类型](https://stash.wiki/proxy-protocols/proxy-groups#%E7%AD%96%E7%95%A5%E7%B1%BB%E5%9E%8B) · [额外功能](https://stash.wiki/proxy-protocols/proxy-groups#%E9%A2%9D%E5%A4%96%E5%8A%9F%E8%83%BD)。
- **DNS 选项**：[自定义上游 DNS 服务器](https://stash.wiki/features/dns-server#%E8%87%AA%E5%AE%9A%E4%B9%89%E4%B8%8A%E6%B8%B8-dns-%E6%9C%8D%E5%8A%A1%E5%99%A8) · [代理服务器域名解析](https://stash.wiki/features/dns-server#%E4%BB%A3%E7%90%86%E6%9C%8D%E5%8A%A1%E5%99%A8%E5%9F%9F%E5%90%8D%E8%A7%A3%E6%9E%90) · [基于域名的自定义 DNS 服务](https://stash.wiki/features/dns-server#%E5%9F%BA%E4%BA%8E%E5%9F%9F%E5%90%8D%E7%9A%84%E8%87%AA%E5%AE%9A%E4%B9%89-dns-%E6%9C%8D%E5%8A%A1) · [回退 DNS](https://stash.wiki/features/dns-server#%E5%9B%9E%E9%80%80-dns) · [Fake-IP](https://stash.wiki/features/dns-server#fake-ip) · [IPv6 解析](https://stash.wiki/features/dns-server#ipv6-%E8%A7%A3%E6%9E%90) · [自定义 Hosts](https://stash.wiki/features/dns-server#%E8%87%AA%E5%AE%9A%E4%B9%89-hosts) · [DNS 查询跟随规则](https://stash.wiki/features/dns-server#dns-%E6%9F%A5%E8%AF%A2%E8%B7%9F%E9%9A%8F%E8%A7%84%E5%88%99)。
- **内网互联方案**：[StashLink](https://stash.wiki/features/nat-traversal#stashlink) · [内置 Tailscale](https://stash.wiki/features/nat-traversal#%E5%86%85%E7%BD%AE-tailscale) · [如何选择](https://stash.wiki/features/nat-traversal#%E5%A6%82%E4%BD%95%E9%80%89%E6%8B%A9)。
- **HTTP 重写方式**：[URL 重写](https://stash.wiki/http-engine/rewrite#url-%E9%87%8D%E5%86%99) · [HTTP header 重写](https://stash.wiki/http-engine/rewrite#http-header-%E9%87%8D%E5%86%99) · [HTTP Body Rewrite](https://stash.wiki/http-engine/rewrite#http-body-rewrite) · [Mock](https://stash.wiki/http-engine/rewrite#mock) · [使用 JavaScript 引擎重写](https://stash.wiki/http-engine/rewrite#%E4%BD%BF%E7%94%A8-javascript-%E5%BC%95%E6%93%8E%E9%87%8D%E5%86%99)。
- **脚本 API**：[基础方法](https://stash.wiki/script/syntax-and-interface#%E5%9F%BA%E7%A1%80%E6%96%B9%E6%B3%95) · [$done(value)](https://stash.wiki/script/syntax-and-interface#donevalue) · [持久化存储](https://stash.wiki/script/syntax-and-interface#%E6%8C%81%E4%B9%85%E5%8C%96%E5%AD%98%E5%82%A8) · [HTTP Client](https://stash.wiki/script/syntax-and-interface#http-client)。
- **控制 API**：[开启与认证](https://stash.wiki/features/http-api#%E5%BC%80%E5%90%AF%E4%B8%8E%E8%AE%A4%E8%AF%81) · [基础信息](https://stash.wiki/features/http-api#%E5%9F%BA%E7%A1%80%E4%BF%A1%E6%81%AF) · [连接](https://stash.wiki/features/http-api#%E8%BF%9E%E6%8E%A5) · [规则](https://stash.wiki/features/http-api#%E8%A7%84%E5%88%99) · [代理与策略组](https://stash.wiki/features/http-api#%E4%BB%A3%E7%90%86%E4%B8%8E%E7%AD%96%E7%95%A5%E7%BB%84) · [远程资源](https://stash.wiki/features/http-api#%E8%BF%9C%E7%A8%8B%E8%B5%84%E6%BA%90) · [DNS](https://stash.wiki/features/http-api#dns) · [诊断](https://stash.wiki/features/http-api#%E8%AF%8A%E6%96%AD) · [脚本](https://stash.wiki/features/http-api#%E8%84%9A%E6%9C%AC) · [实时推送](https://stash.wiki/features/http-api#%E5%AE%9E%E6%97%B6%E6%8E%A8%E9%80%81) · [面板](https://stash.wiki/features/http-api#%E9%9D%A2%E6%9D%BF)。

## 官网旧链接与替代入口

以下 4 个路径来自官网实际链接，核对时返回 404。替代入口按主题选取，不代表官网重定向。

| 返回 404 的旧路径 | 可用入口 | 备注 |
| --- | --- | --- |
| `https://stash.wiki/stash-mac-en` | [Stash Mac 英文版](https://stash.wiki/en/stash-mac) | 英文首页保留的旧链接。 |
| `https://stash.wiki/script/rewrite-requests-en` | [改写 HTTP 英文版](https://stash.wiki/en/script/rewrite-requests) | 英文重写页保留的旧链接。 |
| `https://stash.wiki/http-engine/script` | [管理脚本](https://stash.wiki/script/manage-script)、[改写 HTTP](https://stash.wiki/script/rewrite-requests) | Mac 历史更新记录中的旧脚本文档。 |
| `https://stash.wiki/features/tls-fingerprint` | [协议类型](https://stash.wiki/proxy-protocols/proxy-types)、[Mac 更新日志](https://stash.wiki/release-notes/macos) | 未找到独立替代页；按具体字段查原文，不能将 TLS 指纹伪装与证书指纹校验混为一谈。 |

## 后续更新导航

1. 从 [robots.txt](https://stash.wiki/robots.txt) 找到 [sitemap.xml](https://stash.wiki/sitemap.xml)，跟随其中的子站点地图。
2. 对照首页侧栏与 [llms.txt](https://stash.wiki/llms.txt)，检查新增、迁移或删除的主题。
3. 读取新增页面，更新用途说明和中英文链接；链接须使用实际页面地址，不能仅按命名规律推测。
4. 检查页面响应、跳转和章节锚点；对正文中的相对链接，按所在页面 URL 解析。
5. 更新核对日期和页面数量；保留仍有参考价值的失效链接说明。
