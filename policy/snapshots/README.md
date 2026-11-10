# 策略快照

这里存放**线上策略的无凭据快照**，用于复现、回溯和灾后重建。
策略本体在 MagicPanel 的 `data/magicpanel.db`（`rules` / `proxy_groups` / `rule_providers` 三张表），
不在代码里；把快照入库是为了让「改了哪些规则、顺序怎么排」可以版本化审阅。

## 快照包含什么

| 表 | 内容 |
| --- | --- |
| `rules` | 分流规则，含 `sort`（顺序即优先级） |
| `proxy_groups` | 策略组，含类型、成员顺序、`local_first` 等 |
| `rule_providers` | 规则来源元数据（列白名单） |

**不包含**：`sources`（订阅地址含令牌）、`local_nodes`（节点凭据）、`devices`（设备令牌），
以及 `rule_providers.content`（MRS 二进制缓存，可重新下载）和 `rule_providers.proxy_url_enc`（加密订阅地址）。

## 导出

在能访问数据库的机器上执行（容器内路径为 `/app/data/magicpanel.db`）：

```sh
python scripts/export_policy.py \
  --db /opt/magicpanel/data/magicpanel.db \
  --out policy/snapshots/$(date +%F).json
```

导出后检查 `digest` 与条数，再提交。

## 导入（复现）

```sh
# 先干跑，确认 digest 与条数
python scripts/import_policy.py --db /opt/magicpanel/data/magicpanel.db \
  --in policy/snapshots/2026-11-10.json --dry-run

# 正式导入（会自动备份数据库为 <db>.before-import-<时间戳>）
python scripts/import_policy.py --db /opt/magicpanel/data/magicpanel.db \
  --in policy/snapshots/2026-11-10.json

# 重新构建并发布，路由器才会拿到新配置
docker exec magicpanel python -c \
  "from app.routers import builds; print(builds.create_build('import', note='导入策略快照'))"
```

导入只替换三张策略表，**不会**改动节点来源与设备令牌。

## 顺序约束（改规则前必读）

构建器会强制校验以下不变量，违反则构建失败（见 `server/app/compiler/validate.py`）：

- 尾部直连块固定为 `cn → cn-ip → direct → private-ip → MATCH`；
- IP 类规则必须排在全部域名规则之后（否则 fake-ip 会直连黑洞，约束 33）；
- 子集合必须先于父集合：`steam-cn < cn`、`apple-cn < apple`、`microsoft-cn < microsoft`、
  `games-cn < games`、`ai-cn < openai/anthropic/category-ai-chat-!cn`；
- 云厂商兜底集合（aws/azure/cloudflare/…）必须排在 `cn` 之前。
