# Mihomo 从零部署指南（AI 可执行版）

> 本文档供 AI Agent 或运维人员使用，可在任何 Linux 系统上从零部署完整的 Mihomo 透明代理网关。
> 适配：Debian/Ubuntu、CentOS/RHEL、Alpine、OpenWrt、树莓派等。

## 1. 前置条件

### 1.1 硬件要求

| 项目 | 最低要求 | 推荐 |
|------|----------|------|
| CPU | 1核 ARM/x86 | 2核+ |
| 内存 | 128MB | 512MB+ |
| 存储 | 50MB | 1GB+ |
| 网络 | 有线以太网 | 千兆以太网 |

### 1.2 系统要求

- Linux 内核 >= 4.9（TPROXY 透明代理需要）
- systemd 或 OpenRC 或直接进程管理
- root 或 sudo 权限
- 网络连通性（至少能访问国内网络）

### 1.3 需要准备的信息

```
# 必填
MIHOMO_SECRET="<API 密码，自定义>"          # 管理面板和 API 的认证密码
PROXY_PROVIDER_URL="<机场订阅链接>"          # 至少一个代理订阅 URL

# 可选
ADDITIONAL_PROVIDER_URL_2="<第二个机场链接>"  # 备用机场
ADDITIONAL_PROVIDER_URL_3="<第三个机场链接>"  # 备用机场
CONFIG_REMOTE_URL="<远程配置文件 URL>"       # 用于自动同步配置
```

## 2. 安装 Mihomo 二进制

### 2.1 检测架构并下载

```bash
# 检测系统架构
ARCH=$(uname -m)
case ${ARCH} in
  x86_64)  PLAT="linux-amd64" ;;
  aarch64) PLAT="linux-arm64" ;;
  armv7l)  PLAT="linux-armv7" ;;
  armv6l)  PLAT="linux-armv6" ;;
  mips)    PLAT="linux-mipsle" ;;
  *)       echo "Unsupported: ${ARCH}"; exit 1 ;;
esac

# 获取最新版本号
VERSION=$(curl -sL https://github.com/MetaCubeX/mihomo/releases/latest | grep -oP 'tag/\K[^"]+' | head -1)
if [ -z "${VERSION}" ]; then
  VERSION="v1.19.24"  # fallback
fi

echo "Architecture: ${ARCH}, Platform: ${PLAT}, Version: ${VERSION}"

# 下载（如果 GitHub 不可达，使用镜像）
DOWNLOAD_URL="https://github.com/MetaCubeX/mihomo/releases/download/${VERSION}/mihomo-${PLAT}-${VERSION}.gz"
GITHUB_MIRROR="https://ghfast.top"

# 先尝试直连，失败则用镜像
curl -sL -o /tmp/mihomo.gz "${DOWNLOAD_URL}" --connect-timeout 10 --max-time 60 || \
curl -sL -o /tmp/mihomo.gz "${GITHUB_MIRROR}/${DOWNLOAD_URL}" --connect-timeout 10 --max-time 60

# 解压并安装
gunzip /tmp/mihomo.gz
chmod +x /tmp/mihomo
mv /tmp/mihomo /usr/local/bin/mihomo
mihomo -v
```

### 2.2 验证安装

```bash
/usr/local/bin/mihomo -v
# 预期输出: Mihomo Meta vX.X.X linux <arch> ...
```

## 3. 创建目录和配置

### 3.1 创建运行目录

```bash
mkdir -p /etc/mihomo/{providers,rules,logs}
```

### 3.2 生成配置文件

以下命令生成完整的 `config.yaml`。**将变量替换为实际值后执行**。

```bash
cat > /etc/mihomo/config.yaml << 'CONFIGEOF'
# ====================================
# Mihomo 配置 - Linux 透明代理网关
# 适用地区：中国大陆
# ====================================

mode: rule
log-level: warning
log-file: /etc/mihomo/logs/mihomo.log
mixed-port: 7890
port: 7891
socks-port: 7892
redir-port: 7893
tproxy-port: 7894
bind-address: "*"
allow-lan: true
ipv6: true
unified-delay: true
tcp-concurrent: true
secret: MIHOMO_SECRET
external-controller: 0.0.0.0:9090
external-ui: .
find-process-mode: 'off'
keep-alive-idle: 600
keep-alive-interval: 30
skip-auth-prefixes:
  - 127.0.0.1/8
  - ::1/128
profile:
  store-selected: true
  store-fake-ip: false

geodata-mode: false
geodata-loader: standard
geo-auto-update: true
geo-update-interval: 48
geox-url:
  geosite: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat
  mmdb: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip-lite.metadb
  geoip: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip-lite.dat
  asn: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/GeoLite2-ASN.mmdb

sniffer:
  enable: true
  sniff:
    HTTP:
      ports: [80, 8080-8880]
      override-destination: true
    TLS:
      ports: [443, 8443]
    QUIC:
      ports: [443, 8443]
  skip-domain:
    - Mijia Cloud
    - dlg.io.mi.com
    - '*.push.apple.com'
    - '*.apple.com'
    - '*.wechat.com'
    - '*.qpic.cn'
    - '*.qq.com'
    - '*.wechatapp.com'
    - '*.vivox.com'
    - '*.oray.com'
    - '*.sunlogin.net'
  skip-addr:
    - 91.108.0.0/16
    - 149.154.160.0/20

tun:
  enable: false

dns:
  enable: true
  listen: 0.0.0.0:1053
  ipv6: true
  respect-rules: true
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  fake-ip-range6: 2001:480:abcd::1/64
  fake-ip-filter-mode: blacklist
  fake-ip-filter:
    - rule-set:fakeip_filter_domain,cn_domain
  default-nameserver:
    - 223.5.5.5
    - 119.29.29.29
  proxy-server-nameserver:
    - https://doh.pub/dns-query
    - https://223.5.5.5/dns-query#h3=true
  direct-nameserver:
    - https://doh.pub/dns-query
    - https://223.5.5.5/dns-query#h3=true
  nameserver:
    - https://223.5.5.5/dns-query
    - https://1.12.12.12/dns-query
  fallback:
    - https://dns.google/dns-query
    - https://cloudflare-dns.com/dns-query
  fallback-filter:
    geoip: true
    geoip-code: CN
  nameserver-policy:
    "geosite:gfw":
      - https://dns.google/dns-query
      - https://cloudflare-dns.com/dns-query

proxies: []

proxy-providers:
  Airport_01:
    type: http
    interval: 86400
    path: ./providers/Airport_01.yaml
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300
    filter: ^(?!.*(拒绝|直连|群|邀请|返利|循环|官网|客服|网站|网址|获取|订阅|流量|到期|机场|下次|版本|官址|备用|过期|已用|联系|邮箱|工单|贩卖|通知|倒卖|防止|国内|地址|频道|无法|说明|提示|特别|访问|支持|教程|关注|更新|作者|加入|USE|USED|TOTAL|EXPIRE|EMAIL|Panel|Channel|Author|traffic))
    proxy: DIRECT
    url: PROXY_PROVIDER_URL
    override:
      additional-prefix: '[机场1]'
      skip-cert-verify: true
      udp: true

proxy-groups:
  - name: 节点选择
    type: select
    proxies:
      - 自动选择
      - DIRECT
  - name: 自动选择
    type: url-test
    include-all: true
    interval: 300
    tolerance: 20
    lazy: true
    max-failed-times: 1
    filter: ^(?!.*(0倍|0\.1倍|traffic|plus))
  - name: 漏网之鱼
    type: fallback
    proxies:
      - 节点选择
      - 自动选择
      - DIRECT
    interval: 300

rules:
  - DOMAIN-SUFFIX,local,DIRECT
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,198.18.0.0/15,DIRECT,no-resolve
  - GEOIP,CN,DIRECT
  - MATCH,漏网之鱼
CONFIGEOF
```

### 3.3 替换配置中的变量

```bash
# 替换密码
sed -i "s/MIHOMO_SECRET/${MIHOMO_SECRET}/g" /etc/mihomo/config.yaml

# 替换订阅链接
sed -i "s|PROXY_PROVIDER_URL|${PROXY_PROVIDER_URL}|g" /etc/mihomo/config.yaml
```

### 3.4 添加完整规则集（可选但推荐）

如果有 GitHub 访问能力（通过代理），可以从完整配置中复制 `rule-providers` 和 `rules` 部分。

完整的规则集配置约 97 个 rule-providers、144 条分流规则，来源于：
- `https://github.com/MetaCubeX/meta-rules-dat` — 官方 GeoSite/GeoIP 规则
- `https://github.com/Lanlan13-14/Rules` — 社区补充规则

**关键**：每个 rule-provider 必须包含 `proxy: "节点选择"` 才能在国内通过代理下载。

## 4. 安装管理面板（可选）

```bash
cd /etc/mihomo
# 下载 Yacd 面板
curl -sL https://github.com/MetaCubeX/Yacd-meta/archive/gh-pages.zip -o ui.zip
unzip ui.zip -d ui_tmp
mv ui_tmp/Yacd-meta-gh-pages/* . 2>/dev/null
rm -rf ui_tmp ui.zip
```

## 5. 配置 systemd 服务

### 5.1 创建服务文件

```bash
cat > /etc/systemd/system/mihomo.service << 'EOF'
[Unit]
Description=mihomo Daemon, Another Clash Kernel.
Documentation=https://wiki.metacubex.one/
After=network.target NetworkManager.service systemd-networkd.service iwd.service
Wants=network-online.target

[Service]
Type=simple
LimitNPROC=500
LimitNOFILE=1000000
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_TIME CAP_SYS_PTRACE CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_TIME CAP_SYS_PTRACE CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE
Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=300
ExecStartPre=/usr/bin/sleep 1s
ExecStart=/usr/local/bin/mihomo -d /etc/mihomo
ExecReload=/bin/kill -HUP $MAINPID

NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/etc/mihomo
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF
```

### 5.2 启用并启动

```bash
systemctl daemon-reload
systemctl enable mihomo
systemctl start mihomo
systemctl status mihomo
```

## 6. 配置日志轮转

```bash
cat > /etc/logrotate.d/mihomo << 'EOF'
/etc/mihomo/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 50M
}
EOF
```

## 7. 配置定时维护

### 7.1 创建维护脚本

```bash
cat > /usr/local/bin/mihomo-maintenance.sh << 'MAINEOF'
#!/bin/bash
MIHOMO_DIR="/etc/mihomo"
API="http://127.0.0.1:9090"
SECRET="${MIHOMO_SECRET:-changeme}"
AUTH_HEADER="Authorization: Bearer ${SECRET}"
LOG="${MIHOMO_DIR}/logs/maintenance.log"
LOCAL_CONFIG="${MIHOMO_DIR}/config.yaml"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "${LOG}"; }

log "=== Daily maintenance start ==="

# 远程配置同步（如果设置了远程 URL）
if [ -n "${CONFIG_REMOTE_URL}" ]; then
    HTTP_CODE=$(curl -s -o /tmp/mihomo_remote.yaml -w '%{http_code}' \
        --connect-timeout 10 --max-time 30 "${CONFIG_REMOTE_URL}" 2>/dev/null)
    if [ "${HTTP_CODE}" = "200" ]; then
        REMOTE_MD5=$(md5sum /tmp/mihomo_remote.yaml 2>/dev/null | cut -d' ' -f1)
        LOCAL_MD5=$(md5sum "${LOCAL_CONFIG}" 2>/dev/null | cut -d' ' -f1)
        if [ "${REMOTE_MD5}" != "${LOCAL_MD5}" ]; then
            cp "${LOCAL_CONFIG}" "${LOCAL_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
            cp /tmp/mihomo_remote.yaml "${LOCAL_CONFIG}"
            log "OK: config synced from remote"
        fi
    fi
fi

# 重启服务
systemctl restart mihomo
sleep 5

if systemctl is-active --quiet mihomo; then
    log "OK: mihomo restarted"
else
    log "FATAL: mihomo failed to restart"
    exit 1
fi

# 更新 proxy-providers
for provider in $(curl -s -H "${AUTH_HEADER}" "${API}/providers/proxies" 2>/dev/null | \
    python3 -c "import sys,json; [print(n) for n in json.load(sys.stdin).get('providers',{})]" 2>/dev/null); do
    curl -s -X PUT -H "${AUTH_HEADER}" "${API}/providers/proxies/${provider}" >/dev/null 2>&1
done
log "OK: providers updated"

# 清理旧备份
ls -t "${MIHOMO_DIR}"/config.yaml.bak.* 2>/dev/null | tail -n +4 | xargs -r rm -f
log "=== Daily maintenance done ==="
MAINEOF

chmod +x /usr/local/bin/mihomo-maintenance.sh
```

### 7.2 添加定时任务

```bash
# 每天凌晨 03:20 执行维护
(crontab -l 2>/dev/null; echo "20 3 * * * /usr/local/bin/mihomo-maintenance.sh >/dev/null 2>&1") | crontab -
```

## 8. 透明代理配置（网关模式）

如果 Mihomo 作为局域网网关，需要配置 iptables 将客户端流量转发到 Mihomo。

### 8.1 透明代理脚本

```bash
cat > /usr/local/bin/mihomo-iptables.sh << 'IPEOF'
#!/bin/bash
# Mihomo 透明代理 iptables 规则
# 适用于 TPROXY 模式

MIHOMO_IP="127.0.0.1"
REDIR_PORT=7893
TPROXY_PORT=7894
DNS_PORT=1053

# 局域网网段（根据实际修改）
LAN_RANGE="10.0.0.0/8"

enable() {
    # 开启内核转发
    sysctl -w net.ipv4.ip_forward=1
    sysctl -w net.ipv6.conf.all.forwarding=1

    # 新建链
    iptables -t mangle -N MIHOMO 2>/dev/null || true
    iptables -t mangle -F MIHOMO

    # 排除本机和局域网直连
    iptables -t mangle -A MIHOMO -d 0.0.0.0/8 -j RETURN
    iptables -t mangle -A MIHOMO -d 10.0.0.0/8 -j RETURN
    iptables -t mangle -A MIHOMO -d 100.64.0.0/10 -j RETURN
    iptables -t mangle -A MIHOMO -d 127.0.0.0/8 -j RETURN
    iptables -t mangle -A MIHOMO -d 169.254.0.0/16 -j RETURN
    iptables -t mangle -A MIHOMO -d 172.16.0.0/12 -j RETURN
    iptables -t mangle -A MIHOMO -d 192.168.0.0/16 -j RETURN
    iptables -t mangle -A MIHOMO -d 224.0.0.0/4 -j RETURN
    iptables -t mangle -A MIHOMO -d 240.0.0.0/4 -j RETURN

    # TCP -> TPROXY
    iptables -t mangle -A MIHOMO -p tcp -j TPROXY --on-port ${TPROXY_PORT} --tproxy-mark 0x1/0x1
    # UDP -> TPROXY
    iptables -t mangle -A MIHOMO -p udp -j TPROXY --on-port ${TPROXY_PORT} --tproxy-mark 0x1/0x1

    # 应用链
    iptables -t mangle -A PREROUTING -j MIHOMO

    # 策略路由
    ip rule add fwmark 0x1 table 100 2>/dev/null || true
    ip route add local default dev lo table 100 2>/dev/null || true

    # DNS 重定向（将客户端 DNS 请求转发到 Mihomo DNS）
    iptables -t nat -N MIHOMO_DNS 2>/dev/null || true
    iptables -t nat -F MIHOMO_DNS
    iptables -t nat -A MIHOMO_DNS -p udp --dport 53 -j REDIRECT --to-ports ${DNS_PORT}
    iptables -t nat -A MIHOMO_DNS -p tcp --dport 53 -j REDIRECT --to-ports ${DNS_PORT}
    iptables -t nat -A PREROUTING -j MIHOMO_DNS

    echo "Mihomo transparent proxy enabled"
}

disable() {
    iptables -t mangle -D PREROUTING -j MIHOMO 2>/dev/null
    iptables -t mangle -F MIHOMO 2>/dev/null
    iptables -t mangle -X MIHOMO 2>/dev/null
    iptables -t nat -D PREROUTING -j MIHOMO_DNS 2>/dev/null
    iptables -t nat -F MIHOMO_DNS 2>/dev/null
    iptables -t nat -X MIHOMO_DNS 2>/dev/null
    ip rule del fwmark 0x1 table 100 2>/dev/null
    ip route del local default dev lo table 100 2>/dev/null
    echo "Mihomo transparent proxy disabled"
}

case "$1" in
    enable)  enable ;;
    disable) disable ;;
    *)       echo "Usage: $0 {enable|disable}" ;;
esac
IPEOF

chmod +x /usr/local/bin/mihomo-iptables.sh
```

### 8.2 开机自动启用透明代理

```bash
# 在 mihomo.service 的 [Service] 段添加
sed -i '/ExecStart=/a ExecStartPost=/usr/local/bin/mihomo-iptables.sh enable' /etc/systemd/system/mihomo.service
echo 'ExecStop=/usr/local/bin/mihomo-iptables.sh disable' >> /etc/systemd/system/mihomo.service
# 注意：需要追加到 [Service] 段，不是 [Install] 段
systemctl daemon-reload
```

### 8.3 配置客户端网关

将局域网客户端的网关和 DNS 指向 Mihomo 服务器：

```
# 客户端网络配置
网关: <Mihomo 服务器 IP>
DNS:  <Mihomo 服务器 IP>（或由 DHCP 自动下发）
```

DHCP 自动下发（在路由器或 dnsmasq 中配置）：
```
# dnsmasq.conf
dhcp-option=option:router,<Mihomo IP>
dhcp-option=option:dns-server,<Mihomo IP>
```

## 9. OpenWrt 特殊配置

OpenWrt 使用 procd 而非 systemd，配置方式不同。

### 9.1 安装

```bash
# 通过 opkg 安装（如果有源）
opkg update
opkg install mihomo

# 或手动安装
ARCH=$(opkg print-architecture | awk 'NR==1{print $2}')
curl -sL "https://github.com/MetaCubeX/mihomo/releases/latest/download/mihomo-linux-${ARCH}.gz" | gunzip > /usr/bin/mihomo
chmod +x /usr/bin/mihomo
```

### 9.2 init.d 服务

```bash
cat > /etc/init.d/mihomo << 'OEOF'
#!/bin/sh /etc/rc.common
USE_PROCD=1
START=99
STOP=10

PROG=/usr/bin/mihomo
CONF_DIR=/etc/mihomo

start_service() {
    procd_open_instance mihomo
    procd_set_param command ${PROG} -d ${CONF_DIR}
    procd_set_param respawn 3600 5 5
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_set_param pidfile /var/run/mihomo.pid
    procd_close_instance
}

stop_service() {
    killall mihomo 2>/dev/null
}
OEOF

chmod +x /etc/init.d/mihomo
/etc/init.d/mihomo enable
/etc/init.d/mihomo start
```

### 9.3 OpenWrt 防火墙规则

```bash
# /etc/firewall.user
iptables -t mangle -N MIHOMO 2>/dev/null
iptables -t mangle -F MIHOMO
iptables -t mangle -A MIHOMO -d 0.0.0.0/8 -j RETURN
iptables -t mangle -A MIHOMO -d 10.0.0.0/8 -j RETURN
iptables -t mangle -A MIHOMO -d 127.0.0.0/8 -j RETURN
iptables -t mangle -A MIHOMO -d 169.254.0.0/16 -j RETURN
iptables -t mangle -A MIHOMO -d 172.16.0.0/12 -j RETURN
iptables -t mangle -A MIHOMO -d 192.168.0.0/16 -j RETURN
iptables -t mangle -A MIHOMO -d 224.0.0.0/4 -j RETURN
iptables -t mangle -A MIHOMO -d 240.0.0.0/4 -j RETURN
iptables -t mangle -A MIHOMO -p tcp -j TPROXY --on-port 7894 --tproxy-mark 0x1/0x1
iptables -t mangle -A MIHOMO -p udp -j TPROXY --on-port 7894 --tproxy-mark 0x1/0x1
iptables -t mangle -A PREROUTING -j MIHOMO
iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 1053
iptables -t nat -A PREROUTING -p tcp --dport 53 -j REDIRECT --to-ports 1053
ip rule add fwmark 0x1 table 100
ip route add local default dev lo table 100
```

## 10. 验证清单

部署完成后，按以下清单逐项验证：

```bash
# 1. 二进制版本
mihomo -v

# 2. 服务状态
systemctl status mihomo  # 或 /etc/init.d/mihomo status

# 3. 端口监听
ss -tlnp | grep mihomo
# 预期: 7890, 7891, 7892, 7893, 7894, 9090, 1053

# 4. API 可用性
curl -s -H "Authorization: Bearer ${MIHOMO_SECRET}" http://127.0.0.1:9090/version

# 5. 代理连通性
curl -s -o /dev/null -w '%{http_code}' -x http://127.0.0.1:7890 https://www.google.com
# 预期: 200

# 6. 国内直连
curl -s -o /dev/null -w '%{http_code}' -x http://127.0.0.1:7890 https://www.baidu.com
# 预期: 200

# 7. 检查错误日志（应该为 0）
journalctl -u mihomo --since '10 min ago' --no-pager | grep -c 'level=error'

# 8. rule-providers 加载状态
curl -s -H "Authorization: Bearer ${MIHOMO_SECRET}" http://127.0.0.1:9090/providers/rules | \
  python3 -c "import sys,json; d=json.load(sys.stdin); p=d.get('providers',{}); ok=sum(1 for v in p.values() if v.get('ruleCount',0)>0); print(f'{ok}/{len(p)} loaded')"

# 9. 代理组状态
curl -s -H "Authorization: Bearer ${MIHOMO_SECRET}" http://127.0.0.1:9090/proxies | \
  python3 -c "import sys,json; [print(f'{v[\"type\"]:10} {\"OK\" if v.get(\"alive\") else \"FAIL\":5} {k}') for k,v in json.load(sys.stdin).get('proxies',{}).items() if v.get('type') in ('URLTest','Fallback')]"

# 10. 定时任务
crontab -l | grep mihomo

# 11. 日志轮转
logrotate -d /etc/logrotate.d/mihomo 2>&1 | head -5
```

## 11. 常见问题

### Q: rule-providers 全部加载失败
A: 国内无法直连 `raw.githubusercontent.com`。需要为每个 rule-provider 添加 `proxy: "节点选择"`，通过代理下载。确保 proxy-providers 先于 rule-providers 加载。

### Q: Telegram 连接导致大量 Sniffer error
A: Telegram 使用 MTProto 协议，在 sniffer 中添加 `skip-addr: [91.108.0.0/16, 149.154.160.0/20]`。

### Q: DNS 弃用警告 "replace fallback-filter.geosite with nameserver-policy"
A: 将 `fallback-filter.geosite` 迁移到 `dns.nameserver-policy`：
```yaml
dns:
  nameserver-policy:
    "geosite:gfw":
      - https://dns.google/dns-query
```

### Q: 树莓派内存不足
A: 减少代理节点数量、禁用 `tcp-concurrent`、设置 `log-level: error`、降低 `keep-alive-idle`。

### Q: OpenWrt 上 TPROXY 不可用
A: 确保安装了 `kmod-ipt-tproxy`、`iptables-mod-tproxy` 包。或改用 redir 模式（仅 TCP 透明代理）。

### Q: 如何更新 Mihomo
A: 重新下载最新二进制替换 `/usr/local/bin/mihomo`，然后 `systemctl restart mihomo`。

### Q: 如何热重载配置（不重启）
A: `curl -X PUT -H "Authorization: Bearer <secret>" -H "Content-Type: application/json" -d '{"path":"/etc/mihomo/config.yaml"}' 'http://127.0.0.1:9090/configs?force=true'`
