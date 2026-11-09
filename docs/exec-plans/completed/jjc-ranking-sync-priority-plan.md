# JJC 排名统计触发同步队列优先级计划

## 背景

当前 JJC 同步队列使用 `priority` 做 worker 领取排序，角色同步成功后会进入 `cooldown` 或 `exhausted`，但优先级不会自动回落。排行榜统计会产出各心法成员明细，但统计到的角色不会主动进入同步队列等待补齐对局数据。

## 目标

1. 角色完成一轮同步并成功释放租约后，将同步队列 `priority` 重置为 `0`。
2. 排行榜统计保存时，对统计明细里的有效角色写入/更新同步队列候选，设置 `priority=1`，并转入 `queued` 等待 worker 同步；若角色已在同步队列且 `priority >= 1`，不重复更新或入队。

## 非目标

- 不改变 worker 排序规则、失败重试规则和 cooldown/exhausted 的时间策略。
- 不新增管理命令或 HTTP API。
- 不改排行榜统计口径和展示结构。

## 涉及文件

- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 在 `release_identity_success` 和 legacy `release_role_success` 成功路径写入 `priority=0`。
  - 提供按排行榜成员 upsert 并入队的仓储方法，复用现有身份队列字段与 `enqueue_*` 语义。
- `src/services/jx3/jjc_ranking.py`
  - 在 Mongo 保存统计快照任务中，保存快照后扫描 `detail_payloads` 的 `members`，将成员加入同步队列，来源标记为 `ranking_stats`。
- `tests/test_jjc_sync_worker_queue.py`
  - 覆盖成功释放重置优先级，以及排行榜成员入队写入优先级 1。
- `tests/test_jjc_ranking_stats_repo.py` 或新增 service 单测
  - 覆盖统计保存任务会调用同步队列补充逻辑。

## 数据与兼容

- 不新增集合、索引或字段，只调整既有 `jjc_sync_identity_queue`/`jjc_sync_role_queue` 中 `priority`、`status`、`queue_*` 等字段写入。
- 排行榜成员若有 `global_id`、`global_role_id`、`zone + role_id/game_role_id`、`server + name` 任一身份锚点即可入队；字段不足则跳过。
- 已存在同步队列记录且 `priority >= 1` 时跳过，避免覆盖人工或其他来源设置的高优先级任务。
- 当前 identity-id 队列可通过 `role_identities` 建档后写入 `identity_id` 关联；测试或迁移环境缺失 identity 集合时，保持 legacy `identity_key` 队列 fallback。

## 验证

- `python -m unittest tests.test_jjc_sync_worker_queue tests.test_jjc_ranking_stats_repo`
- `python -m py_compile src/storage/mongo_repos/jjc_sync_repo.py src/services/jx3/jjc_ranking.py`

## 回滚

回滚本计划改动后，队列优先级恢复为原先不自动归零，排行榜统计只保存快照，不再触发同步队列入队。
