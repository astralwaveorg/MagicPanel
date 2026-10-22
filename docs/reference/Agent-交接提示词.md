# Agent 交接提示词

第一次接手本项目（或换了机器、隔了很久再来）时，把这份文件从头到尾读完，然后照着做。
它是一份**给 AI Agent 的说明书**：涵盖架构、心智模型、硬性约束、改动落点、配置修改方式、
测试与发布流程，避免新 Agent 重新摸一遍。

> 配套的三份正文档仍然是事实来源：动手前先读 `AGENTS.md`、`docs/开发文档.md`、
> `docs/配置文档.md`（写界面文案再读 `docs/使用文档.md`）。

---

## 你在 MagicPanel 仓库根目录（已 clone，路径不重要）

这是一个**自托管的代理订阅配置服务**：把机场订阅、规则集、分流规则、策略组、节点来源统一维护在一处，
按客户端（Stash / Mihomo）编译成产物，发布出去，每台设备拿一个固定地址自动更新。

技术栈：FastAPI + SQLite(WAL) + Vue3 + Element Plus，界面是中文，部署在 NAS。
线上地址 `https://magichub.top:8443`（管理端 `/admin`，门户 `/`）。

### 先分清两台机器

这是最容易搞混的一点，动手前先记住：

| 机器 | 地址 | 跑什么 |
| --- | --- | --- |
| Mac mini（开发机，**也是代理机**） | `10.0.1.8` | Stash 混合端口 `7890`；仓库克隆在这台机器上 |
| NAS（主机名 `Altair`） | `10.0.1.2` | 面板容器 `magicpanel`；**所有服务端的事都在这里** |

- **抓取订阅、抓规则集、测速、构建、发布**——都发生在 NAS 容器里。
- 因此 `proxy_url` 这类「服务端用」的代理字段必须填 `http://10.0.1.8:7890`
  （Mac mini 的内网地址）。填 `127.0.0.1` 会连到 NAS 自己，实测 connection refused，抓取全挂。
- **在开发机上跑的脚本**（`release.sh` / `fetch_geo_data.sh`）用 `127.0.0.1:7890`
  或 `10.0.1.8:7890` 都行；但 `deploy.sh` 的 `DEPLOY_PROXY` 是注入 **NAS 端构建过程**的，
  必须用 `10.0.1.8`。

完整地址表、端口归属与自检命令见 [环境与地址速查](环境与地址.md)。

---

## 第一步：先读，别先改

按顺序读完这四份，读完再动手：

1. `AGENTS.md` —— 硬性约束（十条），违反了会直接让客户端加载失败
2. `docs/开发文档.md` —— 架构、数据怎么流动、改动落点速查、测试与发布流程
3. `docs/配置文档.md` —— 每个配置表的数据结构、字段含义、修改路径
4. `docs/使用文档.md` —— 每个页面怎么用（写界面文案前必读，避免和界面对不上）

这三份文档就是事实来源。代码和文档冲突时，先查清楚哪个是现状，再一起改。

---

## 架构一句话版

客户端拿到的 `config.yaml` 由**四层合并**而成，优先级由低到高：

| 层 | 谁维护 | 说明 |
| --- | --- | --- |
| ① 产物配置 | 产物配置页，三层 | 引擎默认配置 → 引擎平台配置 → 设备独立配置 |
| ② 结构化内容 | 节点/策略组/规则各自页面 | 服务端生成，任何配置层都不许覆盖 |
| ③ 功能模块 | 功能模块页 | YAML 片段，字典递归合并、列表追加 |
| ④ 平台扩展 | 引擎平台页 | 单个引擎平台专属片段，最后应用 |

**产物配置的三层**（`base_configs` 表，主键 `(engine, platform, device_id)`）是整个项目的核心心智模型：

- 每一层**只存"相对基线的差异"**，其余自动继承上层
- 基线（`inherited`）：引擎默认配置层 = 程序内置默认值；引擎平台配置 / 设备独立配置 = 上层合并后的生效值
- **列表的合并语义分两种**：引擎默认配置 / 引擎平台配置 = 整体替换；设备独立配置 = 只记新增项、下发时追加
- 差异计算、层级合并、分发叠加这三处必须一致（`diff_overlay` / `cascade` / `apply_device_overlay`）

**适用范围用显式哨兵**，不要写"空 = 全部"：

- `config.ALL_SCOPE = "*"`：`["*"]` = 全部（界面上的「包含所有…」）
- `[]` = 不适用任何平台 / 设备
- 前端对应 `src/scopeOptions.js` 与 `src/components/ScopeSelect.vue`（界面绝不出现裸 `*`）

---

## 硬性约束

完整十条在 `AGENTS.md`，这里是最容易踩的几条：

1. `proxies` / `proxy-providers` / `proxy-groups` / `rule-providers` / `rules` 五个结构化键，
   产物配置三层、平台扩展、功能模块**都不许写**，服务端硬校验（400）
2. 兜底规则 `MATCH` 永远排在最后
3. 规则类型创建时校验 13 种（`config.RULE_TYPES`），构建时再按引擎白名单复查
   （`ENGINE_RULE_TYPES`），超出白名单客户端会加载失败
4. 引擎平台 `(engine, platform)` 唯一，重复写 409
5. 列表合并语义两种（替换 / 追加），差异计算 / 层级合并 / 分发叠加三处代码必须一致
6. 设备独立配置的键跟着设备的引擎平台走，换平台要自动换键，否则配置静默失效
7. 改数据库结构走迁移（`db.py` 里的 `_migrate_xxx`），迁移必须幂等
8. 凭据不进仓库（`scripts/check_secrets.py` 会拦）
9. 改引擎默认配置要核对官方文档（`scripts/check_engine_defaults.py` 逐键对账）
10. 命名只有三个层级名：引擎默认配置 / 引擎平台配置 / 设备独立配置；
    页面叫「产物配置」，引擎平台自己的片段叫「平台扩展」

---

## 仓库结构

```text
server/app/
  routers/     HTTP 接口（122 个），按业务分文件：policy / base_config / sources / targets_devices …
  services/    抓取、测速、发布、调度、备份、base_config（三层合并的算法在这）
  compiler/    产物编译与校验（render.py / validate.py）
  db.py        表结构与迁移
src/
  views/       一个页面对应一个 .vue
  components/  通用组件（ScopeSelect / EnableToggle / StatusDot / Pager …）
  scopeOptions.js   「包含所有」哨兵，与后端 config.ALL_SCOPE 对齐
  snippetPresets.js 功能模块预设（纯前端常量）
scripts/       deploy.sh（发布）/ package.sh / check_data_consistency.py / check_secrets.py / docs_lookup.py
docs/          使用 / 开发 / 配置文档 + 官方文档查阅流程
official-example/ 官方配置样例，核对引擎默认配置用
```

---

## 改配置（数据）：直接改，别去点页面

用户要改规则、策略组、来源、设备、产物配置这类**数据**时，不要走界面，两条路：

1. **走 API**（推荐，有校验有审计）：用管理端账号登录拿 session + CSRF，然后
   `POST/PUT/DELETE https://magichub.top:8443/api/v1/...`。账号密码问用户要，别猜。
2. **直接改库**（批量整理时更省事）：线上库在 NAS 的容器里
   `ssh archon@10.0.1.2` → 容器 `magicpanel` → `/app/data/magicpanel.db`
   （`archon` 是用户名，NAS 的主机名是 `Altair`）。
   改完必须跑 `python3 scripts/check_data_consistency.py`，确认"引用完整、命名统一、
   无冗余覆盖、结构键未被越权写入"。**不要手动 `ALTER TABLE`。**

常用表：`sources` / `rule_providers` / `local_nodes` / `proxy_groups` / `rules` /
`targets` / `devices` / `base_configs` / `snippets` / `settings` / `builds` / `releases` / `audit`。

改数据时容易错的地方：

- 规则靠 `sort` 排序，`MATCH` 必须在最后；`target` 要指向真实存在的策略组
- 策略组 `use_sources` 里的来源名必须存在；用 `["*"]` 表示"所有来源（含以后新增的）"
- 设备 `name` 是**文件名**（产物文件名 = `<name>.yaml`），`note` 才是展示用设备名
- 设备 `target_id` 指向引擎平台；换平台要连带改 `base_configs` 的键
- 产物配置三层：写 `base_configs` 时只写差异，且要按本层的列表语义（设备层 = 追加）
- 结构化内容只能通过业务接口写（服务端会校验），别手写 `rules` / `proxy-groups`

---

## 改界面时的约定

- 表格用 `size="small"`；主数据表的列宽别超过 200px，窄屏断点统一 768px
- **操作列一律用全局 `.op-grid`（两列网格，最后一个落单按钮自动横跨整行）**，
  按钮 `size="small"`，列宽按按钮数给：2 个 150 / 3 个 180 / 4~6 个 200
- 操作列写 `:fixed="isMobile ? false : 'right'"`；窄屏用 `useMobile()` 判断
- 按钮配色：新建/保存 = 实心蓝、触发 = 蓝、检测 = 绿、发布 = 绿、查看 = 青、撤销 = 橙、删除 = 红、中性不加 type
- 文案简洁、明确、不啰嗦；界面用词与 `docs/使用文档.md` 保持一致

---

## 改完必须跑的四件事（顺序固定）

```bash
cd server && ../.venv/bin/python -m pytest tests -q      # 后端测试，全绿才能往下走
npm run build                                             # 前端产物输出到 server/app/static
.venv/bin/python scripts/check_secrets.py                 # 凭据扫描
DEPLOY_PROXY=http://10.0.1.8:7890 bash scripts/deploy.sh # 发布（自带数据自检与域名验证）
```

`DEPLOY_PROXY` 指向 Mac mini 上的 Stash 混合端口。它是通过 ssh 注入到 **NAS 端构建过程**的
（构建时要拉 npm/pip 包），必须写内网地址 `10.0.1.8`；写 `127.0.0.1` 会让 NAS 连自己、拉包失败。

首次 clone 先装依赖：`python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt && npm install`

---

## 发布到 NAS

- 你可能在别的机器上，但**同一内网**，发布链路是通的
- `scripts/deploy.sh` 做的事：跑测试 → 同步代码 → 重建容器 → 等健康检查 → 数据自检 → 域名验证
- 只想快速验证前端用 `--fast`；走代理加 `DEPLOY_PROXY=http://10.0.1.8:7890`
- 线上：容器 `magicpanel`，数据目录 `/app/data`，对外 `https://magichub.top:8443`
- **改完代码 ≠ 客户端拿到新配置**：配置类改动还要在「构建发布」里发一版才生效
  （只有设备独立配置例外，它在分发时实时叠加）

---

## 收尾

- 提交信息写中文，说清"改了什么、为什么"，一次改动一个主题
- 改过的文档同步更新；三份文档 + `AGENTS.md` + `README.md` 都要对得上代码
- 改完部署并在浏览器里实际看一眼（桌面 + 手机宽度），别只看代码就说"好了"
- 门户 PIN 用户改过，别假设是 2468；需要进门户时问用户

---

## 开始之前

先读上面那四份文档，然后回答三件事：

1. 你理解的四层合并与三层基线是什么
2. 你打算先做什么、落在哪些文件
3. 需要用户提供什么（管理端账号、生产库访问方式等）

不要一上来就改代码。
