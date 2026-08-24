# JJC 同步自动补队列 dispatcher 执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

为现有 JJC 同步系统补一个 bot-managed dispatcher，让到期角色能够被持续补入 `queued`，避免 worker 在“排行榜 7 天窗口”上线后经常闲置。实现目标是提升现有 worker 的利用率，而不是引入第二套队列或改写当前同步状态机。

## Progress

- [x] 补齐 dispatcher 需求目录和索引
- [x] 明确 dispatcher service 接口与 runtime 生命周期
- [x] 实现 bot 托管 dispatcher 主循环与停止逻辑
- [x] 补充状态摘要、配置读取和必要日志
- [x] 完成自动化验证与文档联动

## Surprises & Discoveries

- 当前系统已有完整的“候选角色转入 queued”能力，核心缺失的是常驻触发器，不是新的入队算法。
- `enqueue_roles()` 已经负责恢复过期租约、读取暂停状态、按批次补队列，并返回状态摘要，适合作为 dispatcher 的直接复用入口。
- bot 当前只托管 worker，不托管 dispatcher；运行时停止顺序也还没有考虑“停止补队列再停 worker”。

## Decision Log

- 决定先做 bot-managed dispatcher，而不是把“队列为空时顺手补队列”塞进每个 worker tick。原因是前者职责更清晰，日志更好看，也更容易独立开关。
- 决定 dispatcher 首期只复用 service 层 `enqueue_roles()`，不直接在 runtime 里调用 repo，避免绕过现有暂停、租约恢复和批次摘要逻辑。
- 决定 dispatcher 路径固定写最近 7 天窗口，而不是 `queue_sync_until_time=None`。原因是自动补队列的目标是持续喂满 worker，同时保持当前排行榜 7 天同步提速收益，不把低价值角色批量放大成 full。
- 决定首期不新增用户侧页面和 API；若需要诊断，优先通过日志和状态摘要补足。

## Outcomes & Retrospective

本节待实现完成后补充，包括：

- 实际 dispatcher 参数
- 实测 worker 利用率变化
- 是否需要第二阶段补充 CLI / 状态页面诊断

## Context and Orientation

需要重点关注以下文件和边界：

- `src/services/jx3/jjc_match_data_sync.py`
  - 新增 dispatcher 运行逻辑。
  - 复用 `enqueue_roles()`、`queue_status()`、worker 摘要能力。
- `src/services/jx3/jjc_sync_worker_runtime.py`
  - 托管 dispatcher 任务列表、启动/关闭、异常捕获。
- `bot.py`
  - 启动和关闭顺序。
- `config.py`
  - dispatcher 开关与参数。
- `tests/test_jjc_match_data_sync.py`
  - dispatcher service 逻辑单测。
- `tests/test_jjc_sync_worker_runtime.py`
  - bot 托管 dispatcher 生命周期测试。
- `docs/design-docs/database-design.md`
  - 若实现中新增持久化诊断字段，必须同步更新。
- `README.md`、`README-Docker.md`、`docs/references/runbook.md`
  - 说明 dispatcher 配置、启动和观察方式。

## Plan of Work

第一步，补 service 层 dispatcher 能力。新增单轮调度方法和常驻循环方法，负责：

- 读取当前 `queued` 数和活跃 worker 数
- 判断当前是否需要补队列
- 计算本轮补队列的 `limit`
- 调用 `enqueue_roles()` 执行补队列
- 输出本轮诊断摘要

第二步，补 runtime 托管。让 bot 启动时根据配置拉起 dispatcher task，关闭时优先停止 dispatcher，再停 worker。

第三步，补测试与文档。验证 dispatcher 在“队列充足”和“队列不足”两种情况下的行为、启动关闭流程和配置禁用路径，并同步运行文档。

## Concrete Steps

1. 在 `src/services/jx3/jjc_match_data_sync.py` 增加 dispatcher 配置常量或初始化参数，包含：
   - `dispatcher_idle_sleep`
   - `dispatcher_batch_size`
   - `dispatcher_target_per_worker`
   - 可选 `dispatcher_min_active_workers`

2. 新增单轮调度方法，建议命名 `dispatch_queue_once()`：
   - 调用 repo/service 获取 `queued` 数、活跃 worker 数、暂停状态
   - 当全局暂停或活跃 worker 为 0 时直接返回摘要，不补队列
   - 计算目标深度 `target_queue = active_workers * dispatcher_target_per_worker`
   - 当 `queued >= target_queue` 时返回 `skipped`
   - 当 `queued < target_queue` 时，按缺口和 `dispatcher_batch_size` 计算 limit，并调用 `enqueue_roles(source="auto_dispatcher", mode="full", queue_sync_until_time=now-7天)`

3. 新增常驻循环方法，建议命名 `run_dispatcher()`：
   - 周期执行 `dispatch_queue_once()`
   - 根据结果进入 sleep
   - 捕获 `asyncio.CancelledError`
   - 汇总最近一次结果，方便 runtime 或状态查询复用

4. 在 `src/services/jx3/jjc_sync_worker_runtime.py`：
   - 新增 dispatcher task 列表或与 worker task 分离的变量
   - 增加 `start_jjc_sync_dispatcher()` / `stop_jjc_sync_dispatcher()`
   - 按配置决定是否启动 dispatcher
   - 对 dispatcher 异常做日志保护，保持和 worker 一致

5. 在 `bot.py`：
   - 启动时先初始化 Mongo，再启动 worker 和 dispatcher
   - 关闭时先停 dispatcher，再停 worker

6. 在配置中增加 dispatcher 运行参数：
   - `JJC_SYNC_DISPATCHER_ENABLED`
   - `JJC_SYNC_DISPATCHER_IDLE_SLEEP`
   - `JJC_SYNC_DISPATCHER_BATCH_SIZE`
   - `JJC_SYNC_DISPATCHER_TARGET_PER_WORKER`

7. 若实现中发现状态观察不够：
   - 先补 service 层状态摘要
   - 再决定是否把 dispatcher 摘要接入 `/jjc同步状态`
   - 除非确有必要，否则不新增 Mongo 持久化字段

8. 同步文档：
   - `README.md` / `README-Docker.md`：说明 dispatcher 开关和用途
   - `docs/references/runbook.md`：说明 dispatcher 正常行为、常见排查点
   - `docs/design-docs/database-design.md`：仅在新增持久化状态时更新

## Validation and Acceptance

自动化验证至少覆盖：

- `dispatch_queue_once()` 在 `queued` 已足够时不补队列
- `dispatch_queue_once()` 在 `queued` 不足时按缺口补队列
- `dispatch_queue_once()` 在无活跃 worker 或全局暂停时跳过
- `run_dispatcher()` 可正常取消退出
- bot runtime 在 dispatcher 启用/禁用两种配置下启动正常

建议验证命令：

```bash
python -m unittest \
  tests.test_jjc_match_data_sync \
  tests.test_jjc_sync_worker_runtime

python -m py_compile \
  src/services/jx3/jjc_match_data_sync.py \
  src/services/jx3/jjc_sync_worker_runtime.py \
  bot.py
```

手工验收关注点：

- 启动 bot 后，`queued` 较少时应自动出现 `source=auto_dispatcher` 的新入队批次。
- 当 `queued` 已充足时，dispatcher 不应持续无限补队列。
- 关闭 bot 时不应在 shutdown 过程中继续新增补队列批次。
