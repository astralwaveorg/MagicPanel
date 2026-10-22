# 文档导航

## 怎么用这份文档

| 文档 | 给谁看 | 什么时候看 |
| --- | --- | --- |
| [使用文档](使用文档.md) | 使用者 | 想知道某个页面怎么用、某个按钮点下去会怎样 |
| [开发文档](开发文档.md) | 维护者、Agent | 要改代码：改哪个文件、怎么验证、怎么发上线 |
| [配置文档](配置文档.md) | 维护者、Agent | 要改配置：哪项配置存在哪、字段是什么、去哪改、改完怎么发布 |
| [在线阅读](https://astralwaveorg.github.io/MagicPanel/) | 所有人 | 上面三份的网页版（`gh-pages` 分支，由 `scripts/build_docs_site.sh` 生成） |

## 深入细节

| 文档 | 内容 |
| --- | --- |
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

## 家庭网络方案与运行上下文

这一组记录的是**迁移前**的方案与审阅结论，属于历史材料，不是当前实现。

| 文档 | 用途 |
| --- | --- |
| [运行上下文](network/Network-Operations-Context.md) | 设备清单、访问入口、用户约束、当前事实与目标区别 |
| [总体设计](network/Home-Proxy-Architecture.md) | Stash 选型：Windows + 两台 Mac、家庭路径、云端统一与故障隔离 |
| [客户端选型与兼容性](network/Client-Selection-and-Compatibility.md) | 授权、Stash／Mihomo 差异、完整配置更新与验收 |
| [Mac mini 服务与迁移方案](network/Mac-mini-LAN-Proxy-Plan.md) | 稳定端口、NAS 消费层、手动接入、切换／回退与验收 |
| [R6S 安全稳定性审阅](network/audits/R6S-Security-Stability-Review.md) | 只读检查证据、问题优先级与待审核建议，不是整改记录 |
| [MacBook 代理卸载记录](network/audits/MacBook-Proxy-Cleanup.md) | 本机仅保留 Stash；旧 Surge 扩展已终止，待正常重启删除 |
| [R6S 初次检查](network/audits/R6S-Inspection.md) | 基础系统、插件与网络快照 |

## 归档

`docs/archive/` 存放历史开发文档（已落地的方案与影响面分析），记录的是当时为什么这么做。留在仓库里只会让"当前实现"和"当时的设想"混在一起，该目录已在 `.gitignore` 中。

根目录 [AGENTS.md](../AGENTS.md) 保留简短硬性约束与入口；设备细节放运行上下文，操作设计放方案，检查证据放 audits，官方入口放 reference，避免多份状态相互矛盾。
