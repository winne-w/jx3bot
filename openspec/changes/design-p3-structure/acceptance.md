# P3 结构拆分与基础设施统一验收记录（acceptance.md）

日期：2026-11-26  
分支：`refactor/design-p3-structure`

## 验收结果
- [x] `src/infra/managed_task.py`（`LoopLocal`、`supervise_forever`、`ManagedBackgroundTask`）统一 3 个后台运行时模块的监督循环与事件循环锁管理。
- [x] `src/infra/http_client.py` 启用进程级共享 `httpx.AsyncClient` 连接池并在 `bot.py` shutdown 钩子统一关闭，同时保持对测试打桩 `httpx.AsyncClient` 的 100% 兼容。
- [x] `src/infra/tuilan_errors.py` 提供结构化 `TuilanAuthError`，`jjc_match_data_sync.py` 优先按异常类型识别鉴权错误。
- [x] `src/services/jx3/jjc_ranking_stats_query.py` 承接峰值心法统计与查询辅助逻辑，剥离路由层重复业务代码；`match_detail_persistence.py` 合并三段重复阶段捕获为统一 `_run_projection_stage`；新增统一投影重建入口 `scripts/rebuild_jjc_projections.py`。
- [x] `src/infra/runtime_config.py` 收敛单一 `ConfigSpec` 注册表（补齐 `JJC_KUNGFU_*`）；`config_manager.restart_bot` 移除 `shell=True` 与强制 `os._exit(0)` 改为优雅退出；`status_monitor/commands.py` 合并 6 个重复推送开关并修复 `xwtoggle_cmd` 重名覆盖；`wanbaolou/alias.py` 全部 33 处 `print()` 替换为 `logger`。
- [x] Python 3.9 与 Python 3.13 跨阶段（P0~P3）联合回归测试全部通过，未触碰 `feat/unify-visual-style` 在途修改文件。
