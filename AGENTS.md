# AGENTS.md

设计、验收和运行记录见[规格文档索引](docs/superpowers/specs/README.md)。

改动前，先按任务阅读对应文档：

| 要做的事 | 看哪份 |
| --- | --- |
| 改界面、改后端逻辑 | [开发文档](docs/开发文档.md) |
| 改配置（规则、策略组、引擎平台、设备独立配置、拓展模块） | [配置文档](docs/配置文档.md) |
| 回答"这个页面怎么用" | [使用文档](docs/使用文档.md) |
| 改规则集、决定直连还是代理、走哪个策略组 | [规则集与分流设计](docs/reference/规则集与分流设计.md) |
| 查内网地址、代理端口、哪台机器在跑什么 | [环境与地址速查](docs/reference/环境与地址.md) |
| 改分流方案、跨方案引用、方案产物与门户选择 | [多套分流方案设计](docs/reference/方案设计-多套分流方案.md) |

**第一次接手本项目**（新 Agent、换机器、隔了很久再来）：先读
[Agent 交接提示词](docs/reference/Agent-交接提示词.md)，里面写清了架构、硬性约束、
改配置的方式和发布流程，再动手。

跨阶段工作由 Codex（GPT-6.2 Sol）负责需求分析、关键设计、评审和验收；通过 Agent Relay 将边界明确的开发、自测和运维交给 Claude Code（MiniMax-M3.1-Flash）。独立工作区或最小材料交接，遵循桥接授权。合并改动后按风险集中验证，再提交、推送和部署。

**2026-11-27 美国自建 06（构建 #422，发布 rev 136）**：新增本地节点 `🇺🇸 美国自建 06`
（VLESS Reality，`186.244.245.81:30033`，SNI `www.amd.com`，AS400619 Arosscloud 洛杉矶），
排在 `🇺🇸 US自建` fallback 组末位（…→05→06）。该机同样是 NAT 容器（内网 `10.91.0.211`），
公网端口已在商家面板映射；NAS/66Cloud/SadIDC 三处实测 30033 可连，面板 Mihomo 测速
781–1025ms。快照 `policy/snapshots/2026-11-27-{before,after}-add-us06.json`
（digest `4335ff2e`→`f46510b6`）。

**2026-11-27 美国自建 05（构建 #421，发布 rev 135）**：新增本地节点 `🇺🇸 美国自建 05`
（VLESS Reality，`154.219.123.112:33995`，SNI `www.amd.com`，uuid/公钥/short-id 见
该机 `/root/reality-node.txt`），排在 `🇺🇸 US自建` fallback 组末位
（04→01→02→03→05），不改既有首选顺序。该机是 NAT 容器（内网 `10.91.0.13`，公网
`154.219.123.112`），公网端口需在商家面板映射；`/usr/local/bin/sb-reality.sh` 已补
NAT 检测、外部自检、监听地址与残留防火墙规则清理。本机经该节点访问
`generate_204` 返回 204，面板 Mihomo 测速 568–602ms。快照
`policy/snapshots/2026-11-27-{before,after}-add-us05.json`
（digest `8cf6ce85`→`37461805`）。

**2026-11-17 Telegram/Claude 独立分流（向阳要求）**：新增可见 select 组 `✈️ Telegram`
（默认 DIRECT，备选 日本软银01/02 节点直引、美国自建、默认代理）与 `🤖 Claude`
（默认 美国自建NTT → 日本软银01/02 → 美国自动），排 sort 1/2；规则 anthropic/telegram/
telegram-ip 移到 ai-cn 之后（sort 25-27，早于一切 AI/通讯集合）。日本自建选项用节点
直引而不是引用「日本移动」组——该组是手机专属（设备作用域），共享产物会被渲染器剔除。
注意：Telegram 默认直连在大陆无法连通（TG 被墙），此为向阳明确选择，客户端可手切。
构建 #296。

**2026-11-20 门户「全部节点」订阅**：`GET /feed/nodes/{token}.yaml` 实时渲染全部
启用节点（探测同源池 + regional 改名，名称与产物一致），单个 select 组 + MATCH
兜底，不含分流策略。令牌存 `settings.portal_nodes_token_enc`（懒生成），门户 PIN
门内展示复制/下载/二维码/重置；重置后旧链接立即失效。含全部凭据节点，链接泄露
等同节点池泄露。

**2026-11-23 日本 A（185.220.197.154）节点补全（构建 #405，修订 119）**：该机跑的是
**sing-box 1.14.4**（不是 hysteria2 服务），一个进程里同时开四个入站：TCP 443 是
VLESS+Reality（uuid / flow xtls-rprx-vision / server_name www.microsoft.com /
short-id 72708404faa2f8c7），UDP 443 是 hysteria2（BBR），UDP 8443 是 hysteria2
（brutal，up_mbps 50 / down_mbps 100 / ignore_client_bandwidth），TCP 10808 是
socks5。防火墙全空（ufw inactive、nft 无规则、iptables 全 ACCEPT），8443 不通
不是被拦。面板侧原「🇯🇵 日本自建 03」= hysteria2 185.220.197.154:8443 的密码、
sni、up/down 与服务端**逐项一致**（密码哈希 1120e598e5671fe9），配置本身没错；
本次新增 **🇯🇵 日本自建 04**（hysteria2 UDP 443，BBR，不带 up/down）与
**🇯🇵 日本自建 05**（VLESS Reality TCP 443），两者与 03 同机同密码，形成同一台
机器的三条独立路径（UDP 高位端口 / UDP 443 / TCP 443）。全部加入隐藏组
**🇯🇵 JP自建**（fallback，成员顺序 01→02→03→04→05）。**Reality 公钥必须从服务端
私钥推导**（RFC 7748 x25519，base64url 无填充），客户端还需 `client-fingerprint:
chrome`（渲染器对 reality-opts 自动补）——缺指纹时 mihomo 直接报
「REALITY is based on uTLS, please set a client-fingerprint」。产物级验证：三条
路径出口 IP 均为 185.220.197.154。改后快照
`policy/snapshots/2026-11-23-after-japan-a-nodes.json`（digest dcb4673069ab6298）。

**2026-11-24 配额路由优化（构建 #406，修订 120）**：按四机实测结论与向阳三项决定
（JP 重编号、恢复 8443、Emby 日本优先）调整。**JP 自建重编号**（四步轮换）：
01=VPS.TAXI-Hy2(443)、02=VPS.TAXI-Hy2(8443·恢复 brutal 50/100)、03=LegendVPS-Hy2、
04=LegendVPS-SS、05=VPS.TAXI-Vless，组序与编号一致；**US自建翻转**为
[Hy2, Vless]（hy2 实测 30.5 Mbps/170ms 是 vless 的 3.3 倍）。**国际媒体**自建序改
SG→JP→US（自动序 日→新→美）、**Emby** 改 JP→SG→US（向阳：66Cloud 只有 1TB 流量，
流媒体吃流量，日本 2TB+1TB 优先，SG 2TB 次之）——配额逻辑：流媒体走 SG(2TB)/JP(3TB)，
66Cloud(1TB) 留给日常主力与谷歌/AI。快照
`policy/snapshots/2026-11-24-{before,after}-quota-routing.json`
（digest 56bbc750→6924bb1e）。产物断言：JP/US 自建组序、国际媒体、Emby、8443 渲染
（up 50/down 100/skip-cert-verify）全过；8 自建节点测速全 ok。

**2026-11-25 SadIDC 美国快线 + 链式节点与谷歌三分法（构建 #414，发布 rev 128）**：
新机 **SadIDC 82.158.91.7**（Debian 13 / 2C / 2G / 20Mbps 精品线，`sada.magichub.top`）
上线，与 66Cloud 组成「中转机（快线、轻量直连）+ 落地机（66Cloud 优质 IP、大带宽）」结构。
**新增本地节点**：🇺🇸 美国自建 03（hysteria2 直连 `sada.magichub.top:33031`，出口本机 IP）、
🇺🇸 美国自建 04（hysteria2 链式 `sada.magichub.top:40334`，服务端 sing-box 经 hy2 隧道
落地 66Cloud `usb.magichub.top:58591`，出口 192.220.75.184；客户端只当普通 hy2 节点，零兼容成本）。
**US自建 组序改为 [04链式, 01(66 Hy2), 02(66 Vless), 03(SadIDC直连)]**——AI/风控组优先
命中 66Cloud 优质 IP 出口。**谷歌三分法（向阳定）**：新增可见组 **▶️ YouTube**
（select，[01, 02, US自建, 美国自动]，新远程集 `youtube`「youtube.mrs」）与 **✨ Gemini**
（select，[04, US自建, SG自建, JP自建]，新远程集 `google-gemini`「google-gemini.mrs」）；
🔍 谷歌服务 美国档首位插入 03 节点直引（剩余谷歌=搜索/浏览走快线）；规则序
`google-gemini → youtube → google`。表头自建服务区新增 `DOMAIN-SUFFIX,eoysky.com → DIRECT`
（sub2api 面板/API 经精品线直连）。快照
`policy/snapshots/magicpanel-policy-2026-11-25-{before,after}.json`
（digest ff895cea→bf3d89d2）。产物断言：03/04 渲染、US自建组序、两个新组、三处规则序、
providers 下发地址全过；面板测速 03=1246ms / 04=618ms / 18(66Cloud Hy2)=711ms（含
NAS→路由器透明代理链开销，仅供对比；真实延迟以路由器订阅刷新后为准）。
**同日终检（构建 #416，rev 130）**：🌍 国外域名（MATCH 总控）成员前置
`美国自建 01、02` 节点直引（日常兜底走 66Cloud 30Mbps，US自建退居第二梯队）；
补回「🇸🇬 新加坡自建 02」（VLESS Reality `sga.magichub.top:443`，MLKEM 开关开，
入 SG自建 = [01,02]，消除媒体组单点）。路由器模板（OpenClashConfig `f4ace00b`）同步三分法：
AI×5+PayPal/国外电商→`US自建优选`(01/02/04)、YouTube→`▶️ YouTube`(落地测速 01/02)、
Gemini→`✨ Gemini`(优选)、GitHub/容器/开发者→`落地测速`、故障转移与谷歌服务保持
`US自建测速`(含 03 快线)、Grok 规则与组并入 category-ai-!cn；ruleset 64/64 顶格。
面板与路由器双侧出口实证：Claude/Gemini=66Cloud、YouTube=01/02、搜索=03、漏网=01。
快照 `policy/snapshots/magicpanel-policy-2026-11-25b-{before,after}.json`（digest c2055386→329956d0）。同机另部署
sub2api（原生 systemd + PG17/Redis，见 `VPS脚本文档/VPS现役机器档案.md`）。

**2026-11-23 自建节点实测（4 台 VPS）**：报告见
`/Users/astral/Documents/MagicPanel-评审/2026-11-23-自建节点测试报告.md`，节点清单与
完整链接见同目录 `2026-11-23-自建节点清单与链接.md`（含凭据，勿外传；机器以服务商
代称：VPS.TAXI=185.220.197.154 东京、LegendVPS=216.23.100.46 东京、
66Cloud=192.220.75.184 洛杉矶、ISIF=152.175.65.196 新加坡）。
**四台 VPS 的节点配置与服务端逐项一致，无需改动。** 服务器自身出网 56–88 MB/s。
**brutal 与 BBR 的结论与线路状态相关**（两个时段各测一次）：晚高峰拥塞期（代理开启、
家宽被占）VPS.TAXI hy2:8443（brutal 50/100）中位 14.9 Mbps，hy2:443（BBR）塌缩到
0.85 Mbps；凌晨空闲期（代理关闭、ICMP 丢包四台全部 0%）排序反转，443（BBR）27.3
反超 8443（brutal）20.1。**合并结论：BBR 在拥塞+丢包下塌缩、干净时反超；brutal 定速
发送两个时段都稳（15–20 Mbps）——两条路径互补，适合同组 fallback，不是二选一。**
当年报告的「高位端口 UDP 丢包」与首轮实测的 25–45% 丢包都是「测试流量+透明代理」
叠加的拥塞假象，空闲时段四台到家宽 0% 丢包。
**使用体验排名（2026-11-24 直连复测）**：① VPS.TAXI（107ms/27Mbps 最均衡，双路径）
② 66Cloud（170ms/30.5Mbps 吞吐最稳、原生 NTT，大流量首选）③ LegendVPS
（125ms/14.5Mbps，作日本第二路径与 SS 备份）④ ISIF（晚高峰 0.2 Mbps、方差最大，
仅 SG 流媒体解锁价值，建议降级专用场景）。
测试方法要点：大文件测速在家宽被占时会整轮失败并被误读成节点故障，**改用 2MB 小包
×10 次连续测**才能得到稳定分布；每个节点测前必须校验出口 IP（`chatgpt.com/cdn-cgi/trace`
的 `ip=` 字段）与目标 VPS 一致，否则会被路由器透明代理链污染。**Xray v26.9.9+ 的
REALITY 节点手写客户端配置必须带 `support-x25519mlkem768: true`**，否则报
`REALITY authentication failed`（面板节点 13 的配置是正确示范）。

**2026-11-22 策略组优化（构建 #400，修订 114）**：按《2026-11-21 策略组优化评审稿》
与《2026-11-22 执行任务清单》完成三范围。**A**：修复三个内联规则来源 404
（2026-11-21 导入漏回填 `content`，经面板接口原样重存回填；防复发见 96d40c3）。
**B**：可见组 43→31——合并 11 个重复业务组（Grok/Copilot/国内AI/GitHub/容器/
OneDrive/Discord/Spotify/AppleTV+/Steam/新闻）、删除 🐟 漏网之鱼、隐藏 ♻️ 自动选择、
🇼🇸 台湾旗标改 🇹🇼；总控 🌍 国外域名 首项改 🚀 故障转移并移除 DIRECT，gfw/media/
MATCH/自定义代理集合改指总控；🔍 谷歌服务（向阳定图标）select，档位成员直接
平铺（美→新→日：US自建→美国自动→SG自建→新加坡自动→JP自建→日本自动，
「🇬 Google 当前地区」中间层已按向阳指示删除）；ChatGPT/Claude/国外AI 改
**fallback**（向阳 2026-11-22 指示：顺序调好后尽量用故障切换自动按序切换）；Telegram 收敛为 日/美/新+显式直连；
TikTok/Talkatone/加密货币/Emby 改 select；PT站点=[直连,路由回家]；Bahamut 只留
台湾自动；📹 Zoom 暂保留独立组待实测后决定是否并入即时通讯。新增 **🎬 Netflix**
可见组（向阳 2026-11-22 决定拆组：照新加坡媒体结构 SG自建→新加坡自动，实播验收
后再调）。

**节点优先级模板（向阳 2026-11-22 定稿）**：三个自建组改名去「测速」二字
（🇺🇸 US自建 / 🇯🇵 JP自建 / 🇸🇬 SG自建）。对节点敏感的业务组统一按
**US自建 → JP自建 → SG自建 → 美国自动 → 日本自动 → 新加坡自动 → ♻️ 自动选择**
排序——美国自建质量最好（伪家宽），日/新自建是机房 IP（速度要求高但质量要求
不高、要固定 IP 时优先日本，否则美国），新加坡自建主用流媒体解锁，「自动」
组全是机场节点（质量与 IP 不保证）。**终态（#384）**：「🐔 自建智选」聚合组已
**删除**（中间层意义不大，向阳指示展开），全部引用组直接按模板列三自建。
组类型按向阳指示尽量用 **fallback** 按序自动切换：总控/ChatGPT/Claude/国外AI
改 fallback。**高风控组收窄纯自建**（向阳 2026-11-22 逐组审查：AI 对 IP 质量最
敏感、面板机场节点 AI 检测零正证，脏 IP 风险大于可用性收益）：ChatGPT/Claude/
国外AI = 纯三自建（fallback，不加任何机场/自动选择尾部）；PayPal = 三自建+直连；
加密货币/Talkatone = 三自建+自动选择（尾部选项不影响 select 默认路径，供客户端
临时覆盖）；Telegram 保留机场备选 + 自动选择 + 直连。TikTok 判定为地域敏感
（地域决定内容池）保持地域聚集顺序 SG>JP>US 不变。**向阳面板手动调整**
（2026-11-22）：删「🇸🇬 新加坡媒体」建「🇸🇬 SG 媒体」（fallback，成员
[SG自建, JP自建, 🇸🇬 新加坡自动]，disney/hbo/primevideo/dazn/viu 五条指它）、
删孤儿「🇹🇷 土耳其自动」；本地节点新增 **🇯🇵 日本自建 02**（Hysteria2，
jpb.magichub.top:443）与 **🇯🇵 日本自建 03**（SS，jpa.magichub.top:28443），
已加入 🇯🇵 JP自建 组（节点直引）。本地节点只有被组显式引用才进产物
（use/filter 不会自动纳入未引用的本地节点），加节点后要手动加进对应组。
**日本自建重编号**（向阳 2026-11-22）：按质量排序 01=日本 B Hy2
（jpb.magichub.top:443）、02=日本 B SS（jpa.magichub.top:28443）、
03=日本 A（185.220.197.154:8443，临时不通）；JP自建 fallback 优先级同步为
Hy2→SS→A。注意节点重编号因 UNIQUE 约束需借临时名四步轮换。开发者/社交/电商/学术/
即时通讯/Zoom/故障转移本来就是 fallback。**保留 select**：Telegram/PayPal/
加密货币/Talkatone（账号风控，出口不自动跨国漂移；Telegram/PayPal/学术/Zoom
尾部保留显式直连手切）、游戏平台/苹果/微软/测速工具（直连首项，fallback 会
锁死直连）、🔍 谷歌服务（美→新→日档位降档要业务失败证据）。**不套用模板**：
故障转移（地区冗余兜底）、TikTok/Netflix/新加坡媒体/Emby（流媒体解锁 SG 优先）、
PT/非标端口/Bahamut。**媒体组媒体化调整**（向阳 2026-11-22 逐组审查）：
📺 国际媒体（宽泛影音兜底，fallback）与 🎥 Emby（select，私服手切）自建置首——
国际媒体 = [US自建, JP自建, SG自建, 美/日/新/港/台/韩/英/德自动, 其他, 家宽, 自动选择]
（自建稳定+大带宽+原生优先于机场）；Emby 按视频流吞吐序 [US自建(97M), SG自建(46M),
JP自建(14M), 美/新/日/港/台自动, 直连]（私服直连手切保留）。Google Voice 走
google 集合（`+.google.com` 后缀覆盖 voice/stun 等全部子域）→ 🔍 谷歌服务 →
美国档，未单独拆组。
**C**（96d40c3）：import_policy.py 导入后回填内联正文；validate.py 构建
门禁拦截「被规则引用但分发正文为空」的内联来源（remote/repo 未抓取为 warning）。
改前/改后快照 `policy/snapshots/2026-11-22-{before,after}-group-optimization.json`
（after 为 #387 最终态，digest 见快照文件，44 组 = 30 可见 + 14 隐藏）。🚀 测速工具
改 ⚡ 测速工具、🚀 故障转移改 🔰 故障转移、🌐 其他地区自动改 🌍 其他自动（向阳定图标，
引用已重映射；注意「其他地区自动」的 filter 长正则超过 GroupBody.filter 长度限制，
界面保存会 422——待放宽该字段后修复）。
总控最终
形态：fallback [US自建, JP自建, SG自建, 🚀 故障转移, 美/日/新自动, ♻️ 自动选择]，
DNS 四条 IP 规则仍单独走 🚀 故障转移不受总控影响。
土耳其/其他地区/家宽三个隐藏组已是孤儿（无任何引用），后续确认后可删。

**2026-11-20 节点名补充关键信息（第二次改名格式修订）**：订阅节点改名格式从
「旗帜 国名 序号」升级为「旗帜 [机场代码] 国名 关键信息 序号」，例：
`🇭🇰 [夜] 香港 家宽 2x NF 07`。机场代码 = 来源名首个汉字或前两个字母
（神龙机场→神、DSM→DS），撞码逐字加长到唯一；家宽/倍率/解锁服务只在
原节点名正则命中时保留（家宽/住宅/ISP/residential；0.5x、×2、x2、2倍、
倍率0.5、rate:0.5 统一成「0.5x」形态；Netflix→NF、ChatGPT→GPT、
YouTube→YT 等最多 3 个，只有泛「解锁」标「解锁」）。序号按「机场+地区」
从 01 起分。provider 路径（normalize_name）同步用机场代码替换完整来源名。
**改名会联动组过滤正则**：组过滤匹配的是 rename 标签（filter_names），
「🇯🇵 游戏 UDP 候选」（组 208/242）的 `^🇯🇵 \[神龙机场\] 日本 0[1-4]$`
已改为过渡正则 `^🇯🇵 \[(神龙机场|神)\] 日本 0[1-4]$` 同时兼容新旧标签。
改动节点名前先检查 proxy_groups.filter 里有没有写死来源括号标签。

**2026-11-20 本地节点统一命名与编辑修复（构建 #335）**：本地节点改名
「美国NTT 01/02 → 美国自建 01/02」「日本软银 01/02 → 日本自建 01/02」（组员引用随
`refresh_node_projection` 自动重映射；随之变化的是「日本自建（仅移动）」「美国自建」等组名）。
修复本地节点编辑被「未知协议参数字段」永久卡死：update_node 剔除存储侧协议白名单外的
遗留键（客户端提交侧仍 400 严格），openLocalEdit 经 reveal 回填表单——列表接口自
b878a12 只回 public_params，`row.params` 恒为 undefined 导致编辑框全空。渲染器服务
别名只按 MEDIA_ROUTE_REGIONS 生成（netflix→JP、hulu/hbo→US），不再向 proxies 写
孤儿别名节点。Netflix 日本组成员 = 有近期 JP 片库证据的节点，含机场标签为台湾但
实测 JP 出口的节点。改前/改后快照在 `policy/snapshots/2026-11-20-{before,after}-rename.json`。
手机专属组「🇯🇵 日本软银」（variant 2）名称未随节点改名，是否同步改名待向阳定。
Claude/Perplexity 在美/日自建节点均为 Cloudflare 人机校验（无法判定），不据此改 AI
分流；Netflix 日本播放仍需向阳实测。

**2026-11-17 全视图逐页巡检**：前端 16 个视图（含 Login/Setup/Portal）全部纳入
挂载冒烟测试（`src/v2/allViews.spec.js`，用生产数据形状做夹具）；修复 10 处
`rows.value = resp.items` 无 undefined 兜底的整页崩溃隐患（`?? []`）。新增页面
时必须跑该冒烟，防止「引用未定义变量→整页空白」一类事故复发。

**2026-11-17 magic-sets 审计与节点规范化、网络体检**：magic-sets 已按产物顺序
做「首个命中」仿真瘦身（23 条死条目删除、zoom.us 归位、补 Element/Matrix/IP 查询站，
script/ 与 rewrite/ 目录已删——Stash 专属片段零引用）。构建与 provider feed 分发端
统一节点名称规范化（`services/node_rename.py`，2026-11-18 起格式为
「旗帜 [机场·标签] 国名 🔓徽章 序号」——机场提前使同机场节点在客户端排序时
聚拢；🔓 徽章仅当该节点 AI 六项检测全解锁时加（`node_name_unlock_badge`
开关默认关），单向变化防名字抖动；占位节点丢弃，本地节点不动），系统设置
可关（`node_name_normalize`，默认开）。能力徽章多维：🔓 AI 全解锁 / 🎬 流媒体解锁 / 📺 Netflix 高级版（2026-11-19）。
节点质量流水线使用隔离 Mihomo 核心逐节点切换，按延迟、下载速率、业务证据分级。
早期 600 ms 草案已由后续 3000 ms 交付口径取代；人机校验、普通网页可达和真实业务证据分开。
探测、命名、分流及设备验收以[节点质量、业务分流与客户端交付](docs/superpowers/specs/2026-11-19-业务分流与客户端交付.md)为入口，
未完成的优化见[全域体检与优化建议](docs/superpowers/specs/2026-11-20-MagicPanel-全域体检与优化建议.md)。

**维护说明（2026-11-15）**：代码行为以仓库实现为准；线上策略与部署状态以实际查询为准。
本文中的构建号、条数与 `sort` 清单是注明日期的记录，不能直接当作当前线上状态，
更不能据此覆盖用户后来在面板里做的调整。

**2026-11-16 DNS 修订**：公共多源 DoH/DoT 是海外解析默认方向；HK/KR 自建
DoH 与 18443 入口降级为可选，不再是 Router Final 必备。单一公共服务商也不可
作唯一前提；须杭州电信/中国移动分别实测。两 A 记录可休眠，但不得进入当前
候选配置。详见家庭网络运行契约 §4.0。

**2026-11-16 Router 核心锁定与密钥轮换**：稳定 Mihomo `v1.19.34` 已由
`restore-stable-core.sh` 每分钟校验；若被 Smart/alpha 覆盖会自动恢复并重启。
面板 controller secret 和代理 auth password 已轮换，新值只保存在 R6S
`/root/mp-final-prep/20261116T151500/` 私密文件中，不写入仓库/日志/回复。
Mihomo WARNING 若来自 NAS BT peer 连接拒绝/超时，属于 P2P 正常失败，
不代表 Google/AI/国内业务故障。

**2026-11-16 Router 当前态**：R6S 基线备份在路由器 `/root/mp-final-prep/20261116T151500/`；
live 已切 `MagicPanel-默认.yaml`，OpenClash 进程使用官方 Mihomo `v1.19.34`，
Smart 已关闭，宽泛 CN-IP 提前旁路已关闭，IPv6 LAN→WAN 已阻断，
`find-process-mode=strict`。当前 NAS 生产构建 #262。WireGuard peer 清单已持久修正。

**2026-11-17 UDP 代理已开启（向阳批准）**：`enable_udp_proxy=1`，nft `openclash_mangle`
TPROXY :7895 劫持 LAN UDP。境外 UDP 经代理链（美国VPS 的 vless TCP 隧道中转），
国内 UDP 命中 cn/cn-ip 保持直连；境外 QUIC/443 仍被约束 34 规则 REJECT 回退 TCP。
开启动因：杭州电信对境外高位端口 UDP/QUIC 系统性丢包，hy2 节点（自建与机场）此前
全超时；开启后面板测速与家庭 WiFi 下 hy2 全部可用（NTT02 657ms、软银01 709ms）。
UCI 改前备份：路由器 `/etc/openclash/backup/openclash-uci-backup-*` 与
`/tmp/openclash-uci-pre-udp`；回滚：还原该文件后 `uci commit openclash &&
/etc/init.d/openclash restart`。观察项：境外 BT peer 的 UDP 进隧道带来的带宽与
日志噪声（属 P2P 正常失败，不代表故障）；游戏主机境外 UDP 走隧道后 NAT 类型变严。
HK/KR DNS 入口与生产化外部 guard 仍阻塞 Router DNS/Gateway Final；不要用公共 DoH 或
旧 watchdog 冒充已验收。详情见 2026-11-16 运行手册 2C。

**2026-11-16 方案收敛**：生产已切换到默认方案为唯一 canonical 方案；`自建美日`
已停用并移出门户/新构建。旧 `?variant=自建美日` 链接由 feed 回退默认产物并带
`X-MagicPanel-Variant-Fallback: default`。不得未审查就重新启用旧方案。
Google/AI 默认组成员顺序为 US(NTT/机房/自动) -> SG -> JP；TikTok 先 JP/SG；
开发/社交优先 NTT/机房，再回退默认代理。变更证据见 2026-11-16 运行手册。

**2026-11-16 实施快照**：核心探测/预算/资格/Google planner/资源冻结/发布CAS/旧feed冻结已进入
本分支，详见[实施状态与运行手册](docs/superpowers/specs/2026-11-16-MagicPanel-V2-实施状态与运行手册.md)。
`v2_runtime_activation` 仍为 `staged`；真实设备/R6S 验收前不得激活自动外发。
发布新调用必须携带 `expected_release_revision` 与 `idempotency_key`；缺核心不得自动生产。
旧 feed freeze 生产 arm 必须基于 R6S 实际缓存基线和 owner 回执。

**V2 实施入口**：[总体设计与审查稿](docs/superpowers/specs/2026-11-15-MagicPanel-V2-总体设计与审查稿.md)
及其配套规范记录了全面迭代。用户已于2026-11-15授权方案定案后完整实施、提交、部署和测试；现状约束在对应迁移生效前继续有效，不能把未来能力当成已经部署。

**Google 地区优先级（用户于 2026-11-15 最后澄清）**：家宽/住宅、机房、机场所有来源，
访问 Google/Gemini/Gmail/YouTube 及关联业务时，严格按 **美国 → 新加坡 → 日本** 回退。
只要还有合格可用的美国候选就用美国；同档内再按业务可用性、IP 质量与稳定性排序，
不能因新加坡/日本更快就越级。仅当前主备失败、未测/未知或预算跳过，不等于整档失败。
Google 专项规则优先于 AI/影音等主题集合，Gemini 归 Google 路径，不新增 Gemini 前台组。
三档均不可用时普通 Google 策略明确失败，不加入 DIRECT；核心整体故障则按用户批准的 BASIC_WAN 恢复原生WAN（含海外尝试）并告警。
“仅美国、美国耗尽即拒绝”和“非美禁止 Google 专项探测”的先前解释撤回；
共同依据见 [Google 选路策略](docs/reference/Google选路策略.md)。策略实现与生产生效分别记录，不将文档定案当作部署完成。

**后续执行入口**：[Agent总执行方案](docs/superpowers/plans/2026-11-15-MagicPanel-V2-00-Agent总执行方案.md)及01–04子计划。最新数字/默认值只认[自动恢复与检测策略](docs/reference/自动恢复与检测策略.md)，网络/DNS/WG/SQM只认[家庭网络运行契约](docs/reference/家庭网络运行契约.md)。

**用户最新运行边界**：杭州电信家宽（下行1000M，上行常见60–80M/峰值100M），外出中国移动；家庭R6S统一透明，NAS/Mac mini/AppleTV不装第二套日常代理；外出Android/MacBook/iOS Stash，WG只回家内网。最终采用auto_stable_v1自动恢复，不能以周间人工处理交付。主用终端分别验能力，不把iOS官方能力推断给Android。

**客户端确认**：统一使用Stash；Android商店包`ws.stash.app`、用户截图版本1.1.10（2026-11-04），Windows即使早期版本也保留兼容目标。商店信息不代替实际设备installed version与cron/API/强制叶/鉴权读回能力回执。

**路由器准备与切换**：用户明确允许先写手册/备份、交付不执行的救援脚本、冻结独立自动更新等安全准备；当前不动WAN/LAN/PPPoE/实际DNS转发，不重启OpenClash、不拉订阅。候选接管/双栈/DNS配置另存，不提前写进会被后台加载的live层。成套网络切换与订阅更新仍在代码/隔离/恢复门禁通过后最后执行；不得通过NAS早发feed间接绕过。已授权范围不用反复请求同一许可。

**路由器包管理禁令**：不得运行`apk upgrade`（含指定包）或用批量重装/升级循环替代；用户明确要求规避该风险。新增依赖先模拟并核对实际变更，基础包/内核升级不属于本次代理优化。`server-ops`已同步该限制。

2026-11-15准备期已完成备份、惰性救援脚本与7项更新调度冻结；核心PID/运行配置和网络/DNS摘要未变。细节与恢复命令只维护在本机私密`docs/network/2026-11-15-路由器手动恢复与分阶段优化手册.md`，这不是最终网络迁移完成。

**稳定性优先**：[稳定性与覆盖验收](docs/superpowers/specs/2026-11-15-MagicPanel-V2-稳定性与覆盖验收补充.md)。先拦坏规则/陈旧自动发布/缺核心证据/最终业务误分流，生产达标以真实回执为准。

## 0. 开工前：先让代码与环境对齐

**唯一事实源是 GitHub 的 `astralwaveorg/MagicPanel` `main`。** NAS 上的
`/opt/magicpanel` 是**部署副本**，由 `scripts/deploy.sh` 从工作区同步过去。
两边不一致时以仓库为准，先把差异查清楚再动手，不要直接在 NAS 上改代码。

```bash
git status --short            # 先检查已有改动，避免覆盖或混入本次任务
git branch --show-current     # 确认当前分支
git pull --ff-only            # 工作区适合更新时再拉取；失败先查原因
git log --oneline -5          # 确认自己在哪个提交上
```

`git pull` 不保证拒绝所有脏工作区；不要自动提交、stash 或丢弃用户已有改动。
`deploy.sh` 要求工作区干净且当前提交与 GitHub 的 `main` 一致，只同步该提交中的文件。
开发仓库可以在 Windows、Mac 或其他工作机上，以当前工作区为准，不限定 Mac mini；
NAS 上的部署目录不能当作开发仓库。

涉及代码部署或线上排障时，核对线上跑的是哪一版：

```bash
ssh archon@10.0.1.2 'docker inspect magicpanel \
  --format "{{.Image}} {{.State.StartedAt}} {{.State.Health.Status}}"'
ssh archon@10.0.1.2 'docker images --format "{{.ID}} {{.CreatedSince}}" | grep magicpanel'
```

结合镜像 ID、构建时间、启动时间与最近一次 `deploy.sh` 记录核对；时间只能辅助判断，
不能单独证明线上对应哪个 Git 提交。

**默认交付要求（2026-11-19 用户确认）：** 所有仓库改动先自检、在本地提交并推送到 GitHub，然后构建部署到服务器。核对运行镜像对应此次提交，并验证受影响的页面或接口可用。遇到阻塞说明哪一步未完成。涉及数据库内的策略改动，还须按下表发布并保存快照。

```text
代码：对齐仓库 → 改代码 → 本地自检 → 提交并推送 main → deploy.sh → 核对镜像、页面 / 接口
产物逻辑：上述代码部署完成 → 创建构建 → 发布测试 → 验证 → 发布生产 → 客户端拉取核对
策略数据：查询并导出改前快照 → 改数据 → 自检并导出改后快照 → 构建发布 → 客户端拉取核对
```

**先区分改动类型**，按实际影响验证与发布：

| 类型 | 内容 | 生效条件 |
| --- | --- | --- |
| **代码** | `server/`、`src/`、`scripts/` | `deploy.sh` 重建容器后立即生效 |
| **产物逻辑** | 渲染器、源码基线默认值等 | 部署代码后还要手动创建构建并发布，见约束 40 |
| **策略数据** | 方案、规则、策略组、来源、引擎默认配置 / 引擎平台配置等（NAS 的 `data/magicpanel.db`） | 「创建构建 → 发布测试 → 发布生产 → 客户端拉取核对」；仅改数据无需重建容器 |
| **设备独立配置** | 基础配置的设备层 | 分发时实时叠加，客户端下次拉取生效，无需重新构建发布 |
| **纯文档** | `AGENTS.md`、`docs/` 等，未改变代码与运行配置 | 核对实现、链接和示例，按默认流程部署；无需刷新客户端 |

策略数据**不在 git 里**，靠 `policy/snapshots/*.json` 存档，见下节。

## 策略快照（让不在 git 里的策略可复现）

方案、规则顺序、策略组这些内容只存在数据库里，git 看不见。改动前后各导一份，
用 `-before` / `-after` 等后缀区分，避免同一天覆盖备份。以下 Bash 命令在能访问数据库的 NAS 工作目录执行：

```bash
# 导出（无凭据，可入库）
python scripts/export_policy.py --db /opt/magicpanel/data/magicpanel.db \
  --out policy/snapshots/$(date +%F)-before.json

# 复现（先 dry-run 看 digest 与条数，再正式导入；会自动备份数据库）
python scripts/import_policy.py --db /opt/magicpanel/data/magicpanel.db \
  --in policy/snapshots/2026-11-15-before.json --dry-run
```

当前导出格式为 **schema 2**，含 `variants` / `rules` / `proxy_groups` / `rule_providers`
四张表；`rule_providers`
走**列白名单**，**不含** `content`（MRS 二进制缓存）与 `proxy_url_enc`（加密订阅地址）；
`sources` / `local_nodes` / `devices`（含令牌与节点凭据）整体不导出。
导入会替换快照中非空的策略表，**不是按方案增量合并**；旧 schema 1 快照缺少
`variants`，不能用来完整恢复多方案状态。正式导入前核对方案、引用对象与目标数据库，
导入后重新构建发布。导出的快照要带回开发仓库保存，不能只留在 NAS 部署副本。

## 硬性约束

1. **结构化内容不能被配置层覆盖。** `proxies` / `proxy-providers` / `proxy-groups` / `rule-providers` / `rules` 五个键，基础配置（引擎默认配置 / 引擎平台配置 / 设备独立配置）、平台扩展、拓展模块都不许写，服务端硬校验。
2. **兜底规则永远在最后。** 规则按 `sort` 排序，`MATCH` 之后不能有规则（`FINAL` 代码里仍作兼容处理，但界面建不出来）。
3. **规则类型按引擎白名单校验。** Stash 与 Mihomo 支持的类型不同，超出白名单客户端会加载失败。
4. **引擎平台唯一。** `(engine, platform)` 只能有一个，重复写入 409。
5. **列表的合并语义分两种**：引擎默认配置 / 引擎平台配置 = 整体替换；设备独立配置 = 追加。差异计算、层级合并、分发叠加三处必须一致。
6. **设备独立配置的键跟着设备的引擎平台走**，换平台时要自动换键，否则配置静默失效。
7. **改数据库结构走迁移**，不要手动 `ALTER TABLE`；迁移必须幂等。
8. **凭据不进仓库。** `scripts/check_secrets.py` 会在 CI 与部署前拦一次。
9. **改引擎默认配置要核对官方文档。** `scripts/check_engine_defaults.py` 逐键对账，出处要落在 `official-example/`。
10. **命名只有三个层级名**：引擎默认配置 / 引擎平台配置 / 设备独立配置，代码、注释、界面、文档保持一致；页面叫「基础配置」，引擎平台自己的片段叫「平台扩展」。
11. **地区线路的自动测速一律 `url-test`，跨地区只留一个「⚡️ 自动测速」组。** 日常组按实测延迟自动选（`interval` 600、`tolerance` 100）。跨地区择优用 url-test（成员 = 各地区自动组 + 本地机房节点），不另建 `fallback` 兜底组：fallback 只保证连得上、不保证快，限速节点会被一直用下去。同一地区不要建「稳定 / 优选」两套组。注意 url-test 组是**隐藏**的（前台不显示），规则不能直接指向它，要用可见 select 包住（见约束 14）。

    本条600秒及下表自建来源优先是旧产物基线。V2由`auto_stable_v1`显式检测预算/当前路径恢复取代隐含递归测速；AI按实测业务可用性、信誉、稳定性排序，来源身份不永久加分。新方案通过对应门禁后按新合同迁移，不提前修改旧生产或把native fallback当完整业务恢复。

    **2026-11-10 起有四个例外，都是有明确业务理由的 `fallback`，不要改回 url-test：**

    | 组 | 类型与顺序 | 为什么必须是 fallback |
    | --- | --- | --- |
    | `🏢 自建优先` | fallback：日本机房01→02 → 美国01→02 → 香港01→02 → `⚡️ 自动测速` | 自建机房节点质量高于机场，需要**按序优先**；url-test 会随延迟抖动在日/美/港之间乱跳，长连接与会话粘性变差。注意 `local_first=1`，否则渲染时 `⚡️ 自动测速` 会排到自建节点前面，fallback 永远选不到自建 |
    | `🔍 谷歌服务` | 严格地区档位：美国 → 新加坡 → 日本，各档内再择优 | 包括 Gemini / Gmail / YouTube 及关联依赖；全部适用美国候选失败才进新加坡，新加坡全失败才进日本。不可因延迟或来源类型越级；未知/未测不算整档失败 |
    | `🧠 人工智能` | fallback：美国机房 → 美国自动 → 日本机房 → 日本自动 → 新加坡自动 | AI 对 IP 质量与地区敏感，部分服务不支持香港，**明确排除香港**；顺序固定 美→日→新 |
    | `🎞️ 国际影音` | fallback：新加坡自动 → 日本自动 → 香港自动 | 流媒体解锁按地区，逐级降级而不是按延迟择优 |

    规则顺序同样有要求：**Google 三件套（`search`/`youtube`/`google`）必须排在 AI 规则之前**，否则 `gemini.google.com` 会先命中 `category-ai-chat-!cn` 落到 `🧠` 组（虽然也是美国，但语义不对且改 AI 组会连带影响 Google）。
12. **正常代理模式兜底为`MATCH → 默认代理`。** 这降低未收录海外域名误直连的风险，不能据此断言任何漏规则都只影响速度；国内服务仍须通过独立DNS、明确直连及末端国内IP规则验证，地区锁服务还要验证对应出口。核心整体故障的BASIC_WAN是用户批准的独立救援状态，不修改普通MATCH政策。
13. **地区维度只保留两类组**：各地区单独命名的组 + 机房组（🇺🇸 美国机房 / 🇯🇵 日本机房）。机房组只放本地机房节点，供"重点标注"用；不要按"散节点"另开同地区组。每个地区是**两层**：内层 `XX自动`（隐藏 `url-test`，自动测速）+ 外层 `XX`（可见 `select`，规则只指向它）。命名规范：内层带"自动"后缀且有空格（`🇭🇰 香港自动`），外层无空格（`🇭🇰香港`）。
14. **规则目标必须是前台可见的策略组。** 客户端前台只显示可见组，指向隐藏组等于"分流了但用户选不了节点"。做法是可见 `select` 包住隐藏 `url-test`：规则指向可见组，可见组成员是隐藏自动组 + 地区正则过滤出的节点。产物里不允许出现任何指向 `hidden: true` 组的规则。
15. **引擎平台配置里的 `_direct_domains` 会置顶成直连规则**，排在所有用户规则之前。域名一旦进了这份列表，用户集合里针对它（或它的子域）的条目就是死规则——用户规则改不动它。要让某个子域走别的线路，得先把主域名从 `_direct_domains` 里摘掉，再确认 `self-hosted` 之类的集合能兜住其余子域。
16. **「引擎默认配置」层参与渲染，改它对产物生效。** 产物基线 = 源码内置默认值 `base_config.py` 的 `default_doc(engine)`，叠加用户在「引擎默认配置」层的覆盖（记录在 `(engine, "", 0)`）。渲染层必须复用 `base_config_service.scope_layers()`，不要自己再取一遍源码常量——否则界面显示的生效值与产物内容会不一致（曾出现过"界面上改了没反应"）。所有配置改动落在引擎平台配置层 `(engine, platform, device_id=0)` 或设备独立配置层。
17. **策略组成员可以直接写本地节点的产物标识**（如 `🇯🇵 日本机房 01 (机房)`），成员顺序就是产物里的优先级，可以把节点插在组中间；`local_nodes` 字段则是整组追加到首或尾。判定"这个名字是谁"只认 `local_nodes.display_name()` / `display_index()` 这一个事实来源——校验器、渲染器、数据自检、界面都不许自己拼一遍「名称 (类型)」，否则节点改名或换类型后会集体失效。
18. **不同节点来源可能有同名节点**，客户端按名字去重会互相覆盖，可用节点数会凭空少一截。每个来源在「节点来源」里配一个「节点名后缀」（下发为 `override.additional-suffix`），保证全局节点名唯一。
19. **节点来源有两种下发方式**：`provider`（写进产物的 `proxy-providers` 段，客户端自己拉取更新）或 `inline`（节点写进产物顶层 `proxies`）。只有 `inline` 的节点会进客户端的 GLOBAL 组——Clash/Stash 的 GLOBAL 只收顶层 proxies 与策略组，provider 里的节点进不去。inline 的代价：机场换节点要重拉订阅才生效；机场订阅只保留 `proxies` 段，机场自带的 rules/dns/策略组不进面板。两种模式下「只分发可用节点」都要生效：provider 模式在 feed 端过滤，inline 模式在构建时按测速结果剔除（`sources.excluded_nodes`），漏掉哪一边这个开关就会静默失效。
20. **规则内容源是独立仓库 `astralwaveorg/magic-sets`，由后台「自主维护」页托管。** 主仓库不再有 submodule 引用（`.gitmodules` 与 `magic-sets/` 已删除）；仓库地址、分支、鉴权凭据存在 `settings.deps_*`，容器运行时把仓库 clone 到 `/app/data/deps/rule-repo`，面板在「自主维护」页里浏览、编辑、提交、推送。仓库分 `rule/`（规则集合）、`script/`（Stash 脚本）、`rewrite/`（HTTP 重写）三个目录。

    面板的规则集分四层：**自维护层**（仓库里的 `rule/*.yaml`，当前 13 个集合，在面板里是 `kind='repo'`，内容由同步写入，**不再经 jsDelivr 中转——推上去面板的 `/res/rule/<name>` feed 立刻是新内容，没有 12 小时 CDN 缓存**）；**上游通用层**（MetaCubeX/meta-rules-dat 的 mrs，`kind='remote'`）；**上游应用集合层**（blackmatrix7/ios_rule_script 的 `rule/Clash/<集合名>/<集合名>.yaml`，yaml，行为 `classical`，一条文件混多种规则类型，如 `XiaoMi`——**不进自维护仓库**，那是自维护层）；**第三方成品库**直接引别人的成品规则直链（mrs、行为 `domain`）。**广告拦截原则（2026-10-31 向阳定稿）：宁可不拦截，不能误拦截。** 曾引入 `TG-Twilight/AWAvenue-Ads-Rule` 的 `No.Unwelcome` 变体（875 条）做广告拦截，排查发现黑盒列表里混有功能性域名（京东 `mapi.m.jd.com`、京东图片 `img2.360buyimg.com`、淘宝风控 `audid-api.taobao.com`、微信视频号 `wxsnsdy.tc.qq.com`、乐播投屏认证 `vipauth.hpplay.cn`、小米系统组件 `api.installer.xiaomi.com` 等），且 mrs 整体生效无法逐条裁剪——已删除其两条规则并停用该来源（来源保留，随时可重启用）。现行广告拦截只走自维护 `magic-reject`（4 条纯 Google 广告域，零误杀）。要扩充广告拦截，往 `magic-reject` 里逐条加自己核实过的域名，不要整包引第三方列表。

    **注意区分两个广告拦截层（2026-11-10 补充）**：上面说的是**客户端配置层**（mihomo/Stash 的 `magic-reject`），仍然只保留 4 条纯 Google 广告域。家庭网络另有**路由器 DNS 层**（R6S 上的 AdGuard Home，配置在 `/etc/adguardhome/adguardhome.yaml`，属部署环境、不在本仓库）：启用 AdGuard DNS filter（约 18.7 万条）+ AWAvenue `Only.Ads` 变体（661 条，只广告、不含遥测/钓鱼），并配 35 条白名单（微信/淘宝/Apple 全系/Steam/支付，小米只放行功能性接口 `a0.app`/`api.installer`/`a.market`/`video.market`）。两层职责不同：DNS 层对全屋生效、能用白名单精确收敛；客户端层要跟配置走，过激会污染所有人的解析。**改 DNS 层请动路由器，不要把列表塞进 `magic-sets`。**

    **自维护层的集合一律用 `behavior: classical`**：条目量不大，但类型可以混着写，域名、IP 段、进程名放进同一个文件，一个规则就能表达一整类分流意图。`classical` 里没有 `domain` 行为那种「`+.` 是后缀、不带是精确」的简写，`+.example.com` 要写成 `DOMAIN-SUFFIX,example.com`，`example.com` 要写成 `DOMAIN,example.com`——写错会把精确匹配放宽成整个域。

    **改了自维护集合，客户端不会立刻看到——那是客户端自己的缓存，不是面板的**。客户端把规则集按 `rule-providers` 的 `interval` 存在本地（`path` 指定的位置），更新订阅只换规则表、不换集合内容；集合内容要等客户端自己重新下载。产物里的这个 `interval` 取自规则来源的 `client_interval`，为 0 时回落到来源的 `interval`（默认 86400）。2026-10-26 已把 13 个自维护集合的 `client_interval` 统一设成 **21600（6 小时，与上游通用集合一致）**；要更快就调「规则来源 → 客户端更新间隔」。强制刷新某个规则集可以打控制器的 `PUT /providers/rules/<name>`（Mac 上 `stash provider update <name>` 在 Stash 4.4.0 上返回 404，不可用）。

**集合文件名一律带 `magic-` 前缀**，表示是自维护的（`magic-chat` 而不是 `chat-ext` 这类后缀命名）。当前 13 个集合按目标组分文件：一个目标组一个文件，规则只写一条指向它：

| 集合 | 目标组 | 内容 |
| --- | --- | --- |
| `magic-jp` | 🇯🇵日本 | 日本线路域名 + 韩国固定 IP 段 |
| `magic-direct` | DIRECT | 自建服务域名与国内直连站点 |
| `magic-process` | DIRECT | 本地传输、同步与远控类进程名 |
| `magic-reject` | REJECT / 🛑 广告过滤 | 最小广告域名集 |
| `magic-proxy` | 🚀 默认代理 | IP 查询、云服务、自建与金融站点域名 |
| `magic-game` | 🎮 海外游戏 | Steam 下载 CDN（服务器在境外） |
| `magic-us` | 🇺🇸美国 | 美国区域域名（`behavior: domain`，唯一例外） |
| `magic-google` | 🔍 谷歌服务 | 谷歌服务补充域名 |
| `magic-microsoft` | Ⓜ️ 微软服务 | 微软服务补充域名 |
| `magic-chat` | 💬 即时通讯 | 小众聊天应用域名 |
| `magic-social` | 👥 海外社交 | 小众社区平台域名 |
| `magic-adult` | 🚀 默认代理 | 成人内容站点域名 |
| `magic-dev` | 🚀 默认代理 | 开发者平台、工具与包源域名 |

改集名的顺序：先在仓库里改文件名与文件头，再在面板上把规则来源改名（规则引用会自动跟着改），最后把引用它的规则值改成新名字。

    集合名 = 仓库文件名去扩展名（文件名是引用键），中文展示名写在文件头注释里。**集合含 IP 段时用它的 `_No_Resolve` 变体**（`<集合名>_No_Resolve.yaml`），IP 条目自带 `no-resolve`，客户端遇到域名请求不会为这条规则白做一次 DNS 解析；`DMM` / `JOOX` / `KakaoTalk` / `Naver` / `Yandex` / `Twitch` / `Amazon` 都是这种。blackmatrix7 的 `rule/Clash/` 目录实际有 666 个集合目录，可用的不止 README 里列的那些。

    面板抓取后存进 `rule_providers.content`，产物里的 rule-providers URL 仍指向面板自己的 `/res/rule/<name>` feed 端点，客户端从面板拉、不直连 GitHub（**客户端协议不变**）。

    `script/` 与 `rewrite/` 片段默认停用：脚本会改写全部请求的 UA，重写依赖 HTTP 引擎与设备信任 CA，而拓展模块没有按设备生效的粒度。仓库托管实体的内容只读，改动只在自主维护页做；启用状态归面板。
21. **规则顺序就是优先级**：客户端从上往下第一条命中即生效，所以顺序必须按「越具体越靠前、同一目标组聚成一块」排。

    **自维护（`magic-` 前缀）的规则排在整张表最前面**，其余规则按下面的十一块排。**整张表的顺序由向阳自己在界面上排，Agent 不要整体重排**——新增规则时插到对应分组块里、或加到表头的 `magic-` 区，然后交给向阳微调。（2026-10-26：Agent 按十一块整体重排过一次，把向阳刚排好的顺序覆盖了，规则顺序因此以面板界面为准。）当前 123 条规则（`sort` 0–122；2026-10-27 在表头 IP 区新增 `120.53.53.53/32` / `223.5.5.5/32` 两条国内 DoH 直连规则（sort 4–5），其后 sort 整体 +2，下面各块的区间数字未逐一改写，**以面板实际顺序为准**）：**开头是自维护区**（其后按十一块排）——① 本地与保留地址直连（14–16）② 网络层直连（17–20，`private` / `private-ip` / `dns-direct` / `direct-ports` → DIRECT）③ 广告（21–22，Stash 三平台用 `REJECT` 字面量、其余平台用「🛑 广告过滤」策略组）④ 设备专属直连（23–25，`connectivity-check` / `mirror-accelerate` / `lvsp-direct` → DIRECT）⑤ Steam 香港（26，`steam-cn`）⑥ **小而明确的直连集合**（27–37，`ai-cn` / `apple-cn` / `apple-push` / `apple-push-ip` / `PrivateTracker` / `microsoft-cn` / `games-cn` / `pt` / `trackers` / `AmazonCN` / `XiaoMi`）⑦ 服务分组（38–96，同一目标组连续成一块）⑧ 路由回家（97–98）⑨ 通用代理兜底（99–115，云服务商集合 `aws` / `azure` / `cloudflare` / `cloudflare-ip` / `digitalocean` / `vercel` / `netlify` / `oracle` 与 `proxy-bm7` / `proxy-domain` 在「🚀 默认代理」块末尾；`biliintl` → 🎞️ 国际影音、`onedrive` → Ⓜ️ 微软服务也排在这一段）⑩ **大而泛的直连集合**（116–117，`cn` / `cn-ip`）⑪ `MATCH`（118）。

    **大而泛的直连集合一律往后排**：`cn`（110k 条）、`cn-ip`（10k 条）排在强制代理与服务分组之后、`MATCH` 之前。理由是它们会把**所有**国内域名先拦去直连，任何一条更具体的规则都轮不到——2026-10-25 的 v2ex 故障就是这么来的：`cn-services` 里的 `+.v2ex.com` 抢先命中直连，而 `proxy-domain` 里写的是笔误 `+.v2ex.co`（`v2ex.co` 根本没有 A 记录），两条凑在一起让强制代理彻底失效。改成「先分流、未列出的兜底走代理」之后，漏配一条直连规则只会让线路不最优，不会让服务打不开。反过来，**小而明确的直连集合仍留在服务分组之前**，它们条目少、指向明确，抢先命中是对的。

    第 ⑦ 块内部再分三层，顺序不能乱：**地区锁服务**（🇯🇵日本 / 🇹🇼台湾 / 🇭🇰香港 / 🇺🇸美国 / 🌍欧洲）→ **主题细分**（🛒 跨境电商 / 🪙 加密货币 / 💬 即时通讯 / 👥 海外社交 / 🎞️ 国际影音 / 💻 开发工具）→ **宽泛合集**（`media` / `disney` / `social` / `games` 等）。地区锁服务必须早于宽泛合集：`media` 里有 10 条 BBC 域名、`disney` 里有 47 条 Hulu 域名，宽泛合集先命中就播不了英国版权区、看不了 Hulu。

    五条硬约束：`MATCH` 永远最后；`ai-cn` / `apple-cn` / `microsoft-cn` / `games-cn` 必须早于对应父集合（`ai-cn` 早于人工智能那三个上游集合 `openai` / `anthropic` / `category-ai-chat-!cn`，`apple-cn` 早于 `apple`，`microsoft-cn` 早于 `microsoft`，`games-cn` 早于 `games`），否则国内子集合整体失效；`steam-cn` 必须早于 `cn`（实测与 cn 重叠 13 条，Steam 中国的域名）；云服务商集合（`aws` / `azure` / `cloudflare` / `cloudflare-ip` / `digitalocean` / `vercel` / `netlify`）与 `proxy-bm7` / `proxy-domain` 放在「🚀 默认代理」块末尾，且**必须早于** `cn` / `cn-ip`；原 `cn-services` 集合已并入 `magic-direct`（只留「上游集合未覆盖 + 实测必须直连」的 3 条：`alimama.com` / `snssdk.com` / `tanx.com`），不要往里塞国内服务的国际版与境外节点——那些直连必然超时，应交给兜底走代理。

    **这些相对顺序已由构建期校验强制（2026-10-31 起，`validate.py` 的「顺序不变量」检查）**：尾部直连块相对顺序（`cn` → `cn-ip` → `direct` → `private-ip`，早于 `MATCH`）、上面四对父子关系、云服务商集合早于 `cn`/`cn-ip`，任何一项被破坏构建直接失败。兜底（MATCH）错位仍走渲染器「自动归位 + 告警」的既有路径，不变量只盯渲染器不会替你修的三组关系。**这个检查的由来**：2026-10-31 排查发现 `games-cn` 已漂移到表尾（排在 `games` 之后，10-26 整体重排的残留），国内游戏域名被父集合抢先送进代理——已移回 `microsoft-cn` 相邻位置，并把五条硬约束写进校验防止再漂移。要调整设计顺序，先改 `validate.py` 的不变量表（并同步本文件），再动规则。

    **判断一个集合里的条目还有没有用，要按产物规则顺序模拟「首个命中」，不能只看集合之间的覆盖关系。** 集合之间的覆盖只说明「别的集合也有这条」，还要看那条规则在产物里排在第几位：排在更靠前的集合命中时，留在靠后集合里的同一条就是**死条目**（原 `cn-services` 里的 `wegame.com.cn` 就是这种——`games` 在第 7 块、`cn-services` 在第 10 块，它永远轮不到，删掉也不改路由；该集合后来并入 `magic-direct`）。判定方法：按产物 `rules:` 的顺序遍历，对每个候选域名找第一个能命中的 `RULE-SET`。

    改顺序前先读 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「规则顺序：按目标分组」。
22. **同一件事的两份清单必须合并，不然其中一份大面积失效。** 上游 `geosite/steam@cn`（19 条）与 blackmatrix7 `SteamCN`（17 条）重叠 14 条，后者 82% 的条目永远走不到、且 14 条路由方向与写规则时的意图相反。已删 `SteamCN`，把它独有的 2 条域名拆成 `DOMAIN-SUFFIX` 规则继续直连。**判断办法**：拿每个集合的条目与面板全部现有集合求交（严格区分 `DOMAIN` 精确与 `DOMAIN-SUFFIX` 后缀语义，后缀回溯要停在公共后缀之前，behavior 用面板声明值，mrs 要换同名 yaml 等价物），交集大到让规则大面积失效时，删重复的那份、把独有内容拆成小规则，别靠调顺序。
23. **`ipcidr` 行为的规则集必须加 `no-resolve`，唯一例外是 `cn-ip`。** 官方文档明确「ipcidr 类规则集支持 no-resolve 参数」：不加的话客户端遇到域名请求会先为这条规则做一次 DNS 解析再判断 IP 是否命中。判断依据是来源的 `behavior`，不是规则的 `type`——`RULE-SET` 规则的 `no_resolve` 只会对 `ipcidr` 行为真正生效。新建 `ipcidr` 来源后要同步把引用它的规则勾上 no-resolve。**例外**：`cn-ip` 不带 no-resolve（2026-10-27 起）——它排在 `MATCH` 之前，是"未列入任何集合的国内域名"的最后直连机会，带 no-resolve 会让这些域名落到 `MATCH → 🚀 默认代理`，从境外出口访问国内站点；多付一次国内 DNS 解析是值得的。
24. **规则与规则集改动后要按官方文档复核一遍。** 白名单以官方文档为准，不靠记忆：Stash <https://stash.wiki/rules/rule-types>、<https://stash.wiki/rules/rule-set>；Mihomo <https://wiki.metacubex.one/config/rules/>、<https://wiki.metacubex.one/config/rule-providers/>。要核对的项、已发现过的问题（`ipcidr` 行为漏加 `no-resolve`，现存的 `private-ip` / `telegram-ip` 都已带上；`cn-ip` 按约束 23 的例外不带）以及 Stash 独有能力（`no-track` / `pre-matching`）都写在 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「规则与规则集的规范核对」。**规则来源内部的一致性（内容有没有悬空引用、有没有规则引用它）暂时不查**——面板侧的校验向阳后面自己优化，验收时不必报告这两类问题。Stash 独有的 `no-track` / `pre-matching` **只写进 Stash 产物**（Mihomo 的规则参数只有 `no-resolve` 与 `src`；实测 Mihomo 遇到未知参数会忽略、不会加载失败，但产物里不写更清楚）；`pre-matching` 还要求目标是 `REJECT` 字面量、用策略组会直接加载失败，且只对 Stash iOS/tvOS 3.7+、macOS 4.4+ 生效，版本太旧的客户端可能加载失败。兜底规则（MATCH）不能加 `no-track`，否则客户端不记录任何连接。同一个规则集可以在互斥的引擎平台各挂一条（广告过滤就是这么分轨的：Stash iOS/tvOS/macOS 用 `REJECT` 字面量，其余平台用「🛑 广告过滤」策略组），「规则重复」判定只看适用范围有无交集。
25. **服务分流要按「这个服务到底要什么」分派，不要一律丢进默认代理。** 三类需求对应三种落法：**地区锁服务**（Pixiv / DMM / Hulu / BBC，换 IP 就打不开）→ 指向对应地区组；**账号风控服务**（Discord / Slack / Amazon / 币圈，对出口 IP 的信誉与地区一致性有校验）→ 指向固定出口的 `select` 组（🛒 跨境电商 / 🪙 加密货币，本地节点排最前），别交给 `url-test` 自动切 IP；**上游大集合吃掉了本该更细路由的域名**（`media` 里的 BBC、`disney` 里的 Hulu）→ 拆出服务专属集合并排在宽泛合集之前。判断"这个集合值不值得加"必须与面板全部现有集合求交，看净增量与路由错位，算增量的三个坑（公共后缀回溯、behavior 不能嗅探、mrs 要换 yaml 等价物）写在 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「服务细分：按用途与地区分派」。
26. **社交类分流按用途分两组：💬 即时通讯 与 👥 海外社交。** 前者是点对点聊天、群聊、通话、消息推送（Telegram / WhatsApp / Signal / Discord / LINE / Viber / KakaoTalk / Messenger / Snapchat / Element / Session / Threema / SimpleX / Wire / Zalo / Slack），后者是动态、发帖、图文流、关注、社区（Twitter / Instagram / Facebook / Reddit / Threads / Bluesky / Tumblr / Pinterest / LinkedIn / TruthSocial / VK / OK / Quora / Lemmy / Nextdoor / GETTR / Minds / MeWe / Gab / Mastodon）。**两个块在第 7 块内各自连续，通讯块必须排在社交块前面**——两块都含 LINE / Messenger / Discord 的域名，具体服务集合要排在宽泛的 `social-extra` / `social` 前面，否则走错组。geosite 的 `category-social-media-!cn`（`social`）已覆盖 Twitter / Facebook / Instagram / Threads / Tumblr / LinkedIn / TruthSocial / VK / Bluesky / Mastodon 的全部条目，**不要再为它们建单服务集合**（同约束 22 的重复清单）；只有净增量不为零的才建来源。小众服务（Threema / Session / SimpleX / Wire / Viber / Quora / Lemmy / Nextdoor / OK / GETTR / Minds / MeWe / Gab）走自维护层 `magic-chat` 与 `magic-social`，域名逐个核实过。
27. **策略组的顺序是向阳精心配置过的基线，不得擅自变更。** 多方案下逐方案核对，改其他方案不得影响默认方案。以下是仓库已存档的 **2026-11-12、构建 233** 默认方案基线（33 组，来自 `policy/snapshots/2026-11-12.json`），括号内是 `sort`：

    ```
    🚀 默认代理(0) → 🏢 自建优先(1) → 🔍 谷歌服务(3) → 🧠 人工智能(4) → 💻 开发工具(5)
    → 🎮 海外游戏(6) → 🎞️ 国际影音(7) → 🎵 TikTok(8) → 💬 即时通讯(9) → 👥 海外社交(10)
    → 🍎 苹果服务(11) → Ⓜ️ 微软服务(12) → 🛒 跨境电商(13) → 🪙 加密货币(14) → ⚡️ 自动测速(15)
    → 🇯🇵日本(16) → 🇺🇸美国(17) → 🇹🇼台湾(18) → 🇰🇷韩国(19) → 🇸🇬 新加坡(20) → 🇭🇰香港(21)
    → 🌍欧洲(22) → 🇯🇵 日本机房(23) → 🇺🇸 美国机房(24) → 🇯🇵 日本自动(25) → 🇺🇸 美国自动(26)
    → 🇹🇼 台湾自动(27) → 🇰🇷 韩国自动(28) → 🇭🇰 香港自动(29) → 🌍 欧洲自动(30)
    → 🇸🇬 新加坡自动(31) → 🏠 路由回家(32) → 🇺🇸 美国NTT落地(33)
    ```

    > 这是历史存档，不代表实时线上状态；旧版 2026-10-26 的 32 组清单已过时，不能照着恢复。
    > `sort=2` 的空缺合法，排序值要求唯一、不要求连续，不要为填空缺重编号。
    > `🇸🇬 新加坡` 与 `🇸🇬 新加坡自动` 仍是外层可见 / 内层隐藏的一对。
    > 曾短暂存在的 `🏠 私有网络` 组已删除；`private` / `private-ip` 直接指向 `DIRECT`。

    **任何重构（菜单重排、页面合并、构建流程改动、数据层切换）都不得改动用户现有的先后顺序**，包括不得擅自重排 `sort` 值。新建组只能放到指定位置；删除组时其余组的相对顺序不变。改动前先拉线上各方案当前顺序作为本次基线，改动后逐项比对确认一致。**要改顺序必须向阳明确要求。**

28. **各列表的 `sort` 值必须全局唯一，否则拖拽排序会静默失效。** `sort` 是全局排序键，同值的两组相对顺序退回由 `id` 决定，界面上拖了没反应。`reorder_subset`（`server/app/db.py`）现在会在重排前检测重复并整表按当前顺序重编号消歧，相对顺序不变；子集重排按"连续块"语义放回原位置区间，区间内其余行整体顺延。**因此重排后要重新核对上条的基线**——`sort` 数值可能被消歧改掉（相对顺序不变）。消歧只在存在重复时触发，正常路径不动任何数值。

    组与规则的排序请求只能包含同一 `variant_id`，混入其他方案的 ID 会被拒绝；
    新方案使用独立的排序段，见约束 42。不要把方案内排序请求拼成整表重排。

29. **后台页面结构已重排（2026-10-25；2026-11-17 分组化并新增网络体检）。** 侧边栏 13 项分四组显示（纯显示层分组，路由与 API 不变）：**运营**（系统概览、网络体检）→ **分流配置**（策略组 → 分流策略 → 节点来源 → 规则来源 → 基础配置）→ **分发与设备**（设备管理 → 构建发布）→ **运维**（拓展模块 → 自主维护 → 审计日志 → 系统设置）。历史备注：分流规则紧跟策略组——规则的目标就是策略组，改规则时来回切这两页最频繁。

    - 「引擎平台」不再是独立页面，是「基础配置」的第一个 tab（`?tab=targets`）；「产物配置」是第二个 tab（`?tab=artifact`）。
    - 「自动运行配置」不再是独立页面，是「构建发布」的第二个 tab（`?tab=auto`）；页面标题行的「立即发布」是两个 tab 共享的页面级操作。
    - 旧路径 `/admin/targets`、`/admin/automation` 会重定向到新位置，不产生死链。
    - 改名只动显示层：路由路径、API 路径、数据库表名与列名、审计的 `object_type` 一律不动；审计的 `action` 文案用新称，**历史记录保持原文案**。

30. **「一键发布」与「抓取并发布」是两个动作。** 一键发布（`POST /api/v1/builds/{id}/publish-both`）发布**已有的这个构建**，内部是同一事务里先置测试再置生产，发布历史只记一条；「抓取并发布」（2026-11-20 更名，曾叫「立即发布/运行自动任务」）触发一整轮自动任务（抓取 → 测速 → 创建**新**构建 → 按自动任务设置发布，默认生产），点击后按当前设置弹确认框。两者语义相近，界面上必须让用户分得清。

31. **DNS 段固化在「引擎默认配置」（源码基线 `server/app/services/base_config.py`），其他层一律不得写 `dns:` 键。** 2026-10-27 定稿方案（旧方案"默认境外 DoH 走代理"把所有未命中策略域名的解析绑在代理可用性上，代理一抖国内网站成片打不开，已废弃）：默认 `nameserver` 为国内 DoH 裸 IP 直连双运营商并发（`120.53.53.53` 腾讯 doh.pub + `223.5.5.5` 阿里）；海外敏感域（Fake-IP 排除清单里的海外域：微软全家 + `lens.l.google.com`）与直连的海外集合（`rule-set:mirror-accelerate` / `pt` / `trackers`）在 `nameserver-policy` 指到境外 DoH（`1.1.1.1` / `8.8.8.8`，经代理出口）。核心依据：Fake-IP 下走代理的连接由节点远程解析，本地答案无关紧要；本地答案只对「Fake-IP 排除清单的海外域」与「DIRECT 连接」有意义。alidns（223.5.5.5）对海外域有污染，但本设计下默认解析器的海外答案永远不会被使用，放它只为运营商冗余。**国内域名不需要任何显式 `nameserver-policy`**——默认就是国内 DoH，显式写反而退化成单服务器。

    - **维护位置与禁改范围**：DNS 段（nameserver / nameserver-policy / proxy-server-nameserver / follow-rule / respect-rules / ipv6 等）只改源码基线；**引擎平台配置、平台扩展（targets.extra_yaml）、设备独立配置、拓展模块都不许写 `dns:` 键**——平台扩展与设备层是追加合并，写了就会悄悄盖过基线（2026-10-27 就从平台扩展和 4 个设备层里清掉过残留的 `vpn.jiek.top` 策略）。家用 Fake-IP 清单仍在平台层用 `_fake_ip_filter` 伪键维护（伪键不是 dns 键）。
    - **保存时校验差异，不能拒绝继承值（2026-11-13 修复）**：`PUT /api/v1/base-config` 与 `POST /api/v1/base-config/apply` 提交的是编辑后的完整生效值，可能含上层继承的 `dns`。先以 `allow_dns=True` 校验生效值，再相对 `_baseline()` 计算 `overlay`，最后按当前层校验 `overlay` 的 `allow_dns`；平台 / 设备层新增或改写 DNS 仍返回 400。不能直接对完整生效值用 `allow_dns=False`，否则连修改 `ipv6` 也保存不了。解析、差异计算与校验的 `ValueError` 都要转为 HTTP 400。回归见 `server/tests/test_builtin_config.py`。
    - **两个清单必须同步**：源码 `_OVERSEAS_SENSITIVE` 与平台层 `_fake_ip_filter` 里的海外域一一对应——一边加域另一边也要加，否则要么答案不干净、要么白走代理。
    - **三个集合不可删**：`mirror-accelerate` / `pt` / `trackers` 被 DNS 策略的 `rule-set:` 键引用，删除或改名会让策略悬空；要动先改源码 `_OVERSEAS_DIRECT_SETS`。
    - **不配 `fallback` / `fallback-filter`**（配了默认启用 geoip CN 过滤，多一个 geo 依赖且没有污染值要筛）；**不配 `default-nameserver`**（所有服务器都是裸 IP，它永远不会被查询）；**不配 `direct-nameserver`**。
    - **DNS 服务器一律写裸 IP**；`nameserver-policy` 的 `rule-set:<name>` 逐个集合写成独立键（逗号合并是 Stash 专有扩展，Mihomo 不认）。
    - **出口规则两组缺一不可**：`IP-CIDR,1.1.1.1/32` / `1.0.0.1/32` / `8.8.8.8/32` / `8.8.4.4/32` → `🚀 默认代理`（境外 DoH），`IP-CIDR,120.53.53.53/32` / `223.5.5.5/32` → `DIRECT`（国内 DoH；Stash follow-rule / Mihomo respect-rules 下缺了会被兜底送进代理）。另有 `RULE-SET,cn-ip,DIRECT` **不带 no-resolve**（约束 23 的例外），作为未列入集合的国内域名的最后直连机会。
    - 拓展模块「国内域名走国内 DNS」已删除（2026-10-27）：默认解析器已是国内 DoH，且该模块的 `geosite:` 合并键 Mihomo 不认，双重无效。不要再建同类模块。
    - 改动细节、逐键必要性与验证方法见 [配置文档](docs/配置文档.md#dns-段国内直连为默认海外敏感域走代理2026-10-27-重构)。


32. **自主维护页的 Git 操作要串行，界面要有处理中反馈。** `repo_manager.operation(op)` 是所有 Git 操作的互斥入口：克隆、拉取、提交、推送都在里面，同一时刻只允许一个；抢不到锁的请求返回 **409**（不是 400），消息是「上一操作还在进行中（<操作名>），等它结束再试」。`/api/v1/deps/status` 带 `busy` 与 `busy_op` 两个字段，前端据此把「保存并提交」「立即同步」置灰并显示进行中字样，操作结束后自动恢复。**`repo_manager` 里那个 `_lock` 定义了却曾经从未被使用**——并发跑 git 会撞 `index.lock`，新加 Git 操作必须走 `operation()`，不要绕过。

33. **任何可能命中 Fake-IP 段或触发解析的 IP 类规则，一律排在全部域名类规则之后（2026-10-28 定稿，构建 178→180）。** 根因：Stash 的连接竞速会在规则评估前后预解析域名，内部解析返回的是 Fake-IP（198.18.0.0/16），而 MetaCubeX `private`/lan 库包含 198.18.0.0/15——`RULE-SET,private-ip,DIRECT` 原先排在域名规则之前，一旦预解析先于规则匹配完成，域名连接就带着「已就绪」的 Fake-IP 被误判成私网直连，随后按真实（被墙）IP 直连拨号超时；「最快 IP 缓存」还会把 Fake-IP 记成该域名的优胜地址，导致该域名持续黑洞直到清缓存/重启。线上表现为国内外站点间歇性卡死十几秒、ZCode 等应用一直转圈、关代理立刻恢复、`dns flush` 短暂恢复、同一域名时好时坏。修复历经两次：构建 178 先移到 `RULE-SET,cn` 与 `RULE-SET,cn-ip` 之间，构建 180 定稿为 **`cn` → `cn-ip` → `direct` → `private-ip` → `MATCH`**（sort 119-122）——第一次的位置仍在域名集合 `direct` 之前，`direct` 里 267 个直连域名的连接同样可能被 Fake-IP 劫持，构建校验（见下）把这一点拦了下来。最终态：域名连接永远先按域名路由，Fake-IP 不可能再被 IP 规则截胡。

    - **不变量**：新增 IP 类规则（`IP-CIDR*` / ipcidr 行为的 `RULE-SET`）一律放在 `private-ip` 相邻区间，不得插到域名规则前面。排在最前的几条 DNS 出口 `IP-CIDR`（1.1.1.1/8.8.8.8→代理、120.53.53.53/223.5.5.5→直连）是唯一例外——它们全是带 no-resolve 的精确 /32，Fake-IP 不可能命中。
    - **构建校验已内置**：`validate_policy` 会在构建期拦截「可能命中 Fake-IP 段的 IP 规则排在域名规则之前」（字面 CIDR 按与 198.18.0.0/15 的重叠精确判断；ipcidr 规则集按 `private`/`lan` 名单判断）。修复这类报错时改规则顺序，不要绕过校验。
    - **Mihomo 不受影响**（Fake-IP 在 TUN 入口即回映射为域名，规则评估看不到 Fake-IP），但产物共用同一规则表，调整顺序对两引擎均无副作用。
    - **基础配置分层（2026-10-28 固化，构建 180）**：共有键（ipv6 / profile / sniffer 端口 / mihomo global-client-fingerprint / `_direct_domains` / `_fake_ip_filter`）全部上收引擎默认配置（源码基线 `base_config.py`），8 个引擎平台层全部清空（仅 Mihomo-Android 保留 `find-process-mode: off`），设备层只剩 MTProto / hosts / tun 个性化；**API 已在平台/设备层拒绝 `dns:` 键**（仅引擎默认层可写，`validate_doc(allow_dns)`），Fake-IP 清单用 `_fake_ip_filter` 伪键、设备层追加。`cascade` 同时修复了顶层级列表键在设备层被静默替换的 bug（现按文档语义追加）。
    - **LVSP 的 tun 段放在设备层（2026-10-28，构建 181）**：Mihomo-macOS 目标的平台扩展**故意为空**——tun/dns-hijack/Tailscale 路由排除是 Lvsp-MacBook-Mihomo 一台设备的个性化，已下沉到该设备的「设备独立配置」。不要「整理」回平台扩展；若将来出现第二台 LVSP mihomo-macOS 设备，再按先个性后共性的原则提升。
    - **引擎基线官方对齐（2026-10-28，构建 182，官方示例已刷新进 official-example/）**：`sniffing` 是 mihomo 官方废弃键（「若 sniffer.sniff 配置则此项无效」），只存在于 Stash 基线，不要加回 mihomo；mihomo 基线带官方示例同款 `geox-url` jsdelivr 镜像（geo-auto-update 国内直连 GitHub 会失败）；mihomo 的 `fake-ip-filter` 是 blacklist 模式，**不支持 GEOSITE 语法**（wiki：GEOSITE/RuleSet 仅 fake-ip-filter-mode: rule 可用），所以 mihomo 清单没有 `geosite:private` 而 Stash 有——两边清单不要强行统一。
    - **OpenClash-Mihomo 目标（mihomo/linux，2026-11-13 构建 243 适配记录）**：面向 OpenWrt OpenClash 的 Mihomo 内核，入站端口、运行模式（TUN/TPROXY）、DNS、嗅探、external-controller 由 OpenClash LuCI 覆写，**平台扩展保持为空，不要往里写 tun 或端口**；平台层差异为 `allow-lan: true`、`bind-address: "*"`、`find-process-mode: off`、`ipv6: false`，最后一项与路由器 `ipv6_enable=0` 对齐。构建 243 已有设备 `Astral-PassWall-Mihomo` 使用「自建美日」方案，路由器订阅登记为 `MagicPanel-自建美日`；不再是无设备的预留目标。内核实际加载配置还要看 LuCI 覆写结果，不能仅凭面板产物判断 DNS、端口和运行模式。

    **文档也必须改在开发工作区**；NAS 部署副本的手工改动会被下次 `rsync --delete` 覆盖。
    纯文档更新的验证范围见「改完要做的事」。

34. **QUIC 分轨：直连放行，代理链路强制回退 TCP（2026-10-31 修订 10-28 决策）。** 10-28 的实测结论仍然成立：Fake-IP 修复后 UDP/QUIC 直连链路畅通，语音/游戏/P2P 必须放行 UDP，所以**不做全局禁 QUIC**。但「任何应用都不出现访问异常」的目标下，QUIC 经 VPN 隧道（尤其手机蜂窝网络）的转发质量无法逐设备保证，而官方 FAQ（stash.wiki/faq/effective-stash）明确建议对走代理的流量禁 QUIC。定稿方案是一条逻辑规则：`AND,((NETWORK,udp),(DST-PORT,443)),REJECT`，排在尾部直连块（`private-ip`）之后、`MATCH` 之前——**只拦“本来就要走代理”的 QUIC**，国内直连流量早在 `cn`/`cn-ip` 命中 DIRECT，QUIC 完全不受影响；未命中任何规则的 QUIC 被拒后应用自动回退 TCP/2，兼容性优先于 HTTP/3 首包收益。两引擎语法一致（Stash 与 Mihomo 都支持 AND 逻辑规则），一行配置全覆盖，不需要逐 App 覆写。带 `no-track`（Stash 侧）避免 REJECT 刷屏连接列表；**不要加 `pre-matching`**（旧版本客户端可能加载失败，约束 24）。若未来要把某类代理流量恢复 QUIC，改这条规则而不是加客户端覆写。

35. **停用 ≠ 删除：feed 必须继续下发已有内容的资源；删除或改名被当前生产产物引用时一律拦住（2026-11-04 定案）。** 根因：产物不可变、只移动指针，客户端手上的配置里写着 `/res/rule/<name>`、`/res/provider/<name>` 这些下发地址，它会**持续**来取——哪怕面板里已经把对应来源停用或删除。feed 一旦回 404，客户端（实测 Stash 4.4.0）会把这条资源留在运行时会话里每 60 秒重试一次，日志刷 `runtime::session: artifact refresh failed ... HTTP 404`，并把整个订阅更新判为失败：配置**下载得到**（服务端 `last_pull_at` 一直在涨）却永远**不生效**（客户端 `lastCompletedCheck` 停在原地）。线上实证：2026-10-31 停用规则来源 `AWAvenue-Ads` 后，两台 macOS 设备每分钟各刷一次 404；Mac mini 的订阅自 2026-11-03 01:39 起再也更新不进来，界面上的「更新配置」必然报错。定稿两条：**（1）** `routers/feed.py` 的 `rule_resource` / `provider_resource` 只要内容还在就照发——`enabled` 只决定是否进入**新**构建，不再决定是否下发（停用是业务语义，删除才是资源消失）；**（2）** 删除或改名一个**当前生产产物仍在引用**的规则来源 / 节点来源，返回 409 + 引用明细（复用既有 code `rule_provider_in_use` / `source_in_use`，前端自动弹二次确认，`force=1` 才放行），提示语是「请先发布新版本再删除/改名」。判断依据是 `services/refs.py` 的 `release_resource_refs(conn, "rule"|"provider", name)`——扫当前生产构建目录下的产物，看是否还写着这个下发地址。停用（`enabled=0`）不受此限制。

36. **「配置本体」与「子资源」的拉取时间必须分开记，设备配置陈旧要在界面上看得见（2026-11-04 定案）。** `devices.last_pull_at` 记录的是**任意资源**（配置本体 + 规则集 + 节点来源）的拉取，**不能**拿它判断设备有没有拿到新配置——规则集本身就按小时级刷新，界面上的「最近下载」与概览的「24 小时内拉取过」因此永远是绿的。线上实证：Mac mini 的配置本体自 2026-11-03 01:39 起就没再生效（客户端 `lastCompletedCheck` 停在原地、界面报「更新配置」失败），而面板显示它「3 小时前刚下载过」——**故障完全隐形**。定稿：`devices.last_config_at` 只在 `config.yaml` 下发时更新（`routers/feed.py` 的 `device_config`）；`routers/targets_devices.py` 的 `config_age_hours()` / `config_stale()` 按 `profile-update-interval` 的 3 倍（不足 6 小时按 6 小时算）判定陈旧，设备列表标「未更新」，概览统计 `counts.devices_stale`。**HTTP 200 只代表文件取回，不代表配置加载、VPN 启动或规则生效**（概览页原有提示保留）——判断"设备是否生效"只看配置本体的时间戳，不要看子资源。新增字段走 `db.py` 的 `_migrate_device_config_pull` 一次性迁移并回填。

37. **节点来源支持自定义请求头与文件来源；请求头的值是凭据（2026-11-04 定案）。** 机场订阅常常要带特定 Cookie / User-Agent 才给内容（风控页、加密订阅），来源因此要能带自定义请求头：
  * `sources.headers_enc` —— 请求头列表（名字 + 值）**密文存储**，与订阅地址同一套处理；列表接口只回显名字（`headers: [{name}]`），原文只在「查看」接口（`POST /api/v1/sources/{id}/reveal`，记审计）里返回；
  * 编辑时**值不回显**，所以请求头值支持 `null` = 保持原值（`_merge_headers`）；新建的请求头必须给值，否则报「必须填写值」；
  * 请求头名字必须是 RFC 7230 token、值里不许换行（头部注入），条数上限 32；
  * **`Accept-Encoding` 一律丢弃**：httpx 只声明自己能解码的编码（镜像里没有 brotli），用户自定义的 `br` 会让响应解不开；
  * 文件来源（`source_kind='file'`）：没有在线地址，内容由上传解析成快照，照常参与分组、测速与下发；`auto_fetch=0`，定时抓取跳过，「一键抓取」明确报「文件来源没有在线地址，请重新上传订阅文件」。上传走 `POST /api/v1/sources/import-file`（内容 base64 传输，**不引入 multipart 依赖**），替换走 `PUT /api/v1/sources/{id}/file`；
  * 内容解析认两种格式：Clash YAML（`proxies:`）与 base64 的 URI 列表（`ss://` / `trojan://` / `vmess://` / `vless://`）。认不出来时给出**可照着做的提示**，不要只说「格式错误」——机场的**加密订阅**（内容是密文、密钥不在订阅地址里）面板解不开，提示里要写明「请在客户端导出成 Clash YAML 后再上传」；
  * 前端「从 curl 命令导入」：粘一条 curl 就能填好地址与请求头（Host 由地址决定，忽略），解析在**前端**做，填进表单让用户确认后再保存。

38. **面板自己的域名必须留在 Fake-IP 之外（2026-11-04）。** 客户端（Stash 增强模式）拿面板域名的真实 IP 去更新订阅：Fake-IP 命中与否由服务端 DNS 决定，客户端本地缓存过期就拿不到。`substitute_feed` 在下发时把 `+.<面板域名>` **追加**进 `dns.fake-ip-filter`（追加而不是替换：用户自己维护的排除清单原样保留）。面板域名同时由 `_panel_direct_rule` 置顶成 `DOMAIN-SUFFIX,<域名>,DIRECT`——VPN 运行中节点失效也不影响订阅更新。**但这两条都救不了家宽公网 IP 变动**：PPPoE 重连后公网 IP 会变，客户端 DNS 缓存里的旧 IP 让订阅取不到（2026-11-04 实测：mini 解析 magichub.top 拿到旧 IP，连接 4 毫秒即被拒；规则与 Fake-IP 都没错）。根治要在**路由器上做分流 DNS**（magichub.top → NAS 内网地址），面板侧代替不了——家宽公网 IP 只能由路由器知道。

39. **一个节点都没有的来源不能卡住自动构建发布（2026-11-04 定案）。** 自动构建发布的门禁要求：启用「只分发可用节点」的来源必须有新鲜且可用的测速结果（关掉自动测速或测速间隔为 0 的来源除外）。但**还没抓到内容、节点数为 0 的来源同样不参与门禁**——它进不了产物，不会违反「只分发可用节点」的承诺；而它永远等不到测速结果，留着就把整条发布链路静默卡死。线上实证：2026-11-04 新建一个抓取失败的来源后，「立即发布」与定时发布都推不出去新版本，面板上看不出任何异常。判据放在 `scheduler._publish_tests_ready()`：按 `node_count>0` 过滤，并把这类来源单列成「没有节点的来源不参与门禁」（与「未开启测速的来源不参与门禁」并列，提示语要分清两者）。有节点但测不出结果的来源仍然卡门禁——那是门禁的本意。

40. **只改渲染器代码要手动构建一次才会进产物（2026-11-04 记录）。** 自动构建的指纹是「策略快照」的哈希（`builds.current_policy` → `collect_snapshot` 的 JSON），覆盖策略与**基础配置三层的内容**，但**不覆盖渲染器代码**。所以只改 `compiler/render.py` 或 `services/base_config.py` 里的默认取值、而策略本身没动时，定时构建会判定「策略未变化，跳过」，新的渲染逻辑不会进产物，设备继续用旧配置。改完渲染器要手动「创建构建 → 发布至测试 → 发布至生产」一次。基础配置层的内容改动会被指纹覆盖，会自动重建，不需要手动干预。

41. **门户「看配置源码」是预览，不是拉取（2026-11-10）。** 设备卡片标题可点，弹层里用 YAML 语法高亮展示该设备的配置源码。走的是**同一个 feed 地址加 `?preview=1`**（`/feed/{token}/config.yaml?preview=1`），内容与客户端下发的完全一致，但三件事必须不同：**不记拉取**（人在看不是客户端在更新，污染了 `last_config_at` / `pull_count` 会让「配置时效」失真——见约束 36）、**不加 `#SUBSCRIBED`**（那是给客户端的更新提示行，不是配置内容）、**`Content-Disposition` 用 `inline`**（`attachment` 会让「新标签打开原文」变成下载而不是显示）。预览响应还带 `Cache-Control: no-store` 且不做 304 协商——缓存的 ETag 会让第二次预览拿到 304 空响应。

    高亮用 `src/yamlHighlight.js`（自研、零依赖）而**不是** CodeMirror：门户是公开页，CodeMirror 是编辑器（`components/CodeEditor.vue` 自己也写明「只读文件不渲染本组件」）；产物动辄四千多行，自研逐行词法扫描 7ms 出结果。**YAML 的纯量按空格分词是错的**——`name: 🇭🇰 香港 06 [Home]` 是一个字符串不是四个 token，所以只有单个词才按类型（布尔/数字/URL/IP）着色，带空格的整段当字符串，否则会把节点名里的 `06` 染成数字，看着像端口号。产物里的键名、URL、节点名都是用户可写内容，**上 `v-html` 前必须转义**。

42. **多套分流方案（variants）：每个方案是一套完整、独立的策略组 + 分流规则副本（2026-11-13 定稿）。** 设计与实现细节见 [方案设计](docs/reference/方案设计-多套分流方案.md)。要点：

    - **数据模型**：`variants` 表（`默认` 方案 id=0，`is_system` 保护，禁删禁改名禁停用）；`proxy_groups` / `rules` 挂 `variant_id`，组名约束为 `UNIQUE(variant_id, name)`——不同方案允许同名组，同一方案内唯一。新方案使用 `config.VARIANT_SORT_STRIDE=10000` 的排序偏移，组 / 规则排序请求不得跨方案，改动后仍须核对默认方案的顺序与 sort（约束 27/28）。
    - **引用全部方案内解析**：规则目标、组成员引用、改名重映射、删除解绑、`validate_policy`（逐方案返回 `{方案id: (errors, warnings)}`，方案之间互不阻塞）都只看同一 `variant_id` 的行。**`refs.detach_group` 必须传 `variant_id`**——2026-11-13 线上事故：删「自建美日」的港台组时把默认方案里指向同名组的 8 条规则一并删了（有回归测试 `test_deleting_group_in_one_variant_keeps_other_variants_rules`）。
    - **构建矩阵**：`create_build` 对每个启用方案 × 每个引擎平台渲染一份产物，并为有专属策略的设备生成设备产物——默认方案沿用 `{target}.yaml` / `{device}.yaml` 命名，方案 V 是 `{target}@V.yaml` / `{device}@V.yaml`。产物文件名冲突在构建期报错。`results` 键为不带 `.yaml` 的产物名，非默认方案的 value 带 `"variant": V`（方案名）。
    - **来源/集合按引用过滤**：渲染时展开各组的 `use`（含 `["*"]`）取并集，顶层 `proxies` 只展开被引用的 inline 来源，`proxy-providers` 只写被引用的 provider 来源；`rule-providers` 只写「本方案规则引用 ∪ DNS `rule-set:` 引用」的集合。默认方案所有组 `use=["*"]` → 行为不变；「自建美日」无来源引用 → 产物无机场节点、无 providers 段。「只分发可用节点」等既有开关不受影响。
    - **分发**：`GET /feed/{token}/config.yaml?variant=<方案名>` 取方案产物（设备专属优先，缺省回退目标产物）；不带参数 = 默认方案 = 历史路径，老订阅零影响。`?preview=1` 与 `?variant=` 可组合。
    - **守卫**：删除/改名被当前生产**或测试**产物引用的方案 → 409 `variant_in_use`（复用约束 35 语义）；停用只是不进新构建，已有产物照常下发。
    - **默认方案展示在前**：方案管理里系统方案的上移 / 下移按钮禁用（`src/components/VariantBar.vue`）；调整其他方案时同样不能把默认方案挤到后面。此顺序属于 `variants.sort`，与各方案内部的组 / 规则 `sort` 分开维护。
    - **「自建美日」方案（2026-11-13 精简终态，构建 240）**：方案数据共 **6 组 / 114 规则**；一般设备产物只有 **5 组（3 可见 + 2 隐藏）**：`🚀 默认代理`（select，成员按 `🇯🇵日本` → `🇺🇸美国`）、`🇯🇵日本`、`🇺🇸美国`，以及两个隐藏 url-test `🇯🇵 日本自动` / `🇺🇸 美国自动`。`🏠 路由回家` 仅在 LVSP 设备范围内保留。节点池只含日美自建节点（日本机房、AWS日本机房、美国机房、美国NTT 01–10），不含机场来源与香港节点；不要恢复精简前的 23 组或重新加回各服务组。
    - **精简方案的分流目标**：AI / 谷歌 / 开发 / 即时通讯 / 海外社交 / 微软 / 跨境电商 / 加密货币 → `🇺🇸美国`；TikTok / 影音 / 游戏等 → `🇯🇵日本`；`apple` → `DIRECT`，国内直连规则保留；DNS 出口、云服务商、代理兜底集合与 MATCH 保留原有目标。这里是独立方案的既定设计，不要套用默认方案的服务组结构，也不要连带改默认方案。精编脚本 `scripts/configure_selfbuilt_variant.py` 可重复执行，运行前仍须导出快照并检查现状。
    - **门户操作全部跟随方案**：设备卡片的复制 / **下载** / 导入 / 二维码 / 预览联动；下载文件名为 `文件名.yaml` 或 `文件名@方案名.yaml`（文件名即设备的唯一标识）。预览沿用服务端返回的**相对路径**并追加方案参数（已有 `?preview=1` 时用 `&variant=`），不要改成公网绝对地址，否则内网访问会遇到跨源问题。预览纪律见约束 41。

43. **「指到家里」的域名必须用 system DNS 解析（2026-11-13 定案，构建 239）。** `magichub.top` / `homehub.stream` 的服务器就在家里：路由器分流 DNS 给 **NAS 内网地址**（10.0.1.2），公网 DoH 给**家宽公网 IP**。代理接管 DNS 后用国内 DoH 解析出公网 IP，局域网设备访问自己的公网 IP 会被 **NAT 回环**挡住——线上实证「homehub 相关域名内网打不开、关代理立刻恢复」。修复：这两个域在引擎默认配置 `nameserver-policy` 固化为 `system`（内网直达 NAS，外网正常回家），伪键 `_system_dns_domains` 供界面追加（渲染时与基线合并）。判断标准：系统 DNS 与公网 DoH 答案不一致且系统侧是内网地址 → 该域必须进清单。与 `_direct_domains` / `_fake_ip_filter` 是三件套，加域要三处一起改。

44. **约束 23 的 cn-ip 例外有构建期校验**（2026-11-13 起）：`RULE-SET,cn-ip` 带 `no-resolve` 直接构建失败（validate.py 强制）。2026-11-13 实证违反过：cn-ip 被 no-resolve 后未收录国内域名全部落进 `MATCH → 🚀 默认代理`，大量大陆服务异常。修复这类报错时改规则，不要绕过校验。

## 改完要做的事

先按开头的改动类型表确定范围。**纯文档更新**核对实现、日期、链接、命令示例，
运行 `git diff --check` 与凭据扫描；涉及文档站生成逻辑时再验证文档站构建。
检查通过后，按改动类型提交、推送和部署。

以下是 **Bash** 示例，从仓库根目录执行：

```bash
# 1) 本地自检
(cd server && ../.venv/bin/python -m pytest tests -q)   # 后端测试，结束后仍在仓库根目录
npm run build                                           # 前端构建（产物进 server/app/static）
.venv/bin/python scripts/check_secrets.py               # 凭据扫描（有人把令牌贴进代码会在这里被拦）
git diff --check

# 2) 在本地提交并推送到 GitHub main
# 3) 发布到 NAS：同步提交 → 重建容器 → 核对版本、健康状态、数据库和域名
bash scripts/deploy.sh                                  # 全量（含后端测试）
bash scripts/deploy.sh --fast                           # 已跑完当前提交的后端测试时可用
# NAS 走路由器 OpenClash 透明代理，构建拉包无需额外代理；
# 仅在异常时用 DEPLOY_PROXY=<可用的内网代理> 显式指定。
```

Windows PowerShell 的虚拟环境路径为 `.venv\Scripts\python.exe`；后端测试先
`Push-Location server`，用 `..\.venv\Scripts\python.exe -m pytest tests -q`，
结束后 `Pop-Location`。从根目录用 `.\.venv\Scripts\python.exe scripts/check_secrets.py`
扫描凭据；虚拟环境尚未创建时，纯文档检查可直接用可用的 `python`。
`deploy.sh` 依赖 Bash、rsync、SSH 及脚本指定的 `.venv/bin/python`，
不能只换成 PowerShell 命令直接运行；先核对执行环境与依赖。

**3）影响产物的改动：创建构建 → 发布测试 → 验证 → 发布生产。**
优先走已有 API（带登录会话与 CSRF，具体请求见[配置文档](docs/配置文档.md#改完怎么发布)）：

- `POST /api/v1/builds` 创建构建，检查所有方案与目标的 `results`。
- `POST /api/v1/builds/{id}/publish-to-test` 发布测试，实际验证受影响的设备与方案。
- `POST /api/v1/builds/{id}/publish-to-prod` 发布生产，再核对生产产物。

渲染器改动也必须执行这一步（约束 40）。直接调用内部发布服务时，状态切换必须放在
`db.tx(immediate=True)` 中串行执行，避免并发产生同一环境的多条生效记录。

**4）客户端拉取并核对。** 路由器在 OpenClash 的订阅管理里找到对应的
`MagicPanel-自建美日` 记录，核对设备与方案后触发更新，更新时间以当前设置为准。
不要假设 `@config_subscribe[0]` 就是目标订阅，也不要把下载内容直接覆盖进猜测的配置路径。

**部署后必须自己验一遍**，不要只看脚本输出：

```bash
ssh archon@10.0.1.2 'docker inspect magicpanel --format "{{.State.Health.Status}}"'
```

再使用已配置并审定的非 Google 健康端点核对通用网络，避免把基础连通等同 Google 能力。
Google 专项按已授权的美国、新加坡、日本候选分别检查，保留视角和业务范围。

策略类改动还要在路由器上确认**实际加载的配置路径**，检查修改的规则与最终出口；
面板产物、订阅下载文件与 OpenClash 覆写后的运行配置可能不同，不能混为一份。

配置类改动要**重新构建发布**才生效（只有设备独立配置例外，分发时实时叠加）。
部署脚本里的「数据自检」会拦下引用不存在的平台/组/节点——它不过就说明数据层有问题，按提示修完再发布。

## 客户端侧核对

若在已安装并运行 Stash CLI 的 Mac 上核对，可直接查询**正在运行的核心**。
以下为历史 Stash 4.4.0 环境的命令示例；Windows 工作区不能假定本机有 Stash，
Mac mini 也已不再承担全屋代理，先确认要检查的是哪台客户端与哪个方案：

```sh
stash status                              # 版本 / 模式 / 端口 / 吞吐
stash rule ls --limit 0                   # 核心里生效的完整规则表（确认客户端是否拉到新订阅）
stash rule match www.v2ex.com            # 某目标命中哪条规则、出口链、解析到的 IP
stash proxy ls "🇯🇵日本"                  # 某个组内的节点与当前选择
stash provider ls                         # rule/proxy/script provider 的条目数与更新时间
```

`stash rule match` 走的是与真实流量相同的匹配过程（`--process` / `--user-agent` / `--network` 可补齐只有真实流量才带的属性）。它**不能**重新拉取配置本身——配置更新仍要在 Stash App 里点「更新订阅」，`provider update` 只刷远程规则集。

## 官方文档

改配置键之前先在线核对官方文档，别凭记忆写：

```sh
python3 scripts/docs_lookup.py search <关键词> --product stash   # 或 mihomo
python3 scripts/docs_lookup.py read <官方页面 URL>
```

流程与要求见 [官方文档查阅流程](docs/reference/Official-Docs-Workflow.md)。
