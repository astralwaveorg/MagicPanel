# MagicPanel

家庭自用的代理订阅配置管理服务：一份策略、按目标编译（Stash / Mihomo）、各设备用固定订阅地址拉取。多位维护者共享同一份数据，账号仅用于访问控制。

- 根路径 `/`：门户展示页，凭维护者的 4 位 PIN 查看并复制订阅地址
- `/admin`：管理端（中文界面，桌面 / 移动端自适应；默认暗色，可切换亮色）
- 后端：FastAPI + SQLite，生产模式直接托管前端产物
- 边界：不开发代理内核、不做流量中转、不提供旁路由或透明代理

设计与行为细节见 [docs/development/MagicPanel-开发规格.md](docs/development/MagicPanel-开发规格.md)。

## 开发

```sh
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
npm install
npm run dev          # API 127.0.0.1:8000，前端 127.0.0.1:7100（已代理 /api 与 /feed）
```

打开 http://127.0.0.1:7100/admin ，首次访问会引导创建第一位维护者账号。

## 测试

```sh
cd server && ../.venv/bin/python -m pytest tests -q
```

## 部署

Docker（推荐，含 1Panel 反向代理步骤）：

```sh
docker compose up -d --build   # 数据持久化在 ./data，监听 127.0.0.1:8100
```

完整步骤见 [docs/deployment/1Panel-Docker-部署.md](docs/deployment/1Panel-Docker-部署.md)。

也可以不用 Docker，打包后裸机运行：

```sh
./scripts/package.sh   # 构建前端并产出 dist/magicpanel-<时间戳>.tar.gz
tar xzf magicpanel-*.tar.gz && cd magicpanel
./run.sh               # 首次运行自动创建虚拟环境并安装依赖，监听 127.0.0.1:8000
```

生产环境应置于反代之后启用 HTTPS，并在「设置」中填写对外基础地址。
运行数据（数据库、加密密钥、构建产物）位于 `data/`，备份时请同时保存 `data/secret.key`（与备份文件分开存放）。
