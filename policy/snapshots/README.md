# 策略快照

快照包含部署的规则、来源元数据和组顺序。即使剔除了节点凭据，也不宜作为公开示例。本目录的历史 JSON 暂保留：有旧版重建脚本按固定路径读取其中的输入。新的生产快照保存在仓库外；如需测试，用合成数据。

## 快照包含什么

| 表 | 内容 |
| --- | --- |
| `variants` | 方案定义（schema 2） |
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
  --out "$BACKUP_DIR/policy-before.json"
```

先将 `BACKUP_DIR` 指向有备份的私有目录。导出后核对 `digest` 与行数，将文件保存在仓库外。

## 导入（复现）

```sh
# 先干跑，确认 digest 与条数
python scripts/import_policy.py --db /opt/magicpanel/data/magicpanel.db \
  --in "$BACKUP_DIR/policy-before.json" --dry-run

# 正式导入（会自动备份数据库为 <db>.before-import-<时间戳>）
python scripts/import_policy.py --db /opt/magicpanel/data/magicpanel.db \
  --in "$BACKUP_DIR/policy-before.json"

# 重新构建并发布，路由器才会拿到新配置
docker exec magicpanel python -c \
  "from app.routers import builds; print(builds.create_build('import', note='导入策略快照'))"
```

导入按快照版本与非空表替换策略数据，不是增量合并；**不会**改动节点来源与设备令牌。

## 顺序约束（改规则前必读）

构建器会强制校验以下不变量，违反则构建失败（见 `server/app/compiler/validate.py`）：

- 尾部直连块固定为 `cn → cn-ip → direct → private-ip → MATCH`；
- IP 类规则必须排在全部域名规则之后（否则 fake-ip 会直连黑洞，约束 33）；
- 子集合必须先于父集合：`steam-cn < cn`、`apple-cn < apple`、`microsoft-cn < microsoft`、
  `games-cn < games`、`ai-cn < openai/anthropic/category-ai-chat-!cn`；
- 云厂商兜底集合（aws/azure/cloudflare/…）必须排在 `cn` 之前。
