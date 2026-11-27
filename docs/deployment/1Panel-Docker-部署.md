# 部署：1Panel + Docker

本文以 NAS 上的 1Panel 为例，把 MagicPanel 部署到 `https://magichub.top:8443`。
根路径 `/` 是门户展示页（PIN 进入），`/admin` 是管理端。

## 组成

一个 Compose 项目，编排文件为仓库根目录的 `docker-compose.yml`：

- 镜像由根目录 `Dockerfile` 多阶段构建（Node 编译前端 → Python 3.12 运行时，非 root 运行）。
- 数据目录 `./data` 挂载到容器 `/app/data`，内含数据库、`secret.key` 主密钥、构建产物与测速核心，**请纳入 1Panel 备份计划**。
- 容器只监听 `127.0.0.1:47100`，不直接对外；对外由 1Panel 的 OpenResty 反向代理承担 TLS。
- `subconverter-extended` 使用上游固定版本和 digest，独立于 MagicPanel 镜像。只在项目网络中通过 `http://subconverter-extended:25500` 访问；不映射宿主机端口，不配置 OpenResty 反代，也不挂载 MagicPanel 数据。当前只部署服务，MagicPanel 的订阅流程未接入。

## 步骤

### 1. 获取代码

```bash
mkdir -p /opt/magicpanel && cd /opt/magicpanel
git clone git@github.com:astralwaveorg/MagicPanel.git .
```

新装时可在 1Panel「容器 → 编排」使用本地 Compose 路径。已有生产项目 `magicpanel` 继续使用 `/opt/magicpanel/docker-compose.yml`，不要另建重名项目或保存一份面板内副本。仓库是定义来源，1Panel 用于查看编排、容器状态和日志，以及管理现有反代。

### 2. 构建并启动

```bash
docker compose up -d --build
docker compose ps        # STATUS 应为 healthy
```

测速核心（Mihomo）在首次执行测速时自动下载到 `./data/bin`，无需打进镜像；
NAS 网络访问 GitHub 不通时，在管理端「设置 → 核心下载代理」填一个可用代理即可。

### 3. 配置反向代理（1Panel）

「网站 → 创建网站 → 反向代理」：

- 主域名：`magichub.top`，端口：`8443`，勾选 HTTPS，证书选择已签发的 `magichub.top` / `*.magichub.top` 证书；
- 代理地址：`http://127.0.0.1:47100`。

1Panel 默认反代模板已带 `X-Forwarded-Proto / X-Forwarded-Host`；MagicPanel 以 `--proxy-headers` 启动，
会按这些头生成订阅地址。保险起见，在管理端「设置 → 对外基础地址」填入 `https://magichub.top:8443`，
此后订阅链接与门户页展示地址固定使用该域名。

### 4. 初始化

1. 访问 `https://magichub.top:8443/admin`，自动跳转初始化页，创建第一位维护者账号。
2. 「系统设置」中为每位维护者设置各自的门户 PIN（4 位数字）。
3. 配置节点来源、策略组、规则与引擎平台，创建构建并发布到测试环境；确认无误后发布到生产环境。
4. 打开「构建发布 → 自动运行配置」tab，确认自动抓取、测速、构建与发布环境；定时任务随容器启动，无需额外配置系统 cron。
5. 家人访问 `https://magichub.top:8443/`，输入任一维护者的 PIN 即可查看并复制订阅地址。

定时任务为单进程内循环，适合当前单容器部署；不要对同一 `./data` 同时启动多个带调度器的实例。临时关闭可设置环境变量 `MAGICPANEL_SCHEDULER=0`。

## 生产发布和独立更新

MagicPanel 应用从干净且与 `origin/main` 一致的工作区运行 `scripts/deploy.sh`。该脚本同步 Git 归档，只重建 `magicpanel` 服务，再核对镜像修订、容器健康和外部入口。生产目录是部署副本，不在 NAS 上执行 `git pull`，也不要为更新一个服务而停止或重建整个编排。

转换服务单独上线或更新时，在 NAS 上执行：

```bash
cd /opt/magicpanel
docker compose config --quiet
docker compose pull subconverter-extended
docker compose up -d --no-deps --no-build subconverter-extended
docker compose ps
docker compose exec -T magicpanel python -c "from urllib.request import urlopen; print(urlopen('http://subconverter-extended:25500/healthz', timeout=5).read().decode())"
```

除健康检查外，用不含真实凭据的节点验证 `/sub`，并核对 `magicpanel` 容器 ID、镜像、启动时间和现有反代入口没有变化。更新镜像时先改版本和 digest，再重复这些检查；回退时恢复上一份定义并只重建转换服务。首次上线若需撤下，可单独执行 `docker compose rm -s -f subconverter-extended`。

如果服务要先于主分支上线，可用部署脚本保留的 `docker-compose.override.yml` 暂存同一份服务定义。继续使用已有项目名、目录和 Compose 文件。在生产主文件包含该服务后，先确认有效配置等价，再移除临时 override；已有其他覆盖项时只移除该服务段。更新期间避免通过面板执行整栈重启。

## 卸载

```bash
docker compose down
# 数据仍在 ./data；确认不再需要后手动删除
```
