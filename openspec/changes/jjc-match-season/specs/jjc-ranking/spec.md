# JJC 排名与对局查询变更

## ADDED Requirements

### Requirement: 对局投影持久化赛季归属

系统 MUST 在 `jjc_match_participants` 投影中持久化可空的 `season_id`，且仅当 `match_time` 不早于 `CURRENT_SEASON_START` 时写入当前 `CURRENT_SEASON`。

#### Scenario: 写入当前赛季对局
- **WHEN** 对局详情的 match_time 不早于当前赛季开始时间
- **THEN** 每条玩家投影写入当前 season_id

#### Scenario: 写入历史或无时间对局
- **WHEN** match_time 早于赛季开始时间或缺失
- **THEN** 玩家投影的 season_id 为 null
