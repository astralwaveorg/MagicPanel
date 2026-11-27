# 文档导航

## 哪些内容随代码提交

| 去向 | 内容 | 例子 |
| --- | --- | --- |
| 仓库 | 换个部署仍然适用，或新 checkout 的工具必须读取 | 产品与配置手册、API 清单、安装/回滚方法、官方参考索引、用模拟数据制作的界面示例 |
| 只在本地保存 | 只描述某次实施、某台机器或一个人的网络 | 环境地址表、节点或设备清单、发布回执、排障日志、测速、带实际数据的截图、历史实施计划 |
| 拆开保存 | 一份文档同时有方法和现场证据 | 仓库保留验证步骤、通过条件和占位符；实测数值、原始输出和部署标识进入站外运行手册 |

新文档先按用途分类。`docs/` 和 `studio/docs/` 使用 [.gitignore](../.gitignore) 的文件清单；新增共用手册时把对应路径加进去并从索引链接。不要强制添加私人文件。工作树中的 `docs/local/` 可暂存本地说明，长期原件请备份到仓库外。旧有的 `docs/network/` 和 `docs/archive/` 仍只在本地。真实的密钥、订阅和签名口令不要写进任何手册。

## 怎么用这份文档

| 文档 | 给谁看 | 什么时候看 |
| --- | --- | --- |
| [Agent 交接提示词](reference/Agent-交接提示词.md) | 第一次接手的人或 Agent | 刚 clone 完、换机器、隔了很久再来：架构、心智模型、改配置方式、发布流程 |
| [使用文档](使用文档.md) | 使用者 | 想知道某个页面怎么用、某个按钮点下去会怎样 |
| [开发文档](开发文档.md) | 维护者、Agent | 要改代码：改哪个文件、怎么验证、怎么发上线 |
| [配置文档](配置文档.md) | 维护者、Agent | 要改配置：哪项配置存在哪、字段是什么、去哪改、改完怎么发布 |
| [在线阅读](https://astralwaveorg.github.io/MagicPanel/) | 所有人 | 使用、开发和配置这三份手册的网页版。推 main 后由 `.github/workflows/pages.yml` 自动生成并发布（不需要手动维护分支） |

## 深入细节

| 文档 | 内容 |
| --- | --- |
| [旧版维护约束](development/旧版维护约束.md) | 配置合并、排序、资源保留与发布等旧版约束的编号索引 |
| [开发规格](development/MagicPanel-开发规格.md) | 已实现细节的完整规格：数据模型、编译校验、发布流水线、订阅协议、安全模型 |
| [产物构成](development/MagicPanel-构建与发布-产物构成.md) | 一次构建固化了什么、发布状态如何流转、产物里哪些固定哪些实时 |
| [接口清单与安卓客户端说明](development/接口清单与安卓客户端说明.md) | 全部接口、请求字段与安卓客户端的订阅约定 |
| [部署文档](deployment/1Panel-Docker-部署.md) | 1Panel + Docker 上线步骤、反向代理、备份与升级 |

## 官方参考

| 文档 | 用途 |
| --- | --- |
| [官方文档查阅流程](reference/Official-Docs-Workflow.md) | 修改前必须在线核对、按节读取、版本验证与证据记录 |
| [Stash Wiki 导航](reference/Stash-Wiki-Navigation.md) | 全站主题、中英文页面及常用章节入口 |
| [Mihomo 配置导航](reference/Mihomo-Config-Navigation.md) | 官方配置页与字段定位 |
| [机器检索索引](reference/official-docs-index.json) | 供脚本查询的元数据，无需逐次全文读取 |

在仓库根目录使用查阅工具（只依赖 Python 标准库）：

```sh
python3 scripts/docs_lookup.py search mixed-port --product mihomo
python3 scripts/docs_lookup.py read https://wiki.metacubex.one/config/inbound/port/
```

缓存位于 `.cache/official-docs/`，临时与缓存文件被 Git 忽略；导航、索引、查阅工具属于应提交的维护资源。

## 依赖更新

`.github/dependabot.yml` 每周一自动提 PR：

| 生态 | 范围 | 策略 |
| --- | --- | --- |
| npm | 仓库根目录 | 只更新 lock 文件，**不跨大版本**（跨大版本会牵动构建链，需人工验证） |
| pip | `server/` | 只做补丁与小版本更新 |
| GitHub Actions | — | **不自动升级**，需要时手工改 `.github/workflows/*.yml` |

## 文档站什么时候重建

`.github/workflows/pages.yml` 只在 `docs/**`、`scripts/build_docs_site.py`、`.github/workflows/pages.yml` 变化时触发。
改根目录 `README.md` 或 `AGENTS.md` **不会**触发文档站重建——这两份文件不在站点里。


Studio 的订阅、引擎与部署另见 [Studio 导航](../studio/README.md)。
