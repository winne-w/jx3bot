# JJC 同步自动补队列 dispatcher 方案文档

## Problem

当前 JJC 同步体系把“消费队列”和“补充队列”拆成了两件事：worker 常驻消费 `queued`，而候选角色从 `pending/cooldown/exhausted/failed` 进入 `queued` 需要显式调用 `enqueue_roles()`。当排行榜角色缩短到最近 7 天同步后，单角色处理耗时下降，worker 更容易把现有 `queued` 吃空；此时系统里虽然还有大量到期可执行角色，但没有常驻组件持续把它们转入 `queued`，worker 就会空转。

如果不补这一层，继续增加 worker 数量不会提升真实吞吐，反而只会放大空闲比例。

## Goals

- 为现有 JJC 同步体系补充常驻 dispatcher，让 `queued` 长期保持合理深度。
- 保持当前 worker、租约、优先级、单次同步窗口和状态机逻辑不变。
- 让页面 full、高优手工角色和排行榜 7 天角色继续共用同一队列与优先级体系。

## Non-Goals

- 不重构 `JjcSyncRepo` 的状态流转。
- 不新增第二套任务表、消息队列或调度中心。
- 不改变 `priority` 含义，不把负优先级转换成禁用语义。
- 不修改已有页面、HTTP API 的用户交互口径，除非实现阶段发现最小必要诊断字段需要补充。

## Current State

- `JjcMatchDataSyncService.worker_tick()` 只会 `claim_queued_role()`；没有 `queued` 时 worker 进入 `idle`。[src/services/jx3/jjc_match_data_sync.py]
- `enqueue_roles()` 已能按 `priority` 和 `next_sync_after` 从 `pending/cooldown/exhausted/failed` 中选取到期角色，原子写入 `queued`。[src/services/jx3/jjc_match_data_sync.py] [src/storage/mongo_repos/jjc_sync_repo.py]
- bot 启动时只会拉起托管 worker，不会拉起托管 dispatcher。[src/services/jx3/jjc_sync_worker_runtime.py] [bot.py]
- 排行榜自动入队角色现在默认只同步最近 7 天，worker 单次处理耗时比 full 更短，因此更依赖持续补队列能力。

## Proposed Solution

总体方案是新增一个 bot-managed 的“自动补队列 dispatcher”常驻任务，与现有 bot-managed worker 并列运行。

dispatcher 主循环职责：

1. 周期性读取当前队列计数和活跃 worker 数。
2. 计算目标 `queued` 深度，例如 `active_workers * queued_target_per_worker`。
3. 当当前 `queued` 数低于目标深度时，调用 `enqueue_roles()` 补入一批到期角色。
4. 当前 `queued` 已达到阈值时，dispatcher 休眠等待下一轮。

分层设计：

- `src/services/jx3/jjc_match_data_sync.py`
  - 新增轻量 dispatcher service 方法，例如 `dispatch_queue_once()` / `run_dispatcher()`。
  - 负责读取状态、判断是否需要补队列、调用现有 `enqueue_roles()`，并返回诊断摘要。
  - 不直接操作底层集合，不复制 `enqueue_next_roles()` 过滤逻辑。
  - dispatcher 路径固定计算 `queue_sync_until_time = now - 7 * 86400`，以最近 7 天窗口补队列。

- `src/services/jx3/jjc_sync_worker_runtime.py`
  - 新增 dispatcher task 的启动、停止、异常保护逻辑。
  - dispatcher 与 worker 使用相同的 bot 托管生命周期。

- `bot.py`
  - 启动时一并启动托管 dispatcher。
  - 关闭时先停止 dispatcher，再停止 worker，避免 bot 退出时继续新补队列。

推荐调度策略：

- `queued_target_per_worker`: 每个活跃 worker 希望队列里至少有多少候选，默认建议 `3`。
- `dispatch_batch_size`: 每次补队列最多补多少角色，默认建议 `20` 或 `active_workers * 3` 的较大者。
- `dispatch_idle_sleep`: 本轮无需补队列时的 sleep 秒数，默认建议 `10`。
- 活跃 worker 判断沿用当前 worker 心跳状态中的 `starting/running/idle/syncing/paused`。
- dispatcher 写入的 `queue_sync_until_time` 固定为最近 7 天，不沿用旧窗口，也不改页面/手工显式 full 的语义。

这样做的原因：

- `queued_target_per_worker` 控制“不断粮但不过量囤积”。
- `dispatch_batch_size` 控制单轮 Mongo 写入量和并发入口下的队列膨胀。
- dispatcher 只补足缺口，不会把所有到期角色一次性推满队列，保留高优角色插队空间。
- dispatcher 统一写最近 7 天窗口，避免把原本已经提速的自动同步角色重新放大成 full。

## Data and Storage Impact

本方案默认不新增 Mongo 集合，不调整现有角色状态字段，不改索引。

可选诊断增强：

- 若实现阶段确认有必要，可在 `jjc_sync_workers` 中新增 dispatcher 类型心跳记录，或沿用现有 worker 心跳集合增加 `worker_type=dispatcher`。
- 如果增加 dispatcher 心跳或统计字段，必须同步更新 `docs/design-docs/database-design.md`。

首选方案是先不新增持久化字段，dispatcher 状态仅保存在日志和运行时 task 中；只有在观察和排障需要明显不足时，才补最小诊断字段。

## API and UI Impact

默认不新增用户侧 API 或页面入口。

可选增强：

- `/jjc同步状态` 若已经展示 worker 运行态，可追加 dispatcher 运行摘要，例如最近一次补队列数量、最近一次空转时间。
- CLI 可追加 `dispatcher` 子命令，方便脱离 bot 单独运行；但这不是首期必须项。

首期目标是先解决供给不足，不扩大用户可见面。

## Risks and Rollback

主要风险：

- 阈值过大导致 `queued` 长期堆积，页面/手工高优角色虽然仍可凭 `priority` 抢占，但运维观察会更难判断“真实待处理深度”。
- 阈值过小或 sleep 过长时，worker 仍可能短暂吃空队列，供给改善不明显。
- 若 dispatcher 与手工 `/jjc同步开始` 并发补队列，虽然底层 `find_one_and_update` 已做原子保护，但日志和批次观察会更复杂。

控制方式：

- 默认使用保守参数启动，先追求“喂饱 worker”，不追求队列最大化。
- dispatcher 统一复用现有 `enqueue_roles()`，避免旁路写入。
- 托管 runtime 对 dispatcher 异常做和 worker 相同的捕获与日志保护，不让单个 dispatcher 异常影响 bot 主进程。

回滚方式：

- 配置关闭 dispatcher，恢复到现有“只托管 worker、手工补队列”的行为。
- 如实现阶段引入额外 CLI 或状态输出，可单独下线这些入口，不需要迁移数据。

## Confirmation

2026-06-17 用户确认采用 dispatcher 方向：新增自动补队列常驻组件，持续把到期角色补入 `queued`，优先利用已出现闲置的 worker，不把本次范围扩大到新的页面或大规模状态机重构。
