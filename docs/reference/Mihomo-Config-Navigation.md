# Mihomo 官方配置查阅导航

核对日期：2026-10-19。范围为 [Mihomo 官方配置区](https://wiki.metacubex.one/config/)及其中文子页面，共 **79 页**，已读取正文与标题，核对时全部返回 HTTP 200。安装、手册、API 为补充入口，不计入配置区页数；英文／俄文翻译不重复展开。

本页用于找入口，具体字段与版本约束必须回到官方原文核对。[文档源仓库](https://github.com/MetaCubeX/Meta-Docs)和[核心完整配置示例](https://github.com/MetaCubeX/mihomo/blob/Meta/docs/config.yaml)可辅助查证；主分支示例可能领先于已安装版本。

## 优先按字段检索

```sh
python3 scripts/docs_lookup.py search respect-rules --product mihomo
python3 scripts/docs_lookup.py read https://wiki.metacubex.one/config/dns/ --section respect-rules
```

默认只输出前 5 个命中及最多 80 行正文。使用方式与强制核对流程见[官方文档查阅流程](Official-Docs-Workflow.md)。

## 按任务定位

| 修改对象／问题 | 官方入口 |
| --- | --- |
| `mode`、`allow-lan`、API、接口、GEO 数据 | [全局配置](https://wiki.metacubex.one/config/general/) |
| `dns`、Fake-IP、DNS 跟随规则与解析循环 | [DNS 字段](https://wiki.metacubex.one/config/dns/) → [DNS 类型](https://wiki.metacubex.one/config/dns/type/) → [解析流程](https://wiki.metacubex.one/config/dns/diagram/) |
| `hosts` 或嗅探恢复域名 | [hosts](https://wiki.metacubex.one/config/dns/hosts/)／[域名嗅探](https://wiki.metacubex.one/config/sniff/) |
| `tun`、自动路由、DNS 劫持、网关 | [TUN](https://wiki.metacubex.one/config/inbound/tun/) → [入站总览](https://wiki.metacubex.one/config/inbound/) |
| `listeners` 或代理监听端口 | [Listeners 通用字段](https://wiki.metacubex.one/config/inbound/listeners/)／[代理端口](https://wiki.metacubex.one/config/inbound/port/) → 对应协议入站页 |
| `proxies`、TLS、Reality、传输参数 | [出站通用字段](https://wiki.metacubex.one/config/proxies/) → 协议页 → [TLS](https://wiki.metacubex.one/config/proxies/tls/)／[传输层](https://wiki.metacubex.one/config/proxies/transport/) |
| `proxy-providers`、订阅筛选与覆写 | [代理集合](https://wiki.metacubex.one/config/proxy-providers/) → [集合文件内容](https://wiki.metacubex.one/config/proxy-providers/content/) |
| `proxy-groups`、延迟测试与故障转移 | [组通用字段](https://wiki.metacubex.one/config/proxy-groups/) → 对应组类型 |
| 链式代理、旧 `relay` 迁移 | [dialer-proxy](https://wiki.metacubex.one/config/proxies/dialer-proxy/)；[relay 页](https://wiki.metacubex.one/config/proxy-groups/relay/)明确标注弃用 |
| `rules`、`rule-providers`、MRS、子规则 | [路由规则](https://wiki.metacubex.one/config/rules/) → [规则集合](https://wiki.metacubex.one/config/rule-providers/) → [集合内容](https://wiki.metacubex.one/config/rule-providers/content/)／[子规则](https://wiki.metacubex.one/config/sub-rule/) |

## 完整配置页面目录

### 总览与全局

| 页面 | 查阅用途 |
| --- | --- |
| [配置](https://wiki.metacubex.one/config/) | 总入口；从流量入站、路由、出站、DNS、策略组定位配置。 |
| [实验性配置](https://wiki.metacubex.one/config/experimental/) | 实验性 QUIC、GSO、ECN 等选项，按目标版本谨慎核对。 |
| [全局配置](https://wiki.metacubex.one/config/general/) | 全局运行模式、日志、API、面板、连接、接口、GEO 数据与缓存。 |
| [NTP](https://wiki.metacubex.one/config/ntp/) | 时间同步开关、服务端、周期和连接代理。 |
| [域名嗅探](https://wiki.metacubex.one/config/sniff/) | 嗅探协议、目标覆写、强制／跳过域名及地址。 |
| [TUNNEL](https://wiki.metacubex.one/config/tunnels/) | 传统流量隧道 network／address／target／proxy 写法。 |

### DNS

| 页面 | 查阅用途 |
| --- | --- |
| [DNS](https://wiki.metacubex.one/config/dns/) | DNS 开关、解析策略、Fake-IP、回退、代理／直连域名解析。 |
| [解析流程](https://wiki.metacubex.one/config/dns/diagram/) | 结合流程图理解 DNS 解析路径与各 nameserver 的关系。 |
| [hosts](https://wiki.metacubex.one/config/dns/hosts/) | 静态域名映射、多地址与通配匹配。 |
| [DNS 类型](https://wiki.metacubex.one/config/dns/type/) | UDP、TCP、DoT、DoH、DoQ、系统与组网 DNS 地址写法。 |

### 入站总览、端口与 TUN

| 页面 | 查阅用途 |
| --- | --- |
| [入站配置](https://wiki.metacubex.one/config/inbound/) | 代理端口、TUN 和 listeners 三种入站配置入口。 |
| [Listeners：通用字段](https://wiki.metacubex.one/config/inbound/listeners/) | 监听器通用字段，名称、监听地址、端口和定向路由。 |
| [代理端口](https://wiki.metacubex.one/config/inbound/port/) | HTTP、SOCKS、混合、透明代理端口及认证。 |
| [TUN](https://wiki.metacubex.one/config/inbound/tun/) | 系统栈、自动路由、DNS 劫持、接口、路由包含／排除。 |

### 各协议入站监听器

| 页面 | 查阅用途 |
| --- | --- |
| [AnyTLS](https://wiki.metacubex.one/config/inbound/listeners/anytls/) | AnyTLS 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [HTTP](https://wiki.metacubex.one/config/inbound/listeners/http/) | HTTP 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Hysteria2-realm](https://wiki.metacubex.one/config/inbound/listeners/hysteria2-realm/) | Hysteria2-realm 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Hysteria2](https://wiki.metacubex.one/config/inbound/listeners/hysteria2/) | Hysteria2 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Mieru](https://wiki.metacubex.one/config/inbound/listeners/mieru/) | Mieru 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [MIXED](https://wiki.metacubex.one/config/inbound/listeners/mixed/) | MIXED 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [REDIRECT](https://wiki.metacubex.one/config/inbound/listeners/redirect/) | REDIRECT 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [ShadowQUIC](https://wiki.metacubex.one/config/inbound/listeners/shadowquic/) | ShadowQUIC 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Snell](https://wiki.metacubex.one/config/inbound/listeners/snell/) | Snell 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [SOCKS](https://wiki.metacubex.one/config/inbound/listeners/socks/) | SOCKS 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [ShadowSocks](https://wiki.metacubex.one/config/inbound/listeners/ss/) | ShadowSocks 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Sudoku](https://wiki.metacubex.one/config/inbound/listeners/sudoku/) | Sudoku 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TPROXY](https://wiki.metacubex.one/config/inbound/listeners/tproxy/) | TPROXY 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Trojan](https://wiki.metacubex.one/config/inbound/listeners/trojan/) | Trojan 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TrustTunnel](https://wiki.metacubex.one/config/inbound/listeners/trusttunnel/) | TrustTunnel 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TUIC V4](https://wiki.metacubex.one/config/inbound/listeners/tuic-v4/) | TUIC V4 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TUIC V5](https://wiki.metacubex.one/config/inbound/listeners/tuic-v5/) | TUIC V5 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TUN](https://wiki.metacubex.one/config/inbound/listeners/tun/) | TUN 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TUNNEL](https://wiki.metacubex.one/config/inbound/listeners/tunnel/) | TUNNEL 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [VLESS](https://wiki.metacubex.one/config/inbound/listeners/vless/) | VLESS 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [VMESS](https://wiki.metacubex.one/config/inbound/listeners/vmess/) | VMESS 入站监听器专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |

### 出站通用、TLS、传输与内置行为

| 页面 | 查阅用途 |
| --- | --- |
| [出站代理：通用字段](https://wiki.metacubex.one/config/proxies/) | 出站通用参数，包括 UDP、接口绑定、链路和多路复用。 |
| [预置出站](https://wiki.metacubex.one/config/proxies/built-in/) | DIRECT、REJECT、PASS 等内置出站行为。 |
| [dialer-proxy](https://wiki.metacubex.one/config/proxies/dialer-proxy/) | 通过代理／策略组连接目标代理，以及 relay 迁移示例。 |
| [DIRECT](https://wiki.metacubex.one/config/proxies/direct/) | 显式 direct 出站配置。 |
| [DNS](https://wiki.metacubex.one/config/proxies/dns/) | 将出站交给 DNS 模块处理。 |
| [Rematch](https://wiki.metacubex.one/config/proxies/rematch/) | 标记后重新匹配主规则或跳转子规则。 |
| [TLS 配置](https://wiki.metacubex.one/config/proxies/tls/) | TLS、SNI、证书校验、指纹、Reality、ECH 及 Shadow TLS。 |
| [传输层配置](https://wiki.metacubex.one/config/proxies/transport/) | HTTP、HTTP/2、gRPC、WebSocket 等传输选项。 |

### 各协议出站代理

| 页面 | 查阅用途 |
| --- | --- |
| [AnyTLS](https://wiki.metacubex.one/config/proxies/anytls/) | AnyTLS 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [EasyTier](https://wiki.metacubex.one/config/proxies/easytier/) | EasyTier 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [HTTP](https://wiki.metacubex.one/config/proxies/http/) | HTTP 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Hysteria](https://wiki.metacubex.one/config/proxies/hysteria/) | Hysteria 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Hysteria2](https://wiki.metacubex.one/config/proxies/hysteria2/) | Hysteria2 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [MASQUE](https://wiki.metacubex.one/config/proxies/masque/) | MASQUE 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Mieru](https://wiki.metacubex.one/config/proxies/mieru/) | Mieru 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [OpenVPN](https://wiki.metacubex.one/config/proxies/openvpn/) | OpenVPN 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [ShadowQUIC](https://wiki.metacubex.one/config/proxies/shadowquic/) | ShadowQUIC 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Snell](https://wiki.metacubex.one/config/proxies/snell/) | Snell 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [SOCKS](https://wiki.metacubex.one/config/proxies/socks/) | SOCKS 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Shadowsocks](https://wiki.metacubex.one/config/proxies/ss/) | Shadowsocks 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [SSH](https://wiki.metacubex.one/config/proxies/ssh/) | SSH 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [ShadowsocksR](https://wiki.metacubex.one/config/proxies/ssr/) | ShadowsocksR 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Sudoku](https://wiki.metacubex.one/config/proxies/sudoku/) | Sudoku 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Tailscale](https://wiki.metacubex.one/config/proxies/tailscale/) | Tailscale 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [Trojan](https://wiki.metacubex.one/config/proxies/trojan/) | Trojan 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TrustTunnel](https://wiki.metacubex.one/config/proxies/trusttunnel/) | TrustTunnel 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [TUIC](https://wiki.metacubex.one/config/proxies/tuic/) | TUIC 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [VLESS](https://wiki.metacubex.one/config/proxies/vless/) | VLESS 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [VMess](https://wiki.metacubex.one/config/proxies/vmess/) | VMess 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [WireGuard](https://wiki.metacubex.one/config/proxies/wg/) | WireGuard 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |
| [ZeroTier](https://wiki.metacubex.one/config/proxies/zerotier/) | ZeroTier 出站代理专用字段；同时阅读所属通用字段和引用的 TLS／传输说明。 |

### 代理集合与代理组

| 页面 | 查阅用途 |
| --- | --- |
| [代理组：通用字段](https://wiki.metacubex.one/config/proxy-groups/) | 策略组通用字段、proxies／use、筛选、健康检查、图标等。 |
| [预置代理组](https://wiki.metacubex.one/config/proxy-groups/built-in/) | 内置 GLOBAL 代理组。 |
| [Fallback](https://wiki.metacubex.one/config/proxy-groups/fallback/) | 按顺序使用可用出站的回退策略。 |
| [Load-balance](https://wiki.metacubex.one/config/proxy-groups/load-balance/) | 负载均衡及 strategy。 |
| [Relay](https://wiki.metacubex.one/config/proxy-groups/relay/) | 弃用说明；新修改应查 dialer-proxy。 |
| [Select](https://wiki.metacubex.one/config/proxy-groups/select/) | 手动选择节点或其他策略组。 |
| [Url-test](https://wiki.metacubex.one/config/proxy-groups/url-test/) | 延迟测试自动选择及 tolerance。 |
| [代理集合](https://wiki.metacubex.one/config/proxy-providers/) | 节点来源、更新、下载代理、header、健康检查、覆写与过滤。 |
| [proxy-providers 文件内容](https://wiki.metacubex.one/config/proxy-providers/content/) | 节点集合文件的内容结构；区分集合内容与主配置声明。 |

### 路由规则、规则集合与子规则

| 页面 | 查阅用途 |
| --- | --- |
| [rule-provider](https://wiki.metacubex.one/config/rule-providers/) | 规则集合来源、更新、behavior、format、header 与 payload。 |
| [rule-providers 文件内容](https://wiki.metacubex.one/config/rule-providers/content/) | classical、domain、ipcidr 集合内容格式。 |
| [路由规则](https://wiki.metacubex.one/config/rules/) | 规则匹配顺序、域名／IP／进程／入站／逻辑规则及参数。 |
| [SUB-RULE](https://wiki.metacubex.one/config/sub-rule/) | SUB-RULE 与子规则组织。 |

## 本仓库对应关系

本仓库不存放 Clash／Mihomo 的配置文件与规则集合，样例以官方文档与 `official-example/` 为准。核对时：

- 先确认实际使用的内核与版本，再查 Mihomo 文档；Android／Linux／macOS 的 TUN 和权限条件分别核对。
- 目录名或文件名带 "Clash" 不代表所有字段都通用；订阅转换器的输出要按目标客户端核对。
- 涉及 Stash 时以 [Stash 导航](Stash-Wiki-Navigation.md)对应官方页为准，不能直接套用 Mihomo 扩展字段。
- 规则集合文件与主配置里的 `rule-providers` 声明要分开看，注意各自的 `behavior`／`format`，不是所有 YAML 都是完整配置。

## 补充官方入口与维护方法

- [语法手册](https://wiki.metacubex.one/handbook/syntax/)：YAML 与 Mihomo 基础语法。
- [官方文档首页](https://wiki.metacubex.one/)：按官网导航进入安装、手册与 API，不猜测不存在的路径。
- 重新整理时，从配置入口递归收集 `/config/` 内链接，并与侧栏、源仓库配置目录对照；逐页核对后再更新日期、数量及 `official-docs-index.json`。
- 此次官网 `sitemap.xml` 中存在以 `None` 开头的异常地址，未将其作为有效链接；`robots.txt` 与 `llms.txt` 返回 404，因此不能依赖它们完成索引。
