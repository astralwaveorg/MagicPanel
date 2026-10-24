# AGENTS.md

改动这份代码前，先读这三份文档：

| 要做的事 | 看哪份 |
| --- | --- |
| 改界面、改后端逻辑 | [开发文档](docs/开发文档.md) |
| 改配置（规则、策略组、引擎平台、设备独立配置、功能模块） | [配置文档](docs/配置文档.md) |
| 回答"这个页面怎么用" | [使用文档](docs/使用文档.md) |
| 改规则集、决定直连还是代理、走哪个策略组 | [规则集与分流设计](docs/reference/规则集与分流设计.md) |
| 查内网地址、代理端口、哪台机器在跑什么 | [环境与地址速查](docs/reference/环境与地址.md) |

**第一次接手本项目**（新 Agent、换机器、隔了很久再来）：先读
[Agent 交接提示词](docs/reference/Agent-交接提示词.md)，里面写清了架构、硬性约束、
改配置的方式和发布流程，再动手。

## 硬性约束

1. **结构化内容不能被配置层覆盖。** `proxies` / `proxy-providers` / `proxy-groups` / `rule-providers` / `rules` 五个键，产物配置（引擎默认配置 / 引擎平台配置 / 设备独立配置）、平台扩展、功能模块都不许写，服务端硬校验。
2. **兜底规则永远在最后。** 规则按 `sort` 排序，`MATCH` 之后不能有规则（`FINAL` 代码里仍作兼容处理，但界面建不出来）。
3. **规则类型按引擎白名单校验。** Stash 与 Mihomo 支持的类型不同，超出白名单客户端会加载失败。
4. **引擎平台唯一。** `(engine, platform)` 只能有一个，重复写入 409。
5. **列表的合并语义分两种**：引擎默认配置 / 引擎平台配置 = 整体替换；设备独立配置 = 追加。差异计算、层级合并、分发叠加三处必须一致。
6. **设备独立配置的键跟着设备的引擎平台走**，换平台时要自动换键，否则配置静默失效。
7. **改数据库结构走迁移**，不要手动 `ALTER TABLE`；迁移必须幂等。
8. **凭据不进仓库。** `scripts/check_secrets.py` 会在 CI 与部署前拦一次。
9. **改引擎默认配置要核对官方文档。** `scripts/check_engine_defaults.py` 逐键对账，出处要落在 `official-example/`。
10. **命名只有三个层级名**：引擎默认配置 / 引擎平台配置 / 设备独立配置，代码、注释、界面、文档保持一致；页面叫「产物配置」，引擎平台自己的片段叫「平台扩展」。
11. **地区策略组一律 `url-test`，跨地区只留一个「⚡️ 自动测速」组。** 日常组按实测延迟自动选（`interval` 600、`tolerance` 100）。跨地区择优用 url-test（成员 = 各地区组 + 本地机房节点），不另建 `fallback` 兜底组：fallback 只保证连得上、不保证快，限速节点会被一直用下去。同一地区不要建「稳定 / 优选」两套组。
12. **兜底规则是 `MATCH → 默认代理`，不是直连。** 面板采用"先分流、未列出的全部走代理"：漏配一条规则只会让线路不最优，不会让服务打不开。改兜底方向前先想清楚影响面。
13. **地区维度只保留两类组**：各地区单独命名的组（🇭🇰 香港 / 🇯🇵 日本 / 🇸🇬 新加坡 / 🇹🇼 台湾 / 🇺🇸 美国 / 🇰🇷 韩国）+ 机房组（🇺🇸 美国机房 / 🇯🇵 日本机房）。机房组只放本地机房节点，供"重点标注"用；不要按"散节点"另开同地区组。
14. **引擎平台配置里的 `_direct_domains` 会置顶成直连规则**，排在所有用户规则之前。域名一旦进了这份列表，用户集合里针对它（或它的子域）的条目就是死规则——用户规则改不动它。要让某个子域走别的线路，得先把主域名从 `_direct_domains` 里摘掉，再确认 `self-hosted` 之类的集合能兜住其余子域。
15. **「引擎默认配置」层参与渲染，改它对产物生效。** 产物基线 = 源码内置默认值 `base_config.py` 的 `default_doc(engine)`，叠加用户在「引擎默认配置」层的覆盖（记录在 `(engine, "", 0)`）。渲染层必须复用 `base_config_service.scope_layers()`，不要自己再取一遍源码常量——否则界面显示的生效值与产物内容会不一致（曾出现过"界面上改了没反应"）。所有配置改动落在引擎平台配置层 `(engine, platform, device_id=0)` 或设备独立配置层。
16. **策略组成员可以直接写本地节点的产物标识**（如 `🇯🇵 日本机房 01 (机房)`），成员顺序就是产物里的优先级，可以把节点插在组中间；`local_nodes` 字段则是整组追加到首或尾。判定"这个名字是谁"只认 `local_nodes.display_name()` / `display_index()` 这一个事实来源——校验器、渲染器、数据自检、界面都不许自己拼一遍「名称 (类型)」，否则节点改名或换类型后会集体失效。
17. **不同节点来源可能有同名节点**，客户端按名字去重会互相覆盖，可用节点数会凭空少一截。每个来源在「节点来源」里配一个「节点名后缀」（下发为 `override.additional-suffix`），保证全局节点名唯一。
18. **节点来源有两种下发方式**：`provider`（写进产物的 `proxy-providers` 段，客户端自己拉取更新）或 `inline`（节点写进产物顶层 `proxies`）。只有 `inline` 的节点会进客户端的 GLOBAL 组——Clash/Stash 的 GLOBAL 只收顶层 proxies 与策略组，provider 里的节点进不去。inline 的代价：机场换节点要重拉订阅才生效；机场订阅只保留 `proxies` 段，机场自带的 rules/dns/策略组不进面板。两种模式下「只分发可用节点」都要生效：provider 模式在 feed 端过滤，inline 模式在构建时按测速结果剔除（`sources.excluded_nodes`），漏掉哪一边这个开关就会静默失效。
19. **规则内容源是独立仓库 `astralwaveorg/magic-sets`**，以 submodule 形式挂在 `magic-sets/`。仓库分 `rule/`（规则集合）、`script/`（Stash 脚本）、`rewrite/`（HTTP 重写）三个目录。面板的规则集分四层，都在「规则来源」里填远程地址（**不需要代码改动**）：自维护层填 `https://cdn.jsdelivr.net/gh/astralwaveorg/magic-sets@main/rule/<名称>.yaml`（yaml，25 个集合，集合名与仓库文件名一致，中文展示名写在文件头注释里）；上游通用层填 MetaCubeX/meta-rules-dat 的 mrs 地址；上游应用集合层填 blackmatrix7/ios_rule_script 的 `rule/Clash/<厂商>/<名称>.yaml`（yaml，行为 `classical`，一条文件混多种规则类型，如 `XiaoMi`——**不进 magic-sets 仓库**，那是自维护层）；第三方成品库直接引别人的成品规则直链（如 `TG-Twilight/AWAvenue-Ads-Rule` 的 `Filters/*.mrs`，mrs、行为 `domain`，当前只有广告过滤这一条）。面板抓取后存进 `rule_providers.content`，产物里的 rule-providers URL 仍指向面板自己的 `/res/rule/<name>` feed 端点，客户端从面板拉、不直连 GitHub。**改自维护集合的内容后必须把规则来源 URL 换成 `.../magic-sets@<commit>/rule/<名称>.yaml` 再抓**：jsDelivr 对已存在路径有 12 小时缓存，`@main` 拿到的是旧内容，加 `?v=` 查询参数也无效，换 commit 才拿到新版本。`script/` 与 `rewrite/` 片段默认停用：脚本会改写全部请求的 UA，重写依赖 HTTP 引擎与设备信任 CA，而功能模块没有按设备生效的粒度。`magic-sets/` 不参与镜像构建（Dockerfile 只 COPY `server/app` 与前端产物），部署脚本 rsync 会带上它但不影响产物。
20. **规则顺序按七段结构排，顺序即分流逻辑。** 规则从上往下第一条命中即生效：1 网络层直连 → 2 设备专属 → 3 本地进程直连 → 4 强制代理与地区敏感 → 5 国内与日本线路 → 6 服务分类 → 7 尾例与兜底。三条硬约束：`MATCH` 永远最后；国内直连大集合必须排在服务集合之前（上游 `apple@cn` ⊂ `apple`、`ai-cn` ⊂ `ai` 等，反过来排这四个国内集合会整体失效）；强制代理清单 `proxy`/`proxy-domain` 排在普通直连之前、但排在 `PrivateTracker` 之前（后者含 `DOMAIN-KEYWORD,torrent`，提前会压掉 `proxy-domain` 里 11 个 torrent 域名的强制代理）。第 4 段内部还有顺序：广告过滤两条在最前，`tiktok` 排在账户域名（`mail-password` 等）之后、广告之前，`SteamCN` 要早于 `steam-cn` 与 `steamcontent.com` / `steamstatic.com`。改顺序前先读 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「规则顺序：七段结构」。
21. **`ipcidr` 行为的规则集必须加 `no-resolve`。** 官方文档明确「ipcidr 类规则集支持 no-resolve 参数」：不加的话客户端遇到域名请求会先为这条规则做一次 DNS 解析再判断 IP 是否命中。判断依据是来源的 `behavior`，不是规则的 `type`——`RULE-SET` 规则的 `no_resolve` 只会对 `ipcidr` 行为真正生效。新建 `ipcidr` 来源后要同步把引用它的规则勾上 no-resolve。
22. **规则与规则集改动后要按官方文档复核一遍。** 白名单以官方文档为准，不靠记忆：Stash <https://stash.wiki/rules/rule-types>、<https://stash.wiki/rules/rule-set>；Mihomo <https://wiki.metacubex.one/config/rules/>、<https://wiki.metacubex.one/config/rule-providers/>。要核对的项、已发现过的问题（`kr` 漏 no-resolve）以及 Stash 独有能力（`no-track` / `pre-matching`）都写在 [规则集与分流设计](docs/reference/规则集与分流设计.md) 的「规则与规则集的规范核对」。Stash 独有的 `no-track` / `pre-matching` **只写进 Stash 产物**（Mihomo 的规则参数只有 `no-resolve` 与 `src`；实测 Mihomo 遇到未知参数会忽略、不会加载失败，但产物里不写更清楚）；`pre-matching` 还要求目标是 `REJECT` 字面量、用策略组会直接加载失败，且只对 Stash iOS/tvOS 3.7+、macOS 4.4+ 生效，版本太旧的客户端可能加载失败。兜底规则（MATCH）不能加 `no-track`，否则客户端不记录任何连接。同一个规则集可以在互斥的引擎平台各挂一条（广告过滤就是这么分轨的），「规则重复」判定只看适用范围有无交集。

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
