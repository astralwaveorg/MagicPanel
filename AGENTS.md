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

    面板的规则集分四层：**自维护层**（仓库里的 `rule/*.yaml`，28 个集合，在面板里是 `kind='repo'`，内容由同步写入，**不再经 jsDelivr 中转——改完推上去，客户端下一次拉取就是新的，没有 12 小时缓存**）；**上游通用层**（MetaCubeX/meta-rules-dat 的 mrs，`kind='remote'`）；**上游应用集合层**（blackmatrix7/ios_rule_script 的 `rule/Clash/<集合名>/<集合名>.yaml`，yaml，行为 `classical`，一条文件混多种规则类型，如 `XiaoMi`——**不进自维护仓库**，那是自维护层）；**第三方成品库**直接引别人的成品规则直链（如 `TG-Twilight/AWAvenue-Ads-Rule` 的 `Filters/*.mrs`，mrs、行为 `domain`，当前只有广告过滤这一条）。

    集合名 = 仓库文件名去扩展名（文件名是引用键），中文展示名写在文件头注释里。**集合含 IP 段时用它的 `_No_Resolve` 变体**（`<集合名>_No_Resolve.yaml`），IP 条目自带 `no-resolve`，客户端遇到域名请求不会为这条规则白做一次 DNS 解析；`DMM` / `JOOX` / `KakaoTalk` / `Naver` / `Yandex` / `Twitch` / `Amazon` 都是这种。blackmatrix7 的 `rule/Clash/` 目录实际有 666 个集合目录，可用的不止 README 里列的那些。

    面板抓取后存进 `rule_providers.content`，产物里的 rule-providers URL 仍指向面板自己的 `/res/rule/<name>` feed 端点，客户端从面板拉、不直连 GitHub（**客户端协议不变**）。

    `script/` 与 `rewrite/` 片段默认停用：脚本会改写全部请求的 UA，重写依赖 HTTP 引擎与设备信任 CA，而拓展模块没有按设备生效的粒度。仓库托管实体的内容只读，改动只在自主维护页做；启用状态归面板。
21. **规则顺序就是优先级**：客户端从上往下第一条命中即生效，所以顺序必须按「越具体越靠前、同一目标组聚成一块」排。当前 125 条规则（`sort` 0–124）分十一块：① 本地与保留地址直连 ② 网络层直连（`private` / `private-ip` / `dns-direct` / `local-process` / `direct-ports`）③ 广告（REJECT）④ 设备专属直连（`self-hosted` / `jp` / `kr` / `connectivity-check` / `mirror-accelerate` / `lvsp-direct`）⑤ Steam 香港 ⑥ **小而明确的直连集合**（`ai-cn` / `apple-cn` / `apple-push` / `PrivateTracker` / `microsoft-cn` / `games-cn` / `pt` / `trackers` / `AmazonCN` / `XiaoMi`）⑦ 服务分组（同一目标组连续成一块）⑧ 路由回家 ⑨ 通用代理兜底（`proxy` / `proxy-domain`，在「🚀 默认代理」块末尾）⑩ **大而泛的直连集合**（`cn-services` / `cn` / `cn-ip`）⑪ `MATCH`。

    **大而泛的直连集合一律往后排**：`cn`（110k 条）、`cn-ip`（10k 条）、`cn-services` 排在强制代理与服务分组之后、`MATCH` 之前。理由是它们会把**所有**国内域名先拦去直连，任何一条更具体的规则都轮不到——2026-10-25 的 v2ex 故障就是这么来的：`cn-services` 里的 `+.v2ex.com` 抢先命中直连，而 `proxy-domain` 里写的是笔误 `+.v2ex.co`（`v2ex.co` 根本没有 A 记录），两条凑在一起让强制代理彻底失效。改成「先分流、未列出的兜底走代理」之后，漏配一条直连规则只会让线路不最优，不会让服务打不开。反过来，**小而明确的直连集合仍留在服务分组之前**，它们条目少、指向明确，抢先命中是对的。

    第 ⑦ 块内部再分三层，顺序不能乱：**地区锁服务**（🇯🇵日本 / 🇹🇼台湾 / 🇭🇰香港 / 🇺🇸美国 / 🌍欧洲）→ **主题细分**（🛒 跨境电商 / 🪙 加密货币 / 💬 即时通讯 / 👥 海外社交 / 🎞️ 国际影音 / 💻 开发工具）→ **宽泛合集**（`media` / `disney` / `social` / `games` 等）。地区锁服务必须早于宽泛合集：`media` 里有 10 条 BBC 域名、`disney` 里有 47 条 Hulu 域名，宽泛合集先命中就播不了英国版权区、看不了 Hulu。

    五条硬约束：`MATCH` 永远最后；`ai-cn` / `apple-cn` / `microsoft-cn` / `games-cn` 必须早于对应父集合 `ai` / `apple` / `microsoft` / `games`，否则国内子集合整体失效；`steam-cn` 必须早于 `cn`（实测与 cn 重叠 13 条，Steam 中国的域名）；`proxy` / `proxy-domain` 放在「🚀 默认代理」块末尾，且**必须早于** `cn-services` / `cn` / `cn-ip`；`cn-services` 只保留「上游集合未覆盖 + 实测必须直连」的条目（当前 31 条），不要往里塞国内服务的国际版与境外节点——那些直连必然超时，应交给兜底走代理。

    改顺序前先读 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「规则顺序：按目标分组」。
22. **同一件事的两份清单必须合并，不然其中一份大面积失效。** 上游 `geosite/steam@cn`（19 条）与 blackmatrix7 `SteamCN`（17 条）重叠 14 条，后者 82% 的条目永远走不到、且 14 条路由方向与写规则时的意图相反。已删 `SteamCN`，把它独有的 2 条域名拆成 `DOMAIN-SUFFIX` 规则继续直连。**判断办法**：拿每个集合的条目与面板全部现有集合求交（严格区分 `DOMAIN` 精确与 `DOMAIN-SUFFIX` 后缀语义，后缀回溯要停在公共后缀之前，behavior 用面板声明值，mrs 要换同名 yaml 等价物），交集大到让规则大面积失效时，删重复的那份、把独有内容拆成小规则，别靠调顺序。
23. **`ipcidr` 行为的规则集必须加 `no-resolve`。** 官方文档明确「ipcidr 类规则集支持 no-resolve 参数」：不加的话客户端遇到域名请求会先为这条规则做一次 DNS 解析再判断 IP 是否命中。判断依据是来源的 `behavior`，不是规则的 `type`——`RULE-SET` 规则的 `no_resolve` 只会对 `ipcidr` 行为真正生效。新建 `ipcidr` 来源后要同步把引用它的规则勾上 no-resolve。
24. **规则与规则集改动后要按官方文档复核一遍。** 白名单以官方文档为准，不靠记忆：Stash <https://stash.wiki/rules/rule-types>、<https://stash.wiki/rules/rule-set>；Mihomo <https://wiki.metacubex.one/config/rules/>、<https://wiki.metacubex.one/config/rule-providers/>。要核对的项、已发现过的问题（`kr` 漏 no-resolve）以及 Stash 独有能力（`no-track` / `pre-matching`）都写在 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「规则与规则集的规范核对」。Stash 独有的 `no-track` / `pre-matching` **只写进 Stash 产物**（Mihomo 的规则参数只有 `no-resolve` 与 `src`；实测 Mihomo 遇到未知参数会忽略、不会加载失败，但产物里不写更清楚）；`pre-matching` 还要求目标是 `REJECT` 字面量、用策略组会直接加载失败，且只对 Stash iOS/tvOS 3.7+、macOS 4.4+ 生效，版本太旧的客户端可能加载失败。兜底规则（MATCH）不能加 `no-track`，否则客户端不记录任何连接。同一个规则集可以在互斥的引擎平台各挂一条（广告过滤就是这么分轨的），「规则重复」判定只看适用范围有无交集。
25. **服务分流要按「这个服务到底要什么」分派，不要一律丢进默认代理。** 三类需求对应三种落法：**地区锁服务**（Pixiv / DMM / Hulu / BBC，换 IP 就打不开）→ 指向对应地区组；**账号风控服务**（Discord / Slack / Amazon / 币圈，对出口 IP 的信誉与地区一致性有校验）→ 指向固定出口的 `select` 组（🛒 跨境电商 / 🪙 加密货币，本地节点排最前），别交给 `url-test` 自动切 IP；**上游大集合吃掉了本该更细路由的域名**（`media` 里的 BBC、`disney` 里的 Hulu）→ 拆出服务专属集合并排在宽泛合集之前。判断"这个集合值不值得加"必须与面板全部现有集合求交，看净增量与路由错位，算增量的三个坑（公共后缀回溯、behavior 不能嗅探、mrs 要换 yaml 等价物）写在 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「服务细分：按用途与地区分派」。
26. **社交类分流按用途分两组：💬 即时通讯 与 👥 海外社交。** 前者是点对点聊天、群聊、通话、消息推送（Telegram / WhatsApp / Signal / Discord / LINE / Viber / KakaoTalk / Messenger / Snapchat / Element / Session / Threema / SimpleX / Wire / Zalo / Slack），后者是动态、发帖、图文流、关注、社区（Twitter / Instagram / Facebook / Reddit / Threads / Bluesky / Tumblr / Pinterest / LinkedIn / TruthSocial / VK / OK / Quora / Lemmy / Nextdoor / GETTR / Minds / MeWe / Gab / Mastodon）。**两个块在第 7 块内各自连续，通讯块必须排在社交块前面**——两块都含 LINE / Messenger / Discord 的域名，具体服务集合要排在宽泛的 `social-extra` / `social` 前面，否则走错组。geosite 的 `category-social-media-!cn`（`social`）已覆盖 Twitter / Facebook / Instagram / Threads / Tumblr / LinkedIn / TruthSocial / VK / Bluesky / Mastodon 的全部条目，**不要再为它们建单服务集合**（同约束 22 的重复清单）；只有净增量不为零的才建来源。小众服务（Threema / Session / SimpleX / Wire / Viber / Quora / Lemmy / Nextdoor / OK / GETTR / Minds / MeWe / Gab）走自维护层 `chat-extra` 与 `social-niche`，域名逐个核实过。
27. **策略组的顺序是向阳精心配置过的基线，不得变更。** 下面这 32 个策略组的先后顺序（含 `sort` 值）是基线，括号内是 `sort`：

    ```
    🚀 默认代理(0) → 🛑 广告过滤(1) → 🔍 谷歌服务(2) → 🧠 人工智能(3) → 💻 开发工具(4)
    → 🎮 海外游戏(5) → 🎞️ 国际影音(6) → 🎵 TikTok(7) → 💬 即时通讯(8) → 👥 海外社交(9)
    → 🍎 苹果服务(10) → Ⓜ️ 微软服务(11) → 🛒 跨境电商(12) → 🪙 加密货币(13) → ⚡️ 自动测速(14)
    → 🇸🇬 新加坡(15) → 🇯🇵日本(16) → 🇭🇰香港(17) → 🇹🇼台湾(18) → 🇰🇷韩国(19) → 🇺🇸美国(20)
    → 🌍欧洲(21) → 🇯🇵 日本机房(22) → 🇺🇸 美国机房(23) → 🇯🇵 日本自动(24) → 🇺🇸 美国自动(25)
    → 🇹🇼 台湾自动(26) → 🇰🇷 韩国自动(27) → 🇭🇰 香港自动(28) → 🌍 欧洲自动(29)
    → 🇸🇬 新加坡自动(30) → 🏠 路由回家(31)
    ```

    > 基线于 2026-10-25 刷新：向阳本人新增了 `🇸🇬 新加坡`（外层可见组，`sort=15`），
    > 与内层隐藏组 `🇸🇬 新加坡自动`（`sort=30`）成对，其余组顺序未动。

    **任何重构（菜单重排、页面合并、构建流程改动、数据层切换）都不得改动这个先后顺序**，包括不得重排 `sort` 值。新建组只能追加到指定位置；删除组时其余组的相对顺序不变。改动前先拉线上当前顺序核对，改动后逐项比对确认一致。**要改顺序必须向阳明确要求。**

28. **各列表的 `sort` 值必须全局唯一，否则拖拽排序会静默失效。** `sort` 是全局排序键，同值的两组相对顺序退回由 `id` 决定，界面上拖了没反应。`reorder_subset`（`server/app/db.py`）现在会在重排前检测重复并整表按当前顺序重编号消歧，相对顺序不变；子集重排按"连续块"语义放回原位置区间，区间内其余行整体顺延。**因此重排后要重新核对上条的基线**——`sort` 数值可能被消歧改掉（相对顺序不变）。消歧只在存在重复时触发，正常路径不动任何数值。

29. **后台页面结构已重排（2026-10-25）。** 侧边栏 12 项，顺序是：系统状态 → 策略组 → 节点来源 → 规则来源 → **基础配置** → 分流规则 → 设备管理 → **拓展模块** → **构建发布** → **自主维护** → 审计日志 → 系统设置。

    - 「引擎平台」不再是独立页面，是「基础配置」的第一个 tab（`?tab=targets`）；「产物配置」是第二个 tab（`?tab=artifact`）。
    - 「自动构建发布」不再是独立页面，是「构建发布」的第二个 tab（`?tab=auto`）；页面标题行的「立即发布」是两个 tab 共享的页面级操作。
    - 旧路径 `/admin/targets`、`/admin/automation` 会重定向到新位置，不产生死链。
    - 改名只动显示层：路由路径、API 路径、数据库表名与列名、审计的 `object_type` 一律不动；审计的 `action` 文案用新称，**历史记录保持原文案**。

30. **「一键发布」与「立即发布」是两个动作。** 一键发布（`POST /api/v1/builds/{id}/publish-both`）发布**已有的这个构建**，内部是同一事务里先置测试再置生产，发布历史只记一条；立即发布触发一整轮自动任务（抓取 → 测速 → 创建**新**构建 → 发布）。两者名字相近，界面上必须让用户分得清。


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

## 官方文档

改配置键之前先在线核对官方文档，别凭记忆写：

```sh
python3 scripts/docs_lookup.py search <关键词> --product stash   # 或 mihomo
python3 scripts/docs_lookup.py read <官方页面 URL>
```

流程与要求见 [官方文档查阅流程](docs/reference/Official-Docs-Workflow.md)。
