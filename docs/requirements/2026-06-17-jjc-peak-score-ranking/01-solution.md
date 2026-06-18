# JJC 7 天历史最高分排名方案文档

## Problem

现有 JJC 心法排名统计依赖当前排行榜。玩家洗车后可能掉出排行榜，即使其最近 7 天曾经打到高分，也不会进入当前排行榜统计。若在 21:00 或 03:00 排名任务内直接计算历史最高分，又会受历史对局异步同步进度影响，导致新近对局未落库时统计缺失。

## Goals

- 使用 09:00 独立任务做最高分补充统计，给 21:00 和 03:00 后的异步历史对局同步留出时间。
- 从历史对局参与者维度生成最高分排名，覆盖已经掉出当前排行榜的玩家。
- 分别按推栏分数和游戏分数生成最高分排名。
- 结果可追溯到具体 `match_id`。

## Non-Goals

- 不在 21:00 / 03:00 排名任务里同步等待历史对局补齐。
- 不以排名快照成员作为最高分排名对象。
- 不在本需求中重构 JJC 同步队列或推栏请求策略。

## Current State

`jjc_match_detail` 保存完整对局详情，玩家节点含 `mmr`、`score`、`total_score`。`public/jjc-ranking-stats.html` 对局详情文案显示 `player.mmr` 为“推栏分数”，`player.total_score` 为“游戏分数”。

`jjc_match_participants` 是玩家级轻量投影，当前主要用于按 `global_id` 查询本地已同步对局列表。它目前只保存合并后的 `total_mmr` 和 `mmr_delta`，没有保存拆分后的 `mmr`、`score`、`total_score`，因此不适合直接生成两套最高分排名。

已有 `scripts/backfill_jjc_match_participants.py` 可从 `jjc_match_detail` 重建参与者投影，适合作为新增投影字段后的历史回填入口。

## Proposed Solution

先扩展 `jjc_match_participants` 读取模型，在构建参与者投影时保存拆分分数字段：

- `tuilan_score`: 来源 `players_info[].mmr`，对应前端“推栏分数”。
- `game_score`: 来源 `players_info[].total_score`，缺失时兜底 `players_info[].score`，对应前端“游戏分数”。
- `game_score_source`: `total_score` 或 `score`。
- `raw_score`: 原始 `players_info[].score`。
- `raw_total_score`: 原始 `players_info[].total_score`。
- `raw_mmr`: 原始 `players_info[].mmr`。

新增或扩展回填脚本，复用现有 `scripts/backfill_jjc_match_participants.py` 对历史 `jjc_match_detail` 做整场重建，使旧对局投影也拥有拆分字段。

新增 09:00 定时任务。任务读取最近两个 `jjc_ranking_stat_summaries`，只把它们的 `timestamp` 作为统计锚点。对每个锚点，查询 `jjc_match_participants` 中 `match_time` 落在 `[timestamp - 7天, timestamp]` 的 3v3 可用详情参与者，分别按 `tuilan_score` 和 `game_score` 聚合每个角色的最高分，然后生成两份最高分榜。

统计结果单独落库，不写回 `jjc_ranking_stat_details.members`。建议新增集合 `jjc_peak_score_rankings`，每条文档对应一个锚点、一种分数口径和一个窗口版本。

## Data and Storage Impact

### `jjc_match_participants`

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tuilan_score` | int/null | 推栏分数，来自对局详情玩家节点 `mmr` |
| `game_score` | int/null | 游戏分数，优先来自 `total_score`，缺失兜底 `score` |
| `game_score_source` | string/null | `game_score` 来源字段，如 `total_score` 或 `score` |
| `raw_mmr` | int/null | 原始 `mmr` |
| `raw_score` | int/null | 原始 `score` |
| `raw_total_score` | int/null | 原始 `total_score` |

索引建议补充：

- `match_type, detail_available, match_time`
- `global_id, match_time`

### `jjc_peak_score_rankings`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `anchor_timestamp` | int | 统计锚点，来自排名快照 timestamp |
| `window_start` | int | 统计窗口起点 |
| `window_end` | int | 统计窗口终点，等于 anchor timestamp |
| `score_type` | string | `tuilan` 或 `game` |
| `window_days` | int | 固定 7 |
| `status` | string | `processing`、`done`、`failed` |
| `items` | array | 排名项 |
| `item_count` | int | 排名项数量 |
| `source_match_count` | int | 参与统计的对局数 |
| `source_participant_count` | int | 参与统计的玩家行数 |
| `version` | int | 统计口径版本 |
| `generated_at` | float | 生成时间 |
| `error` | string/null | 失败原因 |

`items[]` 建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `rank` | int | 排名 |
| `score` | int | 最高分 |
| `match_id` | int | 最高分对应对局 ID |
| `match_time` | int | 最高分对应对局发生时间 |
| `score_source` | string | 来源字段 |
| `global_id` | string/null | 稳定角色 ID |
| `role_name` | string/null | 对局中的角色名 |
| `server` | string/null | 服务器 |
| `zone` | string/null | 大区 |
| `kungfu` | string/null | 心法 |
| `match_count` | int | 窗口内该角色参与统计的对局数 |

唯一索引建议：

- `anchor_timestamp, score_type, version`

## API and UI Impact

已在现有 JJC 排名页面增加展示入口，并新增只读 API：

- `GET /api/jjc/ranking-stats/flat-members?timestamp=<timestamp>&range=<top_1000|top_200|top_100|top_50>`：读取当前推栏排名扁平角色列表，不按心法分组。
- `GET /api/jjc/ranking-stats/peak-score?timestamp=<timestamp>&score_type=<tuilan|game>&range=<top_1000|top_200|top_100|top_50>`：读取 7 天最高分榜。

`public/jjc-ranking-stats.html` 增加视图切换：心法分布、当前排名列表、7 日推栏最高分、7 日游戏最高分。列表支持前 1000、前 200、前 100、前 50 切换；最高分列表展示最高分对应对局 ID，并可点击打开现有对局详情弹窗。

## Risks and Rollback

主要风险是历史对局同步不完整导致 09:00 统计缺数据。结果中记录 `source_match_count` 和 `source_participant_count`，用于观察当天统计覆盖度。该需求只读本地已同步数据，不阻塞排名主任务。

若上线后发现统计口径错误，可停止 09:00 job，并删除或忽略 `jjc_peak_score_rankings` 中对应 `version` 的结果。`jjc_match_participants` 新增字段是读取模型字段，可通过回填脚本重建或回滚代码后保留不用。

## Confirmation

2026-06-17 已与用户确认核心方案：09:00 按最近两个排名快照时间点，从历史对局参与者生成 7 天最高分排名；字段口径以现有前端文案为准；统计时间使用接口返回的对局发生时间；结果记录最高分对应 `match_id`。
