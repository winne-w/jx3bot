# JJC 同步自动补队列 dispatcher 需求澄清

## Background

当前 JJC 同步 worker 只消费 `queued` 角色，不会主动从 `pending`、`cooldown`、`exhausted`、`failed` 中挑选到期角色补入队列。近期排行榜自动入队角色已经改为“最近 7 天窗口”同步，单角色处理时间明显下降，worker 更容易空闲，但大量角色仍停留在非 `queued` 状态，导致系统瓶颈从“worker 处理慢”转成“待执行角色补队列不及时”。

现有手工 `/jjc同步开始` 和 CLI `enqueue` 已经具备一次性把候选角色转入 `queued` 的能力，但它们是显式触发、非持续运行，无法稳定喂满常驻 worker。

## Goals

- 增加一个常驻自动补队列 dispatcher，在 worker 空闲或 `queued` 深度不足时，持续把到期角色补入 `queued`。
- 优先复用现有 `enqueue_roles()` / `enqueue_next_roles()` 能力，不重写角色选择与入队语义。
- 不改变当前 worker 对 `queued` 的消费方式、优先级排序、租约机制和角色状态机。
- 为后续继续提高 worker 数量提供稳定的任务供给能力。

## Non-Goals

- 不把 dispatcher 做成新的角色状态机或新的队列集合。
- 不修改 `claim_queued_role()` 的排序规则；仍保持 `priority` 降序、`queued_at` 升序。
- 不一次性把所有 `pending/cooldown/exhausted/failed` 角色全部入队。
- 不改变排行榜 7 天窗口、页面 full 同步和手工同步窗口的既有业务口径。
- 不在本次需求里引入前端页面开关或人工管理页面。

## Scope

本次范围限定在 JJC 同步运行时调度层与文档：

- `src/services/jx3/jjc_match_data_sync.py`
- `src/services/jx3/jjc_sync_worker_runtime.py`
- `bot.py` 启动/停止托管任务链路
- `config.py` 相关运行配置
- `scripts/jjc_sync.py` 如需补充独立 dispatcher CLI
- `docs/design-docs/database-design.md`
- `README.md` / `README-Docker.md` / `docs/references/runbook.md`

默认先支持 bot 内置托管 dispatcher；是否补充 CLI 独立进程启动方式，取决于实现复杂度和运维收益。

## Business Rules

- dispatcher 只负责“补队列”，不直接同步角色详情。
- dispatcher 只通过现有 repo/service 入队接口工作，不绕过现有状态过滤。
- dispatcher 候选来源沿用 `enqueue_next_roles()`：`pending`、`cooldown`、`exhausted`、`failed`，且 `next_sync_after` 为空或已到期。
- dispatcher 只在 `queued` 深度不足时补队列，避免队列无限膨胀。
- dispatcher 不得覆盖页面 full / 排行榜 7 天 / 手工 days/until 的既有单次入队窗口语义。
- dispatcher 自动补队列路径固定使用最近 7 天窗口，即 `queue_sync_until_time = 当前补队列时间 - 7 * 86400`。
- dispatcher 补入队列时默认采用 `mode="full"`；具体同步范围仍由角色本次入队记录中的 `queue_sync_until_time` 决定。
- dispatcher 不得抢占 `syncing` 角色租约，不得改变 `disabled` 角色。
- 页面和手工高优角色仍通过现有 `priority` 机制自然抢占前序执行。

## Dependencies

- MongoDB 队列表：`jjc_sync_role_queue`
- 现有队列 service：`JjcMatchDataSyncService.enqueue_roles()`
- 现有 worker runtime：`src/services/jx3/jjc_sync_worker_runtime.py`
- bot 启动入口：`bot.py`
- 运行配置：`config.py`
- 运行文档：`docs/references/runbook.md`

## Open Questions

- dispatcher 的补队列阈值是固定值，还是按活跃 worker 数动态计算。
- 是否需要额外提供独立 CLI `dispatcher` 子命令，支持脱离 bot 单独运行。
- 是否需要暴露 dispatcher 心跳或状态到现有 `/jjc同步状态` 输出。

## Confirmation

2026-06-17 用户确认总体方向：采用“自动补队列 dispatcher”方案，把到期角色持续补入 `queued`，优先利用当前已出现闲置的同步 worker，而不是继续单纯增加 worker 数量。
