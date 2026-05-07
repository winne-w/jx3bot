# JJC 对局同步批量调度计划

状态：进行中
更新时间：2026-05-07

## 背景

当前 `/jjc同步开始` 只触发一轮同步，service 默认每轮领取 3 个角色。队列达到 1000+ 角色时，管理员需要重复触发数百次，实际不可用。

## 目标

- 保持现有 `/jjc同步开始 [default|full|incremental]` 兼容。
- 支持管理员在命令中指定单轮领取数量：`limit=<N>`。
- 支持多轮批量执行：`rounds=<N>` 或 `rounds=auto`。
- 支持后台执行：追加 `background` 或 `后台` 后立即返回启动结果。
- 管理员命令的时间上限使用分钟参数 `minutes=<N>`，默认 60 分钟；service 内部仍使用秒作为运行保护单位。
- 状态命令展示后台批量任务运行状态和最近批量摘要。

## 非目标

- 不新增 HTTP 管理入口。
- 不新增数据库集合或字段。
- 不做多角色并发请求；本次只做批量轮询，避免放大推栏接口压力。
- 不改变对局详情去重、失败重试、水位推进规则。

## 涉及文件

- `src/services/jx3/jjc_match_data_sync.py`
- `src/plugins/jx3bot_handlers/jjc_match_data_sync.py`
- `tests/test_jjc_match_data_sync.py`
- `tests/test_jjc_match_data_sync_handler.py`
- `docs/exec-plans/index.md`

## 实施方案

1. 已完成：在 service 保留 `run_once(mode, limit)`，新增 `run_until_idle(mode, limit, max_rounds, max_seconds)` 聚合多轮结果。
2. 已完成：在 service 内维护单个后台任务，新增 `start_background_run(...)`，同一时间只允许一个后台批量任务运行。
3. 已完成：后台任务复用 `run_until_idle`，完成后保存最近批量摘要，状态接口返回 `background_running` 与 `last_background_summary`。
4. 已完成：handler 解析 `limit=`, `rounds=`, `minutes=`, `background/后台`；未传时维持现有单轮默认。
5. 已完成：补充 handler/service 单测覆盖参数解析、批量聚合、后台重复启动保护。

## 当前进度

- 2026-05-07：已实现批量多轮、后台启动、状态展示和管理员帮助示例。
- 2026-05-07：已通过单测和 py_compile 验证；计划保持 active，待代码提交后再移动到 completed。
- 2026-05-07：根据管理员使用习惯，将命令层时间参数从 `seconds=` 调整为 `minutes=`，默认 60 分钟。

## 验证

```bash
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_match_data_sync_handler
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py
```

## 风险与回滚

- 风险：`limit` 过大可能增加推栏请求压力。通过保持串行处理、默认仍为 3、管理员显式传参控制。
- 风险：后台任务异常丢失。通过捕获异常并写入最近批量摘要。
- 回滚：移除新增命令参数解析和 service 批量方法，恢复 `/jjc同步开始` 仅调用 `run_once(mode=mode)`。
