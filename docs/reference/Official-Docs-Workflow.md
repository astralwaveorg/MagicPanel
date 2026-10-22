# 配置修改前的官方文档查阅流程

本流程落实根目录 `AGENTS.md` 的硬性约束：修改配置、模板、覆写、规则格式或配置生成脚本前，必须核对目标产品的官方文档。摘要、已有配置和记忆只能用于定位，不能代替原文。

## 最短查阅路径

1. **确定目标**：识别客户端、内核版本、操作系统与配置用途。优先查项目部署说明、用户已提供的信息及可用的版本命令。目标版本未知时，明确说明假设；会影响字段支持或行为时，先核实再改动该部分。
2. **定位字段**：用本地索引找相关页面，通常先选 1–3 页。涉及协议时，兼顾协议专用页与通用字段、TLS、传输层等依赖。
3. **读取原文**：每个相关页面在本次任务中至少联网读取或校验一次。核对字段类型、作用域、默认值、相互依赖、弃用信息、平台／最低版本。短节未包含示例时，补读同页配置样例及引用页面。
4. **修改与验证**：只使用有文档依据且与目标兼容的写法；检查 YAML／规则格式，再使用目标内核或客户端验证。无法确认文档、版本兼容性时，停止受影响的改动，说明缺少什么依据。
5. **留下证据**：最终说明或 PR 列出相关官方 URL、版本／平台假设、执行的验证及未完成的检查。无需把整页原文贴进报告。

## 选择正确的官方来源

| 目标 | 导航／官方来源 | 注意 |
| --- | --- | --- |
| Mihomo | [本地配置导航](Mihomo-Config-Navigation.md)／[官方配置区](https://wiki.metacubex.one/config/) | Android、Linux、macOS 的路由、接口与权限条件分别核对。 |
| Stash | [本地全站导航](Stash-Wiki-Navigation.md)／[官方文档](https://stash.wiki/) | Mihomo 扩展字段不能视为 Stash 自动支持。 |
| Surge | [官方手册](https://manual.nssurge.com/) | 本工具不支持 Surge（`--product` 只接受 `mihomo` / `stash`），需用浏览器或网页工具读取对应官方章节。 |
| 订阅转换模板／生成脚本 | 转换工具官方说明 + 输出目标的官方文档 | 同时核对模板语法和最终生成字段。 |

## 本地检索与定向读取

工具仅依赖 Python 标准库，任意目录均可执行；以下命令以仓库根目录为例。

```sh
# 只查元数据，不联网，不输出整份索引。
python3 scripts/docs_lookup.py search respect-rules --product mihomo
python3 scripts/docs_lookup.py search nameserver-policy --product stash

# 先联网核对，仅读相关章节；默认最多 80 行。
python3 scripts/docs_lookup.py read https://wiki.metacubex.one/config/dns/ --section respect-rules

# 不清楚标题时，只列标题；后续可在本任务内复用已校验的缓存。
python3 scripts/docs_lookup.py read https://wiki.metacubex.one/config/inbound/tun/ --outline
python3 scripts/docs_lookup.py read https://wiki.metacubex.one/config/inbound/tun/ --section auto-route --offline

# 找示例或关键字；不足时调大输出范围。
python3 scripts/docs_lookup.py read https://wiki.metacubex.one/config/dns/ --find proxy-server-nameserver --max-lines 60
python3 scripts/docs_lookup.py read https://stash.wiki/configuration/override --section 语法参考
```

- `search` 默认最多 5 条，可用 `--limit` 调整。索引含 79 个 Mihomo 配置页与 44 个 Stash 中文主题，不重复收录翻译；词组按空格分词并要求全部命中。查不到时换用实际字段名或打开官方导航，不要据此认定功能不存在。
- `read` 默认联网；如已有 ETag／Last-Modified，则条件请求，HTTP 304 时复用已校验正文。无此响应支持时重新下载，不能声称一定节省网络流量。
- `--section` 优先精确匹配标题，否则要求唯一部分匹配；`--outline` 可确认标题。`--find` 显示首次命中附近片段；`--start-line` 从整页或所选章节的第 N 行起读。
- 输出含来源、UTC 校验时间、正文 SHA256、行号和截断提示。截断、长行裁剪或提取缺失时，扩大范围或打开原文；不要根据残缺示例修改配置。
- `--offline` 不进行联网校验，只能用于检索预览，或在同一次任务中重复读取已联网核对的页面。网络失败时工具报错，不自动把旧缓存当最新文档。

## 如何节省 token 和时间

| 层级 | 保留内容 | 何时读取 |
| --- | --- | --- |
| `AGENTS.md` | 简短的必须遵守规则与流程入口 | 每次任务自动发现；不嵌入整站说明。 |
| `official-docs-index.json` | URL、标题、字段关键词，约 78 KB | 由脚本在本地搜索，只把少量命中输出给助手。 |
| 两份导航文档 | 按主题与任务整理的入口 | 需求不明确或需要跨主题定位时。 |
| `.cache/official-docs/` | 已提取正文、来源、校验时间、响应校验头与内容摘要 | 按页校验，按节输出；不读取整站缓存。 |
| 官网原文／官方源仓库 | 最终核对依据 | 缓存缺失、提取不全、字段新增或存在争议时。 |

首次整理已在本机缓存 79 个 Mihomo 配置页面，约半 MB；缓存受 `.gitignore` 排除，不会随克隆分发。换机器后无需下载整站，第一次 `read` 会按需生成缓存。缓存丢失不影响本地索引检索。

同一任务先读取通用字段，再读取专用字段；已经核对的同页用 `--offline` 取下一节，避免重复下载。不要为追求少读而跳过相互依赖、版本警告或完整示例。

## 验证与约束的边界

Mihomo 可先用 `mihomo -v` 确认本地版本，再按其帮助运行 `mihomo -t -f <配置文件>`。测试可能需要规则资源和 GEO 数据；不要为了通过测试删掉未准备好的依赖，也不要直接在生产目录运行不熟悉的脚本。Stash／Surge 使用各自客户端支持的配置检查或导入方式。YAML 能解析并不证明字段有效，更不证明分流、DNS 或路由运行正确。

`AGENTS.md` 是对助手的硬性工作指令；检索工具提供来源追踪和输出限制，但无法自动证明每次编辑在语义上符合文档。文档核对与目标客户端验证必须同时执行；不把关键词命中或一次成功下载当成合规证明。

新增官方页面时更新索引和导航，并联网核对地址；不要把完整 HTML、正文缓存、真实订阅或认证信息提交到 Git。若要复核改动依据，在最终说明中保留确切官方链接及必要的字段说明即可。
