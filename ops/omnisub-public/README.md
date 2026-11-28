# OmniSub 公共转换站

独立 Compose 栈，供匿名用户把公开 HTTPS 订阅或节点转换成客户端更新地址。所有目标均由固定摘要的 [OmniSub 镜像](https://github.com/astralwaveorg/OmniSub/releases/tag/v1.12.1)生成。它不连接 MagicPanel 的账号、数据库或 NAS 转换器。

上游[快速开始](https://github.com/Aethersailor/SubConverter-Extended/wiki/Getting-Started)通过 `/sub` 转换，`/version` 查看版本，`/inspect` 诊断已有请求。公共首页是单独的转换表单，提供 Mihomo / OpenClash、Stash、Surge 5/6 和 Shadowrocket。Shadowrocket 返回节点订阅。完整配置使用随栈提供的手动选择组，未命中规则时走该组。不会套用 MagicPanel 的运营商规则。

## 安装

1. 将此目录放入独立的 Compose 项目，保留 `Dockerfile`、`public.ini` 和 `www/`。设置 `.env` 的 `PUBLIC_HOST` 为实际域名、`DENY_IPS` 为宿主所有公网地址（以逗号分隔）。网关从外网读取指定的 HTTPS 订阅，校验 DNS 结果、连接到已检查的 IP，并验证原域名的 TLS 证书。只接受 443 端口。转换容器位于不能直接出网的内部网络。
2. 首次安装时，以宿主机管理员身份在项目目录执行以下命令。密钥用于加密更新地址，需要单独备份；丢失或更换后，所有原有链接失效。

   ```sh
   install -d -m 0700 state
   (umask 077; set -C; python3 -c 'import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' > state/link-key) &&
     chown 10001:10001 state/link-key && chmod 0400 state/link-key
   ```

3. 运行 `docker compose config --quiet`、`docker compose up -d --build --wait`。运行中的项目可由 1Panel 通过 Docker Compose 标签识别。网站证书和反向代理另行管理。
4. 为域名配置 HTTPS，反向代理到 `127.0.0.1:47108`。提供的 [OpenResty 示例](openresty.conf.example) 包含限流、图标路径和日志设置；将域名与证书目录占位符替换为实际值，证书路径须在 OpenResty 容器内可见。不要将转换器端口或诊断、上传、管理接口暴露到公网。检验配置后平滑加载。CDN 不应覆盖私有响应的 `Cache-Control: no-store`。
5. 从服务所在主机及外部各运行一次 `python3 tests/smoke.py <站点地址>`。可再传一个托管 [nodes.yaml](tests/nodes.yaml) 的公开 HTTPS 地址，验证服务端下载、字段保留和客户端更新。样例使用保留域名，只验证配置，不代表连通真实代理。

更新前保存上一版本的 Compose、程序、模板、网站配置和密钥。回退时恢复同一密钥和上一版镜像，再运行上述检查。全站停用时先撤下此域名的转发，再停止此栈，无须重启其他容器。

## 地址与已知边界

- 页面使用同站 POST 生成加密的 `/s/…` 地址，不需要数据库。创建时先转换并校验一次；后续每次下载重新读取来源。加密不能防止别人使用泄露的链接。没有单链接撤销或失败缓存。
- 也支持经典 `GET /sub?target=clash&url=…`，可用参数限于 `target`、`url`、`list`（YAML）、`ver`（Surge）。此接口的查询串包含原始来源，日常使用建议从首页生成。页面和转换响应不使用外部脚本或第三方短链。
- 来源文本最多 4200 字节、4 个远程订阅、512 个节点。不支持带远程 proxy-providers 的嵌套订阅、YAML 锚点或自定义远程模板。提交或下载失败时返回错误，不下发半份配置。
- 此版公共入口遇到已识别的固定证书指纹会拒绝转换。Hysteria2 URI 的转义口令暂时需要改用 YAML。交付前检查节点数以及 Hysteria2 服务器、端口和口令；未知的其他协议差异仍需在目标客户端验证。
