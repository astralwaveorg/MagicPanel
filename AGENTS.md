# AGENTS.md

改动这份代码前，先读这三份文档：

| 要做的事 | 看哪份 |
| --- | --- |
| 改界面、改后端逻辑 | [开发文档](docs/开发文档.md) |
| 改配置（规则、策略组、引擎平台、设备独立配置、拓展模块） | [配置文档](docs/配置文档.md) |
| 回答"这个页面怎么用" | [使用文档](docs/使用文档.md) |
| 改规则集、决定直连还是代理、走哪个策略组 | [规则集与分流设计](docs/reference/规则集与分流设计.md) |
| 查内网地址、代理端口、哪台机器在跑什么 | [环境与地址速查](docs/reference/环境与地址.md) |

**第一次接手本项目**（新 Agent、换机器、隔了很久再来）：先读
[Agent 交接提示词](docs/reference/Agent-交接提示词.md)，里面写清了架构、硬性约束、
改配置的方式和发布流程，再动手。

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
12. **兜底规则是 `MATCH → 默认代理`，不是直连。** 面板采用"先分流、未列出的全部走代理"：漏配一条规则只会让线路不最优，不会让服务打不开。改兜底方向前先想清楚影响面。
13. **地区维度只保留两类组**：各地区单独命名的组 + 机房组（🇺🇸 美国机房 / 🇯🇵 日本机房）。机房组只放本地机房节点，供"重点标注"用；不要按"散节点"另开同地区组。每个地区是**两层**：内层 `XX自动`（隐藏 `url-test`，自动测速）+ 外层 `XX`（可见 `select`，规则只指向它）。命名规范：内层带"自动"后缀且有空格（`🇭🇰 香港自动`），外层无空格（`🇭🇰香港`）。
14. **规则目标必须是前台可见的策略组。** 客户端前台只显示可见组，指向隐藏组等于"分流了但用户选不了节点"。做法是可见 `select` 包住隐藏 `url-test`：规则指向可见组，可见组成员是隐藏自动组 + 地区正则过滤出的节点。产物里不允许出现任何指向 `hidden: true` 组的规则。
15. **引擎平台配置里的 `_direct_domains` 会置顶成直连规则**，排在所有用户规则之前。域名一旦进了这份列表，用户集合里针对它（或它的子域）的条目就是死规则——用户规则改不动它。要让某个子域走别的线路，得先把主域名从 `_direct_domains` 里摘掉，再确认 `self-hosted` 之类的集合能兜住其余子域。
16. **「引擎默认配置」层参与渲染，改它对产物生效。** 产物基线 = 源码内置默认值 `base_config.py` 的 `default_doc(engine)`，叠加用户在「引擎默认配置」层的覆盖（记录在 `(engine, "", 0)`）。渲染层必须复用 `base_config_service.scope_layers()`，不要自己再取一遍源码常量——否则界面显示的生效值与产物内容会不一致（曾出现过"界面上改了没反应"）。所有配置改动落在引擎平台配置层 `(engine, platform, device_id=0)` 或设备独立配置层。
17. **策略组成员可以直接写本地节点的产物标识**（如 `🇯🇵 日本机房 01 (机房)`），成员顺序就是产物里的优先级，可以把节点插在组中间；`local_nodes` 字段则是整组追加到首或尾。判定"这个名字是谁"只认 `local_nodes.display_name()` / `display_index()` 这一个事实来源——校验器、渲染器、数据自检、界面都不许自己拼一遍「名称 (类型)」，否则节点改名或换类型后会集体失效。
18. **不同节点来源可能有同名节点**，客户端按名字去重会互相覆盖，可用节点数会凭空少一截。每个来源在「节点来源」里配一个「节点名后缀」（下发为 `override.additional-suffix`），保证全局节点名唯一。
19. **节点来源有两种下发方式**：`provider`（写进产物的 `proxy-providers` 段，客户端自己拉取更新）或 `inline`（节点写进产物顶层 `proxies`）。只有 `inline` 的节点会进客户端的 GLOBAL 组——Clash/Stash 的 GLOBAL 只收顶层 proxies 与策略组，provider 里的节点进不去。inline 的代价：机场换节点要重拉订阅才生效；机场订阅只保留 `proxies` 段，机场自带的 rules/dns/策略组不进面板。两种模式下「只分发可用节点」都要生效：provider 模式在 feed 端过滤，inline 模式在构建时按测速结果剔除（`sources.excluded_nodes`），漏掉哪一边这个开关就会静默失效。
20. **规则内容源是独立仓库 `astralwaveorg/magic-sets`，由后台「自主维护」页托管。** 主仓库不再有 submodule 引用（`.gitmodules` 与 `magic-sets/` 已删除）；仓库地址、分支、鉴权凭据存在 `settings.deps_*`，容器运行时把仓库 clone 到 `/app/data/deps/rule-repo`，面板在「自主维护」页里浏览、编辑、提交、推送。仓库分 `rule/`（规则集合）、`script/`（Stash 脚本）、`rewrite/`（HTTP 重写）三个目录。

    面板的规则集分四层：**自维护层**（仓库里的 `rule/*.yaml`，当前 13 个集合，在面板里是 `kind='repo'`，内容由同步写入，**不再经 jsDelivr 中转——推上去面板的 `/res/rule/<name>` feed 立刻是新内容，没有 12 小时 CDN 缓存**）；**上游通用层**（MetaCubeX/meta-rules-dat 的 mrs，`kind='remote'`）；**上游应用集合层**（blackmatrix7/ios_rule_script 的 `rule/Clash/<集合名>/<集合名>.yaml`，yaml，行为 `classical`，一条文件混多种规则类型，如 `XiaoMi`——**不进自维护仓库**，那是自维护层）；**第三方成品库**直接引别人的成品规则直链（mrs、行为 `domain`）。**广告拦截原则（2026-10-31 向阳定稿）：宁可不拦截，不能误拦截。** 曾引入 `TG-Twilight/AWAvenue-Ads-Rule` 的 `No.Unwelcome` 变体（875 条）做广告拦截，排查发现黑盒列表里混有功能性域名（京东 `mapi.m.jd.com`、京东图片 `img2.360buyimg.com`、淘宝风控 `audid-api.taobao.com`、微信视频号 `wxsnsdy.tc.qq.com`、乐播投屏认证 `vipauth.hpplay.cn`、小米系统组件 `api.installer.xiaomi.com` 等），且 mrs 整体生效无法逐条裁剪——已删除其两条规则并停用该来源（来源保留，随时可重启用）。现行广告拦截只走自维护 `magic-reject`（4 条纯 Google 广告域，零误杀）。要扩充广告拦截，往 `magic-reject` 里逐条加自己核实过的域名，不要整包引第三方列表。

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
27. **策略组的顺序是向阳精心配置过的基线，不得变更。** 下面这 32 个策略组的先后顺序（含 `sort` 值）是基线，括号内是 `sort`：

    ```
    🚀 默认代理(0) → 🛑 广告过滤(1) → 🔍 谷歌服务(2) → 🧠 人工智能(3) → 💻 开发工具(4)
    → 🎮 海外游戏(5) → 🎞️ 国际影音(6) → 🎵 TikTok(7) → 💬 即时通讯(8) → 👥 海外社交(9)
    → 🍎 苹果服务(10) → Ⓜ️ 微软服务(11) → 🛒 跨境电商(12) → 🪙 加密货币(13) → ⚡️ 自动测速(14)
    → 🇯🇵日本(15) → 🇺🇸美国(16) → 🇹🇼台湾(17) → 🇰🇷韩国(18) → 🇸🇬 新加坡(19) → 🇭🇰香港(20)
    → 🌍欧洲(21) → 🇯🇵 日本机房(22) → 🇺🇸 美国机房(23) → 🇯🇵 日本自动(24) → 🇺🇸 美国自动(25)
    → 🇹🇼 台湾自动(26) → 🇰🇷 韩国自动(27) → 🇭🇰 香港自动(28) → 🌍 欧洲自动(29)
    → 🇸🇬 新加坡自动(30) → 🏠 路由回家(31)
    ```

    > 基线于 2026-10-26 核对：线上 32 个组，顺序与本段逐项一致。`🇸🇬 新加坡`（外层可见组，`sort=19`）
    > 与内层隐藏组 `🇸🇬 新加坡自动`（`sort=30`）成对。
    > 上一版写的 `🇸🇬 新加坡(15)` 与线上不符，已按线上实际顺序改正。
    > 曾短暂存在的 `🏠 私有网络` 组已删除——私有地址必然直连，单独一个组没有意义，
    > `private` / `private-ip` 两条规则直接指向 `DIRECT`。

    **任何重构（菜单重排、页面合并、构建流程改动、数据层切换）都不得改动这个先后顺序**，包括不得重排 `sort` 值。新建组只能追加到指定位置；删除组时其余组的相对顺序不变。改动前先拉线上当前顺序核对，改动后逐项比对确认一致。**要改顺序必须向阳明确要求。**

28. **各列表的 `sort` 值必须全局唯一，否则拖拽排序会静默失效。** `sort` 是全局排序键，同值的两组相对顺序退回由 `id` 决定，界面上拖了没反应。`reorder_subset`（`server/app/db.py`）现在会在重排前检测重复并整表按当前顺序重编号消歧，相对顺序不变；子集重排按"连续块"语义放回原位置区间，区间内其余行整体顺延。**因此重排后要重新核对上条的基线**——`sort` 数值可能被消歧改掉（相对顺序不变）。消歧只在存在重复时触发，正常路径不动任何数值。

29. **后台页面结构已重排（2026-10-25）。** 侧边栏 12 项，顺序是：系统状态 → 策略组 → **分流策略** → 节点来源 → 规则来源 → **基础配置** → 设备管理 → **拓展模块** → **构建发布** → **自主维护** → 审计日志 → 系统设置。分流规则紧跟策略组——规则的目标就是策略组，改规则时来回切这两页最频繁。

    - 「引擎平台」不再是独立页面，是「基础配置」的第一个 tab（`?tab=targets`）；「产物配置」是第二个 tab（`?tab=artifact`）。
    - 「自动构建发布」不再是独立页面，是「构建发布」的第二个 tab（`?tab=auto`）；页面标题行的「立即发布」是两个 tab 共享的页面级操作。
    - 旧路径 `/admin/targets`、`/admin/automation` 会重定向到新位置，不产生死链。
    - 改名只动显示层：路由路径、API 路径、数据库表名与列名、审计的 `object_type` 一律不动；审计的 `action` 文案用新称，**历史记录保持原文案**。

30. **「一键发布」与「立即发布」是两个动作。** 一键发布（`POST /api/v1/builds/{id}/publish-both`）发布**已有的这个构建**，内部是同一事务里先置测试再置生产，发布历史只记一条；立即发布触发一整轮自动任务（抓取 → 测速 → 创建**新**构建 → 发布）。两者名字相近，界面上必须让用户分得清。

31. **DNS 段固化在「引擎默认配置」（源码基线 `server/app/services/base_config.py`），其他层一律不得写 `dns:` 键。** 2026-10-27 定稿方案（旧方案"默认境外 DoH 走代理"把所有未命中策略域名的解析绑在代理可用性上，代理一抖国内网站成片打不开，已废弃）：默认 `nameserver` 为国内 DoH 裸 IP 直连双运营商并发（`120.53.53.53` 腾讯 doh.pub + `223.5.5.5` 阿里）；海外敏感域（Fake-IP 排除清单里的海外域：微软全家 + `lens.l.google.com`）与直连的海外集合（`rule-set:mirror-accelerate` / `pt` / `trackers`）在 `nameserver-policy` 指到境外 DoH（`1.1.1.1` / `8.8.8.8`，经代理出口）。核心依据：Fake-IP 下走代理的连接由节点远程解析，本地答案无关紧要；本地答案只对「Fake-IP 排除清单的海外域」与「DIRECT 连接」有意义。alidns（223.5.5.5）对海外域有污染，但本设计下默认解析器的海外答案永远不会被使用，放它只为运营商冗余。**国内域名不需要任何显式 `nameserver-policy`**——默认就是国内 DoH，显式写反而退化成单服务器。

    - **维护位置与禁改范围**：DNS 段（nameserver / nameserver-policy / proxy-server-nameserver / follow-rule / respect-rules / ipv6 等）只改源码基线；**引擎平台配置、平台扩展（targets.extra_yaml）、设备独立配置、拓展模块都不许写 `dns:` 键**——平台扩展与设备层是追加合并，写了就会悄悄盖过基线（2026-10-27 就从平台扩展和 4 个设备层里清掉过残留的 `vpn.jiek.top` 策略）。家用 Fake-IP 清单仍在平台层用 `_fake_ip_filter` 伪键维护（伪键不是 dns 键）。
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
    - **OpenClash-Mihomo 目标（mihomo/linux，构建 183）**：面向 OpenWrt OpenClash 的 Mihomo 内核，按 Aethersailor/Custom_OpenClash_Rules wiki 的「最小配置」原则设计——产物只提供节点/策略组/规则，入站端口、运行模式（TUN/TPROXY）、DNS、嗅探、external-controller 全部由 OpenClash LuCI 覆写，**平台扩展保持为空，不要往里写 tun 或端口**；平台层只有路由器必需的三键：`allow-lan: true`、`bind-address: "*"`、`find-process-mode: off`（mihomo 官方建议路由器关进程匹配）。该目标暂无设备，属于预留。
**改 AGENTS.md 这类文档必须改在 mini 仓库再部署——直接改 NAS 侧文件会被 deploy 的 rsync --delete 覆盖掉（2026-10-28 踩过）。**

34. **QUIC 分轨：直连放行，代理链路强制回退 TCP（2026-10-31 修订 10-28 决策）。** 10-28 的实测结论仍然成立：Fake-IP 修复后 UDP/QUIC 直连链路畅通，语音/游戏/P2P 必须放行 UDP，所以**不做全局禁 QUIC**。但「任何应用都不出现访问异常」的目标下，QUIC 经 VPN 隧道（尤其手机蜂窝网络）的转发质量无法逐设备保证，而官方 FAQ（stash.wiki/faq/effective-stash）明确建议对走代理的流量禁 QUIC。定稿方案是一条逻辑规则：`AND,((NETWORK,udp),(DST-PORT,443)),REJECT`，排在尾部直连块（`private-ip`）之后、`MATCH` 之前——**只拦“本来就要走代理”的 QUIC**，国内直连流量早在 `cn`/`cn-ip` 命中 DIRECT，QUIC 完全不受影响；未命中任何规则的 QUIC 被拒后应用自动回退 TCP/2，兼容性优先于 HTTP/3 首包收益。两引擎语法一致（Stash 与 Mihomo 都支持 AND 逻辑规则），一行配置全覆盖，不需要逐 App 覆写。带 `no-track`（Stash 侧）避免 REJECT 刷屏连接列表；**不要加 `pre-matching`**（旧版本客户端可能加载失败，约束 24）。若未来要把某类代理流量恢复 QUIC，改这条规则而不是加客户端覆写。

## 改完要做的事

```bash
cd server && ../.venv/bin/python -m pytest tests -q     # 后端测试
npm run build                                           # 前端构建
.venv/bin/python scripts/check_secrets.py               # 凭据扫描
DEPLOY_PROXY=http://10.0.1.8:7890 bash scripts/deploy.sh   # 发布（脚本自带数据自检与域名验证）
# DEPLOY_PROXY 会注入 NAS 端的 docker build，构建时要拉 npm 与 pip 包，
# 所以必须写 Mac mini 的内网地址 10.0.1.8，不能写 127.0.0.1
```

配置类改动还要**重新构建发布**才生效（只有设备独立配置例外，分发时实时叠加）。

## 客户端侧核对

本机 Mac mini 上的 Stash 4.4.0 装了命令行 `stash`，能直接问**正在运行的核心**，比在产物 YAML 里推演可靠：

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
