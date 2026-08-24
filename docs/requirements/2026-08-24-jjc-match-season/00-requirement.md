# JJC 对局赛季归属与查询隔离 需求澄清

## Background

新赛季即将开始。当前本地已同步对局列表按角色 `global_id` 查询 `jjc_match_participants`，没有赛季条件；集合和 `jjc_match_detail` 也没有对局赛季字段。因此更新 `config.py` 中的当前赛季后，列表仍会混入已缓存的历史赛季对局。

## Goals

- 为可展示的 JJC 3v3 玩家对局投影持久化赛季归属。
- 已同步对局查询只返回与 `config.CURRENT_SEASON` 一致的记录。
- 回填当前 MongoDB 存量数据：仅将发生时间不早于 `CURRENT_SEASON_START` 的记录标记为当前赛季；更早或无对局时间的记录保持无赛季归属。
- 后续只需更新 `config.py` 的 `CURRENT_SEASON` 与 `CURRENT_SEASON_START`，无需再修改查询代码。

## Non-Goals

- 不删除、归档或改写历史赛季的完整对局详情。
- 不为开始日期未知的未来赛季预设名称或日期。
- 不改变按 `match_id` 直接读取详情的 API 语义；本需求的“对局查询”限定为角色的已同步对局列表。
- 不为历史赛季猜测或伪造实际赛季名称。

## Scope

- 写入链路：对局详情生成 `jjc_match_participants` 投影时写入 `season_id`。
- 读取链路：`GET /api/jjc/ranking-stats/synced-role-matches` 通过 service/repo 按当前赛季读取。
- 数据维护：新增可重复执行、默认 dry-run 的 Mongo 回填脚本，并在当前库完成回填与核验。
- 文档：数据库设计、运行手册和本需求交付记录。

## Business Rules

- 赛季标识唯一来源是运行时的 `config.CURRENT_SEASON`；赛季开始边界唯一来源是 `config.CURRENT_SEASON_START`，按北京时间零点解释。
- 新写入投影时，只有 `match_time >= CURRENT_SEASON_START` 的对局写入当前 `season_id`。赛季前或缺少 `match_time` 的对局写入 `season_id: null`，不会进入当前赛季列表。
- 查询必须精确匹配当前 `season_id`，不以缓存写入时间或同步时间推断赛季。
- 回填遵循同一规则，允许重复运行；不会删除任何文档。

## Dependencies

- MongoDB：`jjc_match_participants` 读取模型。
- 配置：`config.py` 的 `CURRENT_SEASON`、`CURRENT_SEASON_START`。
- 当前投影生成器、JJC 已同步对局 API 和静态页面。

## Open Questions

- 无。未来赛季名称和开始日期确定后，由维护者更新现有配置即可。

## Confirmation

用户已于 2026-08-24 选择“持久化赛季标识 + 回填 Mongo”方案，并明确要求新赛季的 JJC 对局查询不显示历史赛季记录。
