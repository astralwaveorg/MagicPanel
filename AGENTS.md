# AGENTS.md

## 接手时先确认应用和分支

运行 `git status --short --branch` 确认分支和已有改动。这个仓库维护两套独立应用：

| 任务对象 | 分支与代码 | 交接入口 | NAS 部署脚本 |
| --- | --- | --- | --- |
| MagicPanel Studio | `v2`；后端在 `studio/`，Svelte 前端在 `studio/client/` | [Studio 文档索引](studio/README.md) | [studio/ops/deploy.sh](studio/ops/deploy.sh) |
| 旧版 MagicPanel | `main`；后端在 `server/`，Vue 前端在 `src/` | [旧版 Agent 交接](docs/reference/Agent-交接提示词.md) | [scripts/deploy.sh](scripts/deploy.sh) |

旧版文档中的历史名称「V2」与 `v2` 分支的 Studio 是两套实现。

### MagicPanel Studio（`v2`）

- 改统一订阅、平台模板或运营商分流，先读[订阅与分流设计](studio/docs/订阅与分流设计报告.md)；改独立转换地址，读[订阅转换工具](studio/docs/独立订阅转换工具.md)。转换工具不写平台模板或发布记录。
- 改 GitHub 规则集或客户端规则，读[界面与规则管理验收](studio/docs/界面与规则管理验收.md)。提交规则文件、将文件应用到草稿、检查生效版本，是三个独立操作。核对客户端实际收到的规则时，查看对应平台和线路的生效产物。
- 本地验证按 [Studio CI](.github/workflows/studio.yml) 执行：从仓库根目录运行 `python -m pytest -q studio/tests`；前端类型检查、链接测试和构建在 `studio/client/` 运行。改导入流程时验证对应应用的链接及其内层订阅下载；真机导入另记回执。
- 发布与回滚遵循 [Studio 交付文档](studio/docs/delivery.md)。仅更新 Studio 服务时，用 `STUDIO_DEPLOY_SCOPE=studio bash studio/ops/deploy.sh`。脚本要求当前分支为 `v2`、`studio/` 无未提交改动、HEAD 与远端 `v2` 一致；只归档该提交的 `studio/`。部署后核对 NAS 的 `/opt/magicpanel-v2/current`、镜像 revision 和容器健康状态。不要用旧版脚本部署 Studio。

## 旧版开发与验证

- 旧版编号约束见[旧版维护约束](docs/development/旧版维护约束.md)。首次接手先读[维护者交接](docs/reference/Agent-交接提示词.md)。按任务查[使用](docs/使用文档.md)、[开发](docs/开发文档.md)、[配置](docs/配置文档.md)和[多方案隔离](docs/reference/方案设计-多套分流方案.md)。修改协议、DNS 或规则类型时，按[官方文档核对流程](docs/reference/Official-Docs-Workflow.md)验证目标引擎。
- 配置层不能覆盖 `proxies`、`proxy-providers`、`proxy-groups`、`rule-providers`、`rules`。引擎默认配置和引擎平台配置替换列表，设备独立配置只追加差异。数据库迁移须幂等，跨方案操作不能修改其他方案的引用或排序。
- 规则按顺序匹配，专项规则先于宽泛集合，最终规则在末尾。停用来源仍须服务已发布的资源；预览不能伪造客户端拉取记录。变更默认值、渲染器或规则时，同时核对目标产物。
- 旧版后端从 `server/` 运行 `../.venv/bin/python -m pytest tests -q`；前端从根目录运行 `npm run test:ui`、`npm run build`。引擎默认值检查用 `.venv/bin/python scripts/check_engine_defaults.py`，凭据扫描用 `python3 scripts/check_secrets.py`。只改文档时核对链接、生成文档站并检查差异。
- 发布旧版应用用 [scripts/deploy.sh](scripts/deploy.sh)，核对运行镜像修订和受影响接口。配置数据变更先备份；测试产物核对通过后再发布生产。发布客户端配置与部署应用是两次不同的操作。

## 文档与现场记录

仓库只保留其他维护者能在新 checkout 中使用的产品说明、工程约束、工具输入和脱敏示例。具体分界见[文档导航](docs/README.md)。生产操作前另读本机交接：网络与路由器限制、既有用户决定、备份位置和回滚条件均按该环境核对。没有对应的现场记录时，不从历史数据推断授权，不执行设备或网络变更。
