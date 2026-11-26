# P3 基础设施统一、路由业务下沉与插件去重（design-p3-structure）

日期：2026-11-26  
分支：`refactor/design-p3-structure`（基于 `refactor/design-p2-data`）  
关联评审：`design_review.md` 阶段 3

## 背景与目标

1. **统一后台任务监督与 HTTP 连接池**：抽取 `src/infra/managed_task.py`（`ManagedBackgroundTask`、`LoopLocal`）统一后台运行时监督；升级 `src/infra/http_client.py` 复用进程级 `httpx.AsyncClient` 连接池并在 `bot.py` shutdown 时关闭；新增结构化 `TuilanAuthError`。
2. **路由业务下沉与持久化管道去重**：将 `src/api/routers/jjc_ranking_stats.py` 中的峰值心法统计与查询编排抽离至 `src/services/jx3/jjc_ranking_stats_query.py`；将 `match_detail_persistence.py` 三段重复 try/except 重构为统一阶段执行循环；新增统一投影重建入口 `scripts/rebuild_jjc_projections.py --stage=fact|participant|identity|all`。
3. **统一运行时配置注册表与插件清理**：新建 `src/infra/runtime_config.py` 收敛 `ConfigSpec` 白名单；修复 `config_manager.py` 重启逻辑（去掉 `shell=True` 与强制 `os._exit(0)` 绕过优雅关闭）；合并 `status_monitor/commands.py` 中 6 份复制粘贴的推送开关；清理 `src/plugins/wanbaolou/alias.py` 中 33 处 `print()` 为结构化日志。
