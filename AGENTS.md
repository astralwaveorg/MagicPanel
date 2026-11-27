# AGENTS.md

本分支维护旧版 MagicPanel（`server/`、`src/`）。开工前运行 `git status --short --branch`。MagicPanel Studio 在 `v2` 分支，使用该分支的交接与部署流程。

## 旧版开发与验证

- 旧版编号约束见[旧版维护约束](docs/development/旧版维护约束.md)。首次接手先读[维护者交接](docs/reference/Agent-交接提示词.md)。按任务查[使用](docs/使用文档.md)、[开发](docs/开发文档.md)、[配置](docs/配置文档.md)和[多方案隔离](docs/reference/方案设计-多套分流方案.md)。修改协议、DNS 或规则类型时，按[官方文档核对流程](docs/reference/Official-Docs-Workflow.md)验证目标引擎。
- 配置层不能覆盖 `proxies`、`proxy-providers`、`proxy-groups`、`rule-providers`、`rules`。引擎默认配置和引擎平台配置替换列表，设备独立配置只追加差异。数据库迁移须幂等，跨方案操作不能修改其他方案的引用或排序。
- 规则按顺序匹配，专项规则先于宽泛集合，最终规则在末尾。停用来源仍须服务已发布的资源；预览不能伪造客户端拉取记录。变更默认值、渲染器或规则时，同时核对目标产物。
- 旧版后端从 `server/` 运行 `../.venv/bin/python -m pytest tests -q`；前端从根目录运行 `npm run test:ui`、`npm run build`。引擎默认值检查用 `.venv/bin/python scripts/check_engine_defaults.py`，凭据扫描用 `python3 scripts/check_secrets.py`。只改文档时核对链接、生成文档站并检查差异。
- 发布旧版应用用 [scripts/deploy.sh](scripts/deploy.sh)，核对运行镜像修订和受影响接口。配置数据变更先备份；测试产物核对通过后再发布生产。发布客户端配置与部署应用是两次不同的操作。

## 文档与现场记录

仓库只保留其他维护者能在新 checkout 中使用的产品说明、工程约束、工具输入和脱敏示例。具体分界见[文档导航](docs/README.md)。生产操作前另读本机交接：网络与路由器限制、既有用户决定、备份位置和回滚条件均按该环境核对。没有对应的现场记录时，不从历史数据推断授权，不执行设备或网络变更。
