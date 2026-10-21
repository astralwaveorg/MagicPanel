# MacBook 代理应用卸载记录

日期：2026-10-19。范围：用户明确要求“本机删除并彻底卸载其他代理，只保留 Stash，立即执行”。仅操作本机 MacBook，没有操作 Mac mini、NAS 或 R6S。

## 已完成

- 保留 `/Applications/Stash.app` 与配套 `Stash Dashboard.app`；本机版本 4.4.0，进程运行、StashTunnel 系统扩展启用。
- 移除 Surge 6.9.1、Surge Dashboard、ClashBar 0.3.6、Homebrew 独立 Mihomo 1.19.32，以及 Surge CLI／DHCP 工具链接。
- 卸载并删除旧 ClashBar、Surge、Clash Party 的系统辅助程序和已发现的启动登记；未改 Stash Helper／启动设置。
- 清理旧 Surge、ClashBar、ClashMax、FlClash 的应用数据、偏好、缓存、日志、容器残留及独立 Mihomo 配置；32 项残留／安装缓存移至本机废纸篓隔离目录，未清空其他废纸篓内容。路径清单只在本地，不把配置或凭据提交仓库。
- Surge 的 Homebrew 卸载因其辅助程序步骤要求终端 sudo 而未完整继续；辅助程序已由原生管理员授权移除，应用通过 Finder 移除，剩余命令链接及 Caskroom 安装登记已清理。ClashBar／Mihomo 已不在 Homebrew 安装列表。

## 网络扩展与验证结果

`systemextensionsctl gc` 成功清理 Surge 的孤立扩展，状态由 `activated disabled` 变为 **`terminated waiting to uninstall on reboot`**。它已经终止，macOS 待下次正常重启删除；**本次没有重启、关闭 SIP 或 reset 全部系统扩展**。Stash 扩展继续显示 `activated enabled`。

复查仅 Stash 代理应用进程运行，无旧代理 helper／独立核心；Applications 与 Homebrew 不再列出其他上述代理。系统 HTTP／HTTPS／SOCKS／PAC 均关闭，网络服务只列出 Wi-Fi 与 Thunderbolt Bridge，未见旧 Surge 网络服务。DNS 查询成功、HTTPS 请求返回 200；这只验证基本连通，不证明所有分流和机场业务均已验收。

## 后续边界

用户方便时正常重启后复查旧 Surge 扩展是否消失；不为清理记录擅自重启。废纸篓内的配置不再参与运行，但仍可能含原凭据，按用户自己的保留／清空习惯处理。未读取 Stash 订阅、账号或密钥，未新建云端配置服务，也未替换 mini 上 NAS 正在使用的 Surge。

卸载参考：[Surge 官方数据清理说明](https://kb.nssurge.com/surge-knowledge-base/faq/mac-reset)、[ClashBar 官方卸载说明](https://github.com/Sitoi/ClashBar)、[Apple 卸载指南](https://support.apple.com/en-us/102610)。
