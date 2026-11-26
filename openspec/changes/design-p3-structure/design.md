# P3 结构拆分与基础设施统一技术方案（design.md）

## 1. `src/infra/managed_task.py` & `src/infra/http_client.py` & `src/infra/tuilan_errors.py`
- `ManagedBackgroundTask`：封装带事件循环安全锁、有界指数退避重启（单轮健康运行满阈值自动重置退避）、取消透传与状态快照的后台协程管理器；`LoopLocal[T]` 消除 3 处重复的按事件循环取锁逻辑。
- `HttpClient`：当 `httpx.AsyncClient` 未被测试 mock 替换时，复用按 `verify` 分桶的进程级长连接 `AsyncClient` 连接池；在 `bot.py` shutdown 钩子中统一调用 `close_shared_async_clients()`；测试打桩 `httpx.AsyncClient` 时自动走桩对象，保持 100% 单测兼容。
- `TuilanAuthError`：结构化鉴权异常，`jjc_match_data_sync.py:_is_auth_error` 优先识别 `isinstance(exc, TuilanAuthError)`，并保持既有字符串分类兼容。

## 2. 路由业务下沉与持久化阶段循环
- `src/services/jx3/jjc_ranking_stats_query.py`：承载 `build_peak_kungfu_statistics` 与峰值/快照查询辅助逻辑，`src/api/routers/jjc_ranking_stats.py` 委托调用并保留原私有别名。
- `src/services/jx3/match_detail_persistence.py`：用统一 `_run_projection_stage` 替代三段重复的 `try/except + _result_error + _log_error` 代码块。
- `scripts/rebuild_jjc_projections.py`：支持 `--stage=fact|participant|identity|all`、`--match-id`、`--limit`、`--dry-run`，复用 `scripts._common.mongo`。

## 3. 配置注册表、优雅重启与插件去重
- `src/infra/runtime_config.py`：单一 `CONFIG_SPECS` 定义表，覆盖全部运行时配置项（含 `JJC_KUNGFU_*`），提供读写、校验与脱敏函数。
- `src/plugins/config_manager.py`：复用 `runtime_config`，`restart_bot` 去除 `shell=True` 与直接 `os._exit(0)`，默认触发优雅退出（交由 Docker `restart: always` 或进程管理器拉起），并支持 `JX3BOT_SELF_SPAWN_RESTART=1` 无 shell 方式拉起子进程。
- `src/plugins/status_monitor/commands.py`：6 个推送开关合并为表驱动 `_register_push_toggle` + 统一群配置归一化函数。
- `src/plugins/wanbaolou/alias.py`：全部 `print()` 替换为 `nonebot.logger`。
