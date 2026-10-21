# 家庭网络运行上下文

最后确认：2026-10-19。供后续 agent 快速接手，优先于早期已撤回的路由代理建议；实时状态可能变化，执行操作前按需复核。

## 用户已明确的要求

- 稳定性优先：代理、Mac mini 或 NAS 故障不能中断未使用代理设备的基础网络。
- R6S 仅负责基础路由，不运行代理；不为代理修改默认网关、DHCP、基础 DNS 或 WAN 映射。
- 家中按需手动配置 Mac mini 的 LAN HTTP／SOCKS 代理，退出时关闭该代理；外出使用设备独立客户端。
- 不采用 Mac mini／NAS／Apple TV 旁路由、透明代理或全家 DNS 接管。需要全应用／UDP 覆盖时，选设备自身客户端。
- **用户已购买 Stash Mac 授权，明确计划 Windows + 两台 macOS 都使用 Stash**；购买不代表已安装、激活或迁移。iOS 已购买并覆盖 tvOS。Android 暂建议 FlClash，Stash Android 待试用。
- 统一管理必须依靠云端远程完整配置，不依赖 Stash iCloud／跨设备同步；节点、规则、完整配置更新分别验证。
- 规则尽量一处维护，多平台输出；配置改动必须核对相应官方原文，不能假定 Stash 与 Mihomo 完全等价。
- 家庭服务迁移／路由整改仍为方案审阅。用户另已明确授权立即卸载本机其他代理：MacBook 清理已完成，保留 Stash；这不授权停用 mini Surge。SSH 只读查看继续有效，后续实施按明确范围执行。

## 设备清单

| 设备 | 地址／访问 | 用户提供的规格与用途 | 2026-10-19 检查／确认 |
| --- | --- | --- | --- |
| NanoPi R6S | `root@10.0.1.1` | 主路由，OpenWrt 系统 | 实为 ImmortalWrt 24.10.4／Linux 6.6.110、约 8 GB 内存；Nikki 已装但总开关关闭、未运行 |
| Mac mini M4 | `nora@10.0.1.8` | macOS、无屏家庭服务器、千兆有线 | macOS 27.0.1、16 GiB；Surge 6.8.1 正常运行；已监听 6152／6153，虚拟路由存在；NAS 正在使用它的代理；目标改为 Stash Mac，未迁移 |
| 飞牛 NAS | `archon@10.0.1.2` | Xeon E-2176G 3.70 GHz、6C12T、32 GB、千兆有线 | Debian 12；默认路由 10.0.1.1。用户确认使用 Mac mini 代理；具体应用／容器／Docker daemon 范围尚未核实 |
| MacBook M2 Pro | 本机；当前工作目录 `/Users/astral/Work/MagicHub` | macOS、移动办公 | macOS 27.0.1；Stash 4.4.0 正在运行，Stash 扩展启用；ClashBar、Surge、Mihomo 已卸载；系统手动 HTTP／HTTPS／SOCKS／PAC 均关闭；旧 Surge 扩展已终止待重启删除 |
| iPhone 17 Pro Max | 未提供管理地址 | iOS | 尚未设备实查；目标客户端 Stash |
| 小米 17 Pro Max | 未提供管理地址 | Android／HyperOS 4 | 尚未设备实查；目标 FlClash，Stash Android 待评估 |
| Apple TV 4K | 未提供地址 | 用户已订购 2026 A19 型号 | 未实查；目标独立 Stash tvOS，不作网关 |
| 拯救者 R9000K 2021 | 未提供地址 | Ryzen 9 5900HX、Windows、16 英寸 | Windows 具体版本未确认；目标 Stash Windows；官方早期版，CVR x64 为恢复备选 |

LAN 为 `10.0.1.0/24`，网关 `10.0.1.1`；宽带按用户“上下行分别”理解为上行 100 Mbps、下行 1000 Mbps。R6S 两个活动网口协商 2.5G，不改变 NAS／Mac mini 千兆接口的已知条件。

本机清理详情见[卸载记录](audits/MacBook-Proxy-Cleanup.md)。旧数据已从运行位置移至废纸篓，不读取或提交凭据；没有重启，也没有修改 mini／NAS／R6S。

## 当前与目标必须分开

| 层面 | 当前已知事实 | 目标／尚未完成 |
| --- | --- | --- |
| Mac mini 代理 | Surge 是正常生产服务，NAS 是其使用者；监听端口 TCP 可达 | 计划迁移到 Stash Mac 显式 LAN 代理；无屏启动／恢复待验收；没有部署、替换或停止 Surge |
| NAS 代理 | 用户明确确认正在使用 Mac mini | 未枚举所有消费者；登录 shell 无代理环境变量不证明 NAS 没有使用代理 |
| 接入端口 | mini 的 6152／6153 正由 Surge 使用；7890 在检查时不可连接 | 优先兼容现有消费者的地址／协议／端口，最终协议和鉴权需确认；不得将规划端口当已上线 |
| 统一配置 | 仓库已有规则与官方文档检索工具 | 目标为独立云端 Sub-Store + 工作台 + 按设备完整配置；生成、HTTPS 分发、自动回滚尚未实现 |
| R6S 审阅 | 有管理端口转发、HTTP 管理和固件维护建议 | 全部待审核，未做整改；不要顺手删除转发、更新固件或清理 Nikki |

## 接手时的最短路径

1. 先读根目录 [AGENTS.md](../../AGENTS.md)；本文件提供事实与约束，不证明实时状态。
2. 设计／选型读[总体方案](Home-Proxy-Architecture.md)与[客户端比较](Client-Selection-and-Compatibility.md)；云端实现读[开发规格](../development/Remote-Config-Console.md)；Mac mini、NAS、切换与回退读[服务与迁移方案](Mac-mini-LAN-Proxy-Plan.md)。
3. 只有涉及路由审阅时才读 [R6S 报告](audits/R6S-Security-Stability-Review.md)，不因看到报告就执行整改。
4. 修改字段先用 [官方查阅流程](../reference/Official-Docs-Workflow.md)定位和联网核对，只读必要章节，复用同一任务内已校验的缓存。
5. 仅复核受影响的组件，记录用户确认／设备观察／设计假设的区别；不要重复扫描全家或输出凭据。

设备快照仅保留日期和必要证据，避免不断追加完整原始输出。实际完成迁移后必须同步更新本文件、总体方案和接入文档，撤掉过期的“未执行”标记并填写验证结果。
