# Mihomo 网关代理服务 — 配置手册

> NAS 服务器 (10.0.1.2) | 飞牛OS Debian | Mihomo Meta v1.19.24

## 架构概览

```
                    ┌─────────────────────────────────────┐
  局域网设备 ──────► │  NAS (10.0.1.2) - Mihomo Gateway   │
  (手机/电脑/TV)     │                                     │
                    │  ┌─────────────────────────────┐    │
                    │  │ Mihomo (systemd service)     │    │
                    │  │ HTTP/SOCKS5/透明代理/DNS      │    │
                    │  └──────────┬──────────────────┘    │
                    │             │                         │
                    │  ┌──────────▼──────────────────┐    │
                    │  │ 3x 机场订阅 (proxy-providers)│    │
                    │  │ + 97x 规则集 (rule-providers)│    │
                    │  └──────────┬──────────────────┘    │
                    └─────────────┼───────────────────────┘
                                  ▼
                          互联网 (代理/直连)
```

## 文件结构

```
MagicHub/clash/mihomo/           # 本地仓库（Git 管理）
├── config.yaml                  # 主配置文件（远程 URL: list.magichub.top）
├── mihomo.service               # systemd 服务单元
├── mihomo-maintenance.sh        # 每日重启前维护脚本
├── mihomo-logrotate             # 日志轮转配置
├── mihomo-crontab               # 定时任务
└── README.md                    # 本手册

NAS /etc/mihomo/                 # 远程运行目录
├── config.yaml                  # 运行时配置
├── providers/                   # 订阅节点缓存
├── rules/                       # 规则集缓存（.mrs 文件）
├── logs/                        # 日志
├── cache.db                     # fake-ip 缓存
├── geoip.metadb / geosite.dat   # GeoIP/GeoSite 数据库
└── UI 面板文件                   # 外部管理面板
```

## 端口分配

| 端口  | 协议              | 用途                         |
|-------|-------------------|------------------------------|
| 7890  | HTTP + SOCKS5 混合 | 通用代理                     |
| 7891  | HTTP              | 纯 HTTP 代理                 |
| 7892  | SOCKS5            | 纯 SOCKS5（SSH/Git/终端）    |
| 7893  | HTTP Redirect     | 透明代理（iptables）         |
| 7894  | TProxy            | 透明代理（TPROXY）           |
| 9090  | HTTP RESTful API  | 管理面板 + API               |
| 1053  | DNS               | fake-ip DNS 服务             |

## 代理策略

### 订阅源 (proxy-providers)

| 名称        | 直连下载 | 健康检查间隔 | 说明       |
|-------------|----------|--------------|------------|
| Airport_01  | DIRECT   | 300s         | 机场1      |
| Airport_02  | DIRECT   | 300s         | 机场2      |
| Airport_03  | DIRECT   | 300s         | 机场3      |

### 自动选择组 (URLTest)

| 组名       | 容差 | 检查间隔 | 失败切换 |
|------------|------|----------|----------|
| 家宽自动   | 20ms | 300s     | 立即     |
| 新加坡自动 | 20ms | 300s     | 立即     |
| 美国自动   | 20ms | 300s     | 立即     |
| 日本自动   | 20ms | 300s     | 立即     |
| 台湾自动   | 20ms | 300s     | 立即     |
| 香港自动   | 20ms | 300s     | 立即     |
| 自动选择   | 20ms | 300s     | 立即     |

### Fallback 组

所有 Fallback 组检查间隔 300 秒，按优先级顺序自动故障切换。

### Selector 组

节点选择、Apple、Emby、Steam、Talkatone、LINE 等为手动选择组。

## DNS 架构

```
enhanced-mode: fake-ip
├── fake-ip-range: 198.18.0.1/16 (IPv4) / 2001:480:abcd::1/64 (IPv6)
├── nameserver (解析国内域名): 223.5.5.5, 1.12.12.12 (DoH)
├── fallback (解析国外域名): dns.google, cloudflare-dns.com (DoH)
├── direct-nameserver: doh.pub, 223.5.5.5 (h3)
└── proxy-server-nameserver: doh.pub, 223.5.5.5 (h3)
```

- `respect-rules: true` — DNS 结果受规则约束，避免 DNS 泄露
- `fallback-filter` — 启用 GeoIP + GFWList 双重过滤
- DNS 监听 `0.0.0.0:1053`，可被客户端直接使用

## 规则系统

### 规则来源

全部 97 个 rule-providers 从 GitHub 下载（通过 `proxy: "节点选择"` 经代理访问），使用 `.mrs` 格式。

两个上游规则库：
- **MetaCubeX/meta-rules-dat** — 官方规则（geosite/geoip）
- **Lanlan13-14/Rules** — 社区补充规则

### 规则匹配顺序

```
局域网直连 → PT直连 → 国内AI直连 → 国外AI代理 → 隐私拦截 →
微信 → 银行 → 流媒体(按平台) → 社交媒体 → 游戏 → 电商 →
GFW → GeoLocation-!CN → CN域名直连 → CN IP直连 → MATCH漏网之鱼
```

## 关键优化项（v2）

### 1. rule-providers 代理下载（致命问题修复）

**问题**：全部 97 个 rule-providers 从 `raw.githubusercontent.com` 下载，中国大陆无法直连，导致规则集全部加载失败。

**修复**：为每个 rule-provider 添加 `proxy: "节点选择"`，通过代理下载规则文件。proxy-providers 使用 `proxy: DIRECT` 可直连，节点先于规则加载，不存在鸡生蛋问题。

### 2. Sniffer skip-addr（消除 Telegram 噪声日志）

**问题**：Telegram 使用 MTProto 协议（非标准 TLS），Sniffer 尝试提取 SNI 时无法获取 TLS ClientHello 数据。

**修复**：添加 Telegram IP 段到 `sniffer.skip-addr`：
- `91.108.0.0/16`
- `149.154.160.0/20`

此配置仅影响 Sniffer 的域名嗅探行为，不影响 Telegram 的路由和代理。

### 3. 健康检查优化

- proxy-providers 健康检查间隔从 600s 降至 300s
- 全局选择 fallback 间隔从 600s 降至 300s
- URLTest 组已有 tolerance: 20 + max-failed-times: 1

### 4. 日志轮转

新增 logrotate 配置：每日轮转，保留 7 天，超过 50MB 立即轮转。

### 5. 定时维护

- **每天 03:20**：同步远程配置 → 更新 proxy-providers → 重启 mihomo 服务，一次完成
- 维护脚本会自动备份旧配置（保留最近 3 份）

### 6. systemd 服务加固

- `Restart=always` + `RestartSec=5` — 异常退出自动重启
- `StartLimitBurst=5` + `StartLimitIntervalSec=300` — 5 分钟内最多重启 5 次
- `ProtectSystem=strict` — 限制文件系统写入范围
- `PrivateTmp=true` — 使用独立临时目录
- `ProtectHome=true` — 禁止访问用户主目录

## 管理面板

- URL: `http://10.0.1.2:9090/ui`
- 密码: `rain8240`

### API 常用操作

```bash
# 查看所有代理组
curl -H "Authorization: Bearer rain8240" http://10.0.1.2:9090/proxies

# 手动更新订阅节点
curl -X PUT -H "Authorization: Bearer rain8240" http://10.0.1.2:9090/providers/proxies/Airport_01

# 手动更新规则集
curl -X PUT -H "Authorization: Bearer rain8240" http://10.0.1.2:9090/providers/rules/telegram_domain

# 热重载配置（不重启）
curl -X PUT -H "Authorization: Bearer rain8240" -H "Content-Type: application/json" \
  -d '{"path":"/etc/mihomo/config.yaml"}' 'http://10.0.1.2:9090/configs?force=true'

# 切换节点（示例：节点选择 → 新加坡自动）
curl -X PUT -H "Authorization: Bearer rain8240" -H "Content-Type: application/json" \
  -d '{"name":"新加坡自动"}' http://10.0.1.2:9090/proxies/节点选择
```

## 部署/更新流程

### 首次部署

```bash
# 1. 复制配置文件
scp config.yaml nas:/etc/mihomo/config.yaml

# 2. 安装 systemd 服务
scp mihomo.service nas:/etc/systemd/system/
ssh nas "systemctl daemon-reload && systemctl enable mihomo"

# 3. 安装维护脚本
scp mihomo-maintenance.sh nas:/usr/local/bin/
ssh nas "chmod +x /usr/local/bin/mihomo-maintenance.sh"

# 4. 安装日志轮转
scp mihomo-logrotate nas:/etc/logrotate.d/mihomo

# 5. 安装定时任务
ssh nas "crontab -l 2>/dev/null; cat mihomo-crontab | crontab -"

# 6. 启动服务
ssh nas "systemctl restart mihomo"

# 7. 验证
ssh nas "systemctl status mihomo"
```

### 日常更新配置

1. 本地修改 `config.yaml`
2. Git 提交并推送到仓库
3. 等待次日 03:20 自动同步重启，或手动触发：
   ```bash
   ssh nas "/usr/local/bin/mihomo-maintenance.sh"
   ```
4. 也可以直接复制并热重载（立即生效，会短暂中断）：
   ```bash
   scp config.yaml nas:/etc/mihomo/config.yaml
   ssh nas "curl -s -X PUT -H 'Authorization: Bearer rain8240' -H 'Content-Type: application/json' -d '{\"path\":\"/etc/mihomo/config.yaml\"}' 'http://127.0.0.1:9090/configs?force=true'"
   ```

## 故障排查

### 检查服务状态
```bash
ssh nas "systemctl status mihomo"
```

### 查看实时日志
```bash
ssh nas "journalctl -u mihomo -f"
```

### 检查代理连通性
```bash
curl -x http://10.0.1.2:7890 -s -o /dev/null -w '%{http_code}' https://www.google.com
# 预期: 200
```

### 检查出口 IP
```bash
curl -x http://10.0.1.2:7890 -s https://ipinfo.io/json
```

### 重启服务
```bash
ssh nas "systemctl restart mihomo"
```
