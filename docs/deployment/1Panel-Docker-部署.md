# 部署：1Panel + Docker

本文以 NAS 上的 1Panel 为例，把 MagicPanel 部署到 `https://magichub.top:8443`。
根路径 `/` 是门户展示页（PIN 进入），`/admin` 是管理端。

## 组成

一个容器，编排文件为仓库根目录的 `docker-compose.yml`：

- 镜像由根目录 `Dockerfile` 多阶段构建（Node 编译前端 → Python 3.12 运行时，非 root 运行）。
- 数据目录 `./data` 挂载到容器 `/app/data`，内含数据库、`secret.key` 主密钥、构建产物与测速核心，**请纳入 1Panel 备份计划**。
- 容器只监听 `127.0.0.1:47100`，不直接对外；对外由 1Panel 的 OpenResty 反向代理承担 TLS。

## 步骤

### 1. 获取代码

```bash
mkdir -p /opt/magicpanel && cd /opt/magicpanel
git clone git@github.com:astralwaveorg/MagicPanel.git .
```

也可以在 1Panel「容器 → 编排 → 创建编排」中直接粘贴 `docker-compose.yml` 并把构建上下文换成代码目录。

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
2. 「设置」中为每位维护者设置各自的门户 PIN（4 位数字）。
3. 配置节点来源、策略组、规则与引擎平台，创建构建并发布到测试环境；确认无误后发布到生产环境。
4. 打开「自动发布」页，确认自动抓取、测速、构建与发布环境；定时任务随容器启动，无需额外配置系统 cron。
5. 家人访问 `https://magichub.top:8443/`，输入任一维护者的 PIN 即可查看并复制订阅地址。

定时任务为单进程内循环，适合当前单容器部署；不要对同一 `./data` 同时启动多个带调度器的实例。临时关闭可设置环境变量 `MAGICPANEL_SCHEDULER=0`。

## 升级

```bash
cd /opt/magicpanel
git pull
docker compose up -d --build
```

数据库结构变更会在启动时自动迁移，无需人工干预。

## 卸载

```bash
docker compose down
# 数据仍在 ./data；确认不再需要后手动删除
```
