# Mihomo 代理服务 — 外部连接配置速查表

NAS IP: `10.0.1.2` | 面板密码: `rain8240`

## 端口一览

| 端口 | 协议 | 用途 | 适用场景 |
|------|------|------|----------|
| 7890 | HTTP + SOCKS5 混合 | 单端口通用代理 | 浏览器、App 代理设置 |
| 7891 | HTTP | 纯 HTTP 代理 | 部分只支持 HTTP 代理的客户端 |
| 7892 | SOCKS5 | 纯 SOCKS5 代理 | SSH、Git、终端工具 |
| 7893 | HTTP Redirect | 透明代理（iptables redirect） | 路由器/网关转发 |
| 7894 | TProxy | 透明代理（TPROXY） | 路由器/网关转发 |
| 9090 | HTTP RESTful API | 管理面板 + API | 浏览器访问面板 |
| 1053 | DNS | DNS 服务器 | 客户端 DNS 指向 |

## 各设备/场景配置

### 浏览器

手动代理设置：
- HTTP 代理：`10.0.1.2` 端口 `7890`
- SOCKS5 代理：`10.0.1.2` 端口 `7890`

SwitchyOmega 插件：
- 代理协议：`HTTP` 或 `SOCKS5`
- 代理服务器：`10.0.1.2`
- 代理端口：`7890`（混合）或 `7891`（纯 HTTP）或 `7892`（纯 SOCKS5）

### macOS / Windows 系统代理

**macOS：** 系统设置 → 网络 → Wi-Fi → 详细信息 → 代理
- Web 代理 (HTTP)：`10.0.1.2:7890`
- 安全 Web 代理 (HTTPS)：`10.0.1.2:7890`
- SOCKS 代理：`10.0.1.2:7892`

**Windows：** 设置 → 网络和 Internet → 代理 → 手动设置代理
- 地址：`10.0.1.2`
- 端口：`7890`

### 终端命令行

临时设置（当前会话生效）：
```bash
# HTTP 代理
export http_proxy=http://10.0.1.2:7890
export https_proxy=http://10.0.1.2:7890
export all_proxy=socks5://10.0.1.2:7890

# 取消代理
unset http_proxy https_proxy all_proxy
```

写入 shell 配置永久生效（`~/.zshrc` 或 `~/.bashrc`）：
```bash
export http_proxy=http://10.0.1.2:7890
export https_proxy=http://10.0.1.2:7890
export all_proxy=socks5://10.0.1.2:7890
export no_proxy=localhost,127.0.0.1,10.0.0.0/8,192.168.0.0/16,.local
```

### Git

```bash
# HTTP/HTTPS
git config --global http.proxy http://10.0.1.2:7890
git config --global https.proxy http://10.0.1.2:7890

# SSH（需配合 ~/.ssh/config）
# 见下方 SSH 部分
```

### SSH 通过代理

`~/.ssh/config`：
```
Host github.com
  ProxyCommand nc -X 5 -x 10.0.1.2:7890 %h %p
```

### curl / wget

```bash
# curl
curl -x http://10.0.1.2:7890 https://www.google.com
curl -x socks5://10.0.1.2:7890 https://www.google.com

# wget
wget -e http_proxy=http://10.0.1.2:7890 -e https_proxy=http://10.0.1.2:7890 https://www.google.com
```

### iOS / Android

**iOS：** 设置 → Wi-Fi → 点击已连接网络 → 配置代理 → 手动
- 服务器：`10.0.1.2`
- 端口：`7890`（HTTP+SOCKS5 混合端口）或 `7892`（纯 SOCKS5）

**Android：** 设置 → Wi-Fi → 长按网络 → 修改网络 → 高级选项 → 代理 → 手动
- 主机名：`10.0.1.2`
- 端口：`7890`

### Docker

```bash
# 容器运行时指定
docker run -e http_proxy=http://10.0.1.2:7890 -e https_proxy=http://10.0.1.2:7890 ...

# Docker daemon 全局（/etc/docker/daemon.json）
{
  "proxies": {
    "http-proxy": "http://10.0.1.2:7890",
    "https-proxy": "http://10.0.1.2:7890",
    "no-proxy": "localhost,127.0.0.1,10.0.0.0/8"
  }
}
```

### apt / yum（Linux 包管理器）

```bash
# apt（Debian/Ubuntu）
echo 'Acquire::http::Proxy "http://10.0.1.2:7890";' | sudo tee /etc/apt/apt.conf.d/proxy.conf
echo 'Acquire::https::Proxy "http://10.0.1.2:7890";' | sudo tee -a /etc/apt/apt.conf.d/proxy.conf

# yum（CentOS/RHEL）
echo 'proxy=http://10.0.1.2:7890' | sudo tee -a /etc/yum.conf
```

### 管理面板

浏览器访问：
- 地址：`http://10.0.1.2:9090/ui`
- 密码：`rain8240`

API 调用示例：
```bash
# 查看代理组
curl -H "Authorization: Bearer rain8240" http://10.0.1.2:9090/proxies

# 切换节点（示例：节点选择 → 香港自动）
curl -X PUT -H "Authorization: Bearer rain8240" -H "Content-Type: application/json" \
  -d '{"name":"香港自动"}' http://10.0.1.2:9090/proxies/节点选择
```

### DNS 配置

将客户端 DNS 指向 NAS 可获得 fake-ip 加速和防 DNS 污染：
- DNS 服务器：`10.0.1.2`
- 端口：`1053`（非标准端口，需支持自定义端口的客户端）

路由器 DHCP 场景直接下发 `10.0.1.2` 作为主 DNS 即可（标准 53 端口需 iptables 转发）。

## 快速验证

```bash
# 测试代理是否可用
curl -x http://10.0.1.2:7890 -s -o /dev/null -w '%{http_code}' https://www.google.com
# 预期输出: 200

# 测试国内直连
curl -x http://10.0.1.2:7890 -s -o /dev/null -w '%{http_code}' https://www.baidu.com
# 预期输出: 200

# 检查出口 IP
curl -x http://10.0.1.2:7890 -s https://ipinfo.io/json
```
