# R6S 只读检查记录

检查日期：2026-10-19。通过用户授权的 SSH 连接 `root@10.0.1.1` 检查。以下是检查时的快照，后续部署前应重新确认。

后续已完成更完整的[安全稳定性审阅](R6S-Security-Stability-Review.md)。按用户最新要求，R6S 不运行代理；本记录只保留检查事实，不再作为路由端代理部署建议。

## 检查范围

读取系统信息、软件包版本、选定的非敏感 UCI 字段、进程名称、监听端口、网口状态和 nftables 表名；执行已有 Mihomo 的版本查询。未导出完整订阅、认证密码或 API 密钥，本文不记录公网地址与完整端口映射。

**没有安装或升级软件、启动或停止服务、修改配置、调整防火墙、重启或测速。** SSH 登录可能产生系统正常的访问日志。

## 系统与资源

| 项目 | 实测结果 |
| --- | --- |
| 型号 | FriendlyElec NanoPi R6S |
| 系统 | ImmortalWrt 24.10.4，`r33602-e717d133ed6d` |
| 内核 | Linux 6.6.110 |
| 目标／包架构 | `rockchip/armv8`／`aarch64_generic` |
| 根文件系统 | squashfs + overlay |
| 内存 | `MemTotal: 8136460 kB`，约 7.76 GiB；检查时可用约 7.56 GiB |
| 交换空间 | 无 |
| 可写 overlay | 总计约 282.8 MB，已用 95.3 MB，剩余 187.5 MB，使用率 34%（`df -h` 原始单位） |
| 块设备 | `mmcblk1` 约 28.9 GiB；当前 overlay 容量远小于整盘容量 |
| 软件包管理 | opkg |
| 防火墙 | 已安装 firewall4，可执行 fw4 与 nft |
| 网口 | eth1、eth2 均协商为 2500 Mbps／全双工；eth0 未连接 |

网口协商速率不代表宽带或代理实际吞吐。R6S 上联／下联为 2.5G，与 NAS、Mac mini 各自千兆接口并不矛盾。

## 现有代理组件

| 项目 | 实测结果 |
| --- | --- |
| Nikki 后端包 | `nikki 2025.12.01-r1` |
| LuCI 界面包 | `luci-app-nikki 1.24.4-r1` |
| Mihomo 可执行文件 | `/usr/bin/mihomo` |
| Mihomo 版本 | `v1.19.17 linux arm64`，构建时间 2025-12-04，含 `with_gvisor` 标签 |
| init 自启动登记 | 已启用 |
| Nikki 配置总开关 | `nikki.config.enabled=0` |
| 当前运行状态 | init 查询为未运行；未观察到 Mihomo／Clash 进程 |
| nftables 表 | 观察到 `inet fw4`、`inet dnsmasq`；未观察到独立 Nikki 表 |

**结论：已经安装，但当前没有启用 Nikki 代理服务。** init 的开机启动登记与 Nikki 自身配置开关不是同一件事，不能因前者启用就认定代理已运行。仅列出 nftables 表名也不能完整证明所有链／规则的行为。

已安装 `kmod-tun`、`kmod-nft-tproxy`、`kmod-nft-socket`、`ip-full`、`curl`、`ca-bundle` 与 `yq`。当前系统版本、内核和 fw4 满足 Nikki 主线文档列出的基础要求；这不代表现有旧版已经支持最新主线的所有字段或行为。[Nikki 官方要求](https://github.com/nikkinikki-org/OpenWrt-nikki)

现存配置选择 TCP redirect、UDP TUN，并设置 Fake-IP、IPv4／IPv6 代理及 DNS 接管选项。由于总开关关闭，**这些只是保存的设置，不是当前有效代理行为**。未导出完整订阅，也未验证节点或配置能否成功启动。

## 当前网络与 DNS

- LAN：`br-lan`，路由地址 `10.0.1.1/24`。
- DHCP：起始偏移 100、数量 150、租期 12 小时；未观察到 LAN 自定义 DHCP 网关／DNS option。
- DNS：已安装并运行 dnsmasq-full 2.90-r5；缓存设置 8000，配置使用 `/tmp/resolv.conf.d/resolv.conf.auto`。
- WAN：PPPoE，物理接口 eth2，检查时在线。
- IPv6：LAN 配置 `ip6assign=60`、RA server；接口状态中 `wan6` 为 down，但动态 `wan_6` 为 up。因此不能根据单独的 `wan6` 状态认定 IPv6 未启用。
- 流量卸载：软件与硬件选项均为 1；选项开启不证明实际数据路径正在使用硬件加速。
- 已有端口转发和远程管理相关设置。后续代理部署必须保留现有业务，不能直接替换整份网络／防火墙配置；本次未从外网验证这些服务的可达性。

未进行 DNS 泄漏、IPv6 绕过、代理出口或吞吐测试；当前路由工作状态不能等同于代理验收结果。

## 对方案的影响

1. **R6S 保持基础网关职责，不运行代理**：原先利用现有 Nikki 的推荐已撤回；保留拨号、路由、DHCP、普通 DNS 和防火墙。
2. **审核现存组件的精简计划**：Nikki 已停止，但有自启动登记与防火墙 include；禁用或卸载需要另行审核，不直接删除依赖。
3. **空间暂未耗尽**：187.5 MB 可写余量需要在固件维护时核算；是否扩容另做分区与备份评估，不直接调整分区。
4. **保留基础路由现状供验收**：没有证据要求现在关闭卸载或 IPv6，相关变更应有问题依据和回退路径。
5. **保持基础网络独立于 NAS／Mac mini**：不把全家的默认网关／唯一 DNS 改指代理主机；独立客户端或可选共享代理的故障不应中断其他设备的基础网络。

下一步仍是审阅[家庭代理方案](../Home-Proxy-Architecture.md)，再确定版本与小范围测试计划。此次检查不代表用户已授权启用或迁移现有服务。
