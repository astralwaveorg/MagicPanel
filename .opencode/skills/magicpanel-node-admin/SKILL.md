---
name: MagicPanel 自建节点管理
description: 在 MagicPanel 生产环境新增、更新、删除、查询自建节点（VLESS Reality、Hysteria2、SS、Trojan），从 vless:// 链接或 Clash YAML 自动解析，自动命名、挂策略组、导快照、构建发布并核对产物。用户说“加节点、删节点、改节点、查节点、把这个链接加到面板”时使用。
---

# MagicPanel 自建节点管理

日常操作优先用已安装的 `mpnode`（源码在仓库 `scripts/node_admin.py`）。它同时包含宿主层和容器层：
宿主层负责中文交互、SSH 到 NAS、改前/改后快照；容器层复用面板的 router/service 写库，维护
`node_catalog` 与策略组成员投影。

## 何时用

- 用户给出 `vless://...` / `hysteria2://...` / `ss://...` / `trojan://...` 或 Clash `proxies:` 片段，要求加进面板。
- 用户要换某个自建节点的 UUID / 密钥 / 端口。
- 用户要删除或停用自建节点、查看节点、测速、补发构建。
- 用户问“这个节点加一下”“这个节点不要了”“帮我测一下某节点”。

## 首选：交互式

```bash
mpnode
```

菜单：新增 / 更新 / 删除 / 查看 / 测速 / 发布。新增时会先跑一次 dry-run 展示计划，再询问地区、
名称、位置和是否发布；确认后才写库。

## 非交互

```bash
mpnode add "vless://uuid@1.2.3.4:443?security=reality&sni=...&pbk=...&sid=..."
mpnode add --link ./node.yaml --region US --dry-run
mpnode update "vless://..."                  # 按链接里的 server:port 匹配
mpnode update "vless://..." --name "🇺🇸 美国自建 05" --rename "🇺🇸 美国自建 05"
mpnode delete --name "🇺🇸 美国自建 07" --force
mpnode list --region US
mpnode test --name "🇺🇸 美国自建 05"
mpnode publish --note "手工补发"
```

常用开关：

- `--dry-run`：只解析并展示计划，不写库、不建构建。
- `--no-publish`：只改数据，不构建发布。
- `--region US|JP|SG|HK|TW|KR|GB|DE`：跳过 ip-api 自动识别。
- `--name`：指定名称；不传则按 `🇺🇸 美国自建 NN` 自动编号。
- `--position end|start|after:节点名|before:节点名`：默认追加到组末尾，不改既有优先级。
- `--group`：指定策略组；`none` 表示不加组。

## 脚本固定行为

1. 同名 `server:port` 已存在时，`add` 自动按更新处理，不重复建节点。
2. 默认节点类型「机房」，产物标识为 `名称 (机房)`。
3. 默认加入对应地区自建组（US→`🇺🇸 US自建`，JP→`🇯🇵 JP自建`，SG→`🇸🇬 SG自建`）。
4. `add/update/delete` 非 dry-run 时，自动在 NAS 的 `/opt/magicpanel/policy/snapshots` 导改前/改后快照。
5. 默认走完整发布：创建构建 → 校验全部产物 → 发布测试 → 发布生产 → 用真实设备令牌核对 Stash 与 Mihomo 订阅。
6. `delete` 必须带 `--force` 才会从策略组解绑；交互式会二次确认。

## 约定与边界

- 只改 `/etc` 之外的面板数据；不直接 `UPDATE local_nodes`，必须走脚本，否则 `node_catalog` 会漏同步。
- 快照不导出 `local_nodes`（凭据），不要手工把节点凭据写进仓库。
- 不自动 `git commit`。需要入库时再提交 `policy/snapshots/` 与文档。
- 生产发布后如果产物核对失败，先看构建 `results` 与设备 token 是否有 `env=production` 的设备。

## Clash Verge 与其他客户端

- 面板按设备目标渲染：Stash 设备给 Stash 产物，Mihomo 设备给 Mihomo 产物。
- **Clash Verge 必须用 Mihomo 设备的订阅地址**（如 `Astral-Windows-Mihomo`）。Stash 产物里
  Hysteria2 是 `auth:`，Mihomo 需要 `password:`；Reality 节点还缺 `support-x25519mlkem768`，
  在 Clash Verge 里会表现为超时。
- 判断方法：看订阅 YAML 里 Hy2 节点是 `password:` 还是 `auth:`。

## 自检

```bash
.venv/bin/python -m pytest server/tests/test_node_admin.py -q
```

完整后端测试改动前跑 `cd server && ../.venv/bin/python -m pytest tests -q`。
