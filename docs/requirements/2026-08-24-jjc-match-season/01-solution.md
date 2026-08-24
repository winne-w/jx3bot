# JJC 对局赛季归属与查询隔离 方案文档

## Problem

`jjc_match_participants` 是角色已同步对局列表的读取模型，但当前记录只包含 `match_time`，不包含赛季。列表查询只按角色身份、3v3 和详情可用性筛选，导致新赛季后仍返回历史缓存。

## Goals

- 以可查询、可索引的 `season_id` 区分玩家对局投影。
- 配置切换后，列表立刻仅显示该配置指定赛季的对局。
- 保留历史原始对局和投影，以便日后单独提供历史查询能力。

## Non-Goals

- 不向 `jjc_match_detail` 写入重复的赛季字段。该集合是完整详情事实，列表过滤由玩家投影负责。
- 不改变同步队列已有的 `season_id` / `season_start_time` 语义。
- 不在本次提供赛季选择器或历史列表 API。

## Current State

`JjcMatchParticipantRepo.build_participants_from_match_detail()` 从详情构建 6 条玩家投影。`list_local_3v3_matches_by_global_id()` 使用 `{global_id, match_type: 3, detail_available: true}` 查询。`JjcRankingInspectService.get_synced_role_matches()` 调用该仓储方法，路由只转发分页参数。

当前同步 worker 已按 `CURRENT_SEASON_START` 停止继续拉取更早的历史，但现有 Mongo 数据和其他详情写入来源仍可产生旧记录，所以读取侧必须有独立的赛季隔离。

## Proposed Solution

在玩家投影中增加可空 `season_id`，并将当前赛季配置传入投影服务。投影构建时从详情提取 `match_time`：当其不早于当前赛季北京时间开始时刻，写入 `CURRENT_SEASON`；否则写入 `null`。

角色已同步对局列表把当前 `CURRENT_SEASON` 传至仓储，仓储查询精确匹配 `season_id`。因此配置由“暗影千机”切换至未来赛季后，旧投影的赛季标识不再匹配；新同步的对局自动进入新赛季。

新增独立回填脚本：默认只统计并输出将更新的数量；显式 `--apply` 后批量更新 `jjc_match_participants`。它根据 `CURRENT_SEASON_START` 给当前赛季时间范围内的行写入当前名称，并清除其他行的 `season_id`，保证重复运行结果一致且不假定历史赛季名称。

## Data and Storage Impact

`jjc_match_participants` 新增字段：

- `season_id: string/null`：对局所属赛季；当前实现只在可由现行配置确定时写入。

新增复合索引 `idx_global_season_available_time`：`global_id`, `season_id`, `match_type`, `detail_available`, `match_time`（降序）, `match_id`（降序）。它覆盖当前角色分页查询的等值前缀与排序。保留旧索引，待线上查询稳定后再另行评估是否移除。

回填目标仅为 `jjc_match_participants`；`jjc_match_detail` 和快照集合不发生写入。脚本必须支持 `--dry-run`、`--apply`、批大小、数据库覆盖和校验模式，并输出处理量、当前赛季行数、未归属行数和失败数。

## API and UI Impact

API 路径、参数和响应结构不变。`synced-role-matches` 的 `total`、分页和 `recent_matches` 将只包含当前赛季。前端无需变更；新赛季刚切换且尚未同步对局时会正常显示空结果。

## Risks and Rollback

- 配置名称或日期填错会把新投影划入错误赛季。上线前用 dry-run 核对开始时间和样本 `match_time`。
- 缺少 `match_time` 的旧详情不进入列表，优先保证不泄漏历史数据；可在后续补数据时重新投影。
- 回滚代码时，删除新查询条件即可恢复原有跨赛季列表；回填字段为新增字段，不影响详情。若需要清除字段，脚本提供明确操作而不在应用启动时自动执行。

## Confirmation

用户已于 2026-08-24 选择本方案中的赛季字段持久化和 Mongo 回填策略。
