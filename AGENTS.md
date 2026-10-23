# AGENTS.md

改动这份代码前，先读这三份文档：

| 要做的事 | 看哪份 |
| --- | --- |
| 改界面、改后端逻辑 | [开发文档](docs/开发文档.md) |
| 改配置（规则、策略组、引擎平台、设备独立配置、功能模块） | [配置文档](docs/配置文档.md) |
| 回答"这个页面怎么用" | [使用文档](docs/使用文档.md) |
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
11. **地区策略组用 `url-test`，跨地区兜底只留一个 `fallback`。** 日常组按实测延迟自动选（`interval` 600、`tolerance` 100）；`fallback` 只保证连得上、不保证快，限速节点会被一直用下去。同一地区不要建「稳定 / 优选」两套组。当前唯一的 `fallback` 是 `🧭 稳定优先`（跨地区兜底），其余地区组一律 `url-test`。

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
