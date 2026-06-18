# JJC 7 天历史最高分排名需求澄清

## Background

当前 JJC 心法排名统计每天 21:00 和 03:00 触发，统计对象来自当时排行榜。部分玩家会在分数打上去后通过洗车掉出当前排行榜，导致只按当前排行榜统计无法覆盖这类玩家。

系统已经通过排名统计、页面查看和同步队列沉淀了推栏历史对局详情。对局详情的玩家节点保存了对局发生时的分数字段，包括 `mmr`、`score`、`total_score`。前端对局详情当前展示口径为 `mmr` 对应“推栏分数”，`total_score` 对应“游戏分数”。

## Goals

- 每天 09:00 基于最近两个 JJC 排名统计快照的时间点，分别生成“该时间点往前 7 天”的历史最高分排名。
- 统计对象来自历史对局中的所有 3v3 参与者，而不是来自排名快照成员，避免洗车后掉榜玩家漏统。
- 同时生成两套最高分排名：推栏分数排名和游戏分数排名。
- 每个最高分结果记录对应的 `match_id` 和对局发生时间，便于后续排查。
- 历史已入库对局可以通过脚本回填新增投影字段。

## Non-Goals

- 不改变现有 21:00 / 03:00 JJC 心法排名统计、推送和图片生成口径。
- 不实时请求推栏补全 09:00 统计缺失数据；09:00 只统计本地已同步对局。
- 不把最高分结果回填到现有心法排名成员明细中，避免混淆两个排名口径。
- 不改变对局详情页面既有“推栏分数 / 游戏分数”展示文案。

## Scope

本次影响 JJC 对局参与者投影、历史投影回填脚本、09:00 定时统计任务、MongoDB 设计文档，以及后续可能新增的 API / 页面展示入口。统计数据来源为本地 MongoDB 中已保存的 `jjc_match_detail` 与可重建读取模型 `jjc_match_participants`。

## Business Rules

- 统计锚点来自最近两个 `jjc_ranking_stat_summaries.timestamp`。
- 每个锚点的窗口为 `[timestamp - 7 * 86400, timestamp]`。
- 窗口过滤使用接口返回的对局发生时间，优先 `data.detail.match_time`，缺失时兜底 `data.detail.basic_info.start_time`；禁止使用 `cached_at`、`detail_saved_at`、`updated_at` 等入库时间。
- 统计对象为窗口内所有本地已同步、详情可用的 3v3 对局参与者。
- 推栏分数字段使用 `players_info[].mmr`。
- 游戏分数字段使用 `players_info[].total_score`，缺失时可兜底 `players_info[].score` 并记录来源字段。
- 同一角色按稳定身份聚合，优先使用 `global_id`；缺失时按后续方案定义的兼容身份键兜底。
- 每个排名项必须保存最高分对应的 `match_id`、`match_time`、分数字段来源、角色名、服务器、心法和参与对局数量。
- 09:00 任务应具备幂等性；已完成同一锚点和版本的最高分统计时不重复生成，除非显式重跑。

## Dependencies

- MongoDB: `jjc_match_detail`、`jjc_match_participants`、`jjc_ranking_stat_summaries`，以及新增最高分统计结果集合。
- 定时任务: `src/plugins/status_monitor/jobs.py`。
- 投影构建: `src/storage/mongo_repos/jjc_match_participant_repo.py`、`src/services/jx3/match_detail_participant_projection.py`。
- 历史回填: `scripts/backfill_jjc_match_participants.py`。
- 前端口径参考: `public/jjc-ranking-stats.html`。
- 数据库设计文档: `docs/design-docs/database-design.md`。

## Open Questions

- 最高分排名结果是否需要首期提供静态页面展示，还是先只提供 Mongo 结果和后续 API。
- 当同一角色缺少 `global_id` 时，兜底身份键是否接受 `person_id`，还是仅接受 `server + role_name`。

## Confirmation

2026-06-17 用户确认方案方向：从历史对局中查询用户最高分并排名，不从当前排名成员查询历史最高分；推栏分数和游戏分数按前端现有文案确定；统计需使用接口返回的对局发生时间，并记录最高分对应的对局 ID。
