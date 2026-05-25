# JJC 排名心法历史胜场兜底计划

## 背景

JJC 排名统计当前主要通过 `role/indicator`、推栏 `match/history`、实时竞技查询和 `role_jjc_cache` 判断角色心法。少量排名角色会出现当前接口查不到心法，但本地 `jjc_match_detail` 已缓存该角色历史对局，且角色在获胜对局中同一心法出现 3 场以上。

本次目标是在排名统计链路中增加一个保守兜底：当现有心法查询无法给出 `kungfu` 时，从当前赛季已缓存的历史对局详情中统计该角色获胜场次，只有同一心法胜场数不少于 3 场才作为排名统计心法。

## 目标

- 让 `get_ranking_kungfu_data()` 对排名中原本 `missing_kungfu_lines` 的角色再尝试一次本地历史对局胜场推断。
- 推断结果只用于“同一角色”的心法，不使用 `person_id` 或 SK01 `global_role_id` 做跨角色匹配。
- 仅当同一心法在获胜对局中出现 `>= 3` 场时认定成功。
- 成功时写入 `role_jjc_cache`，后续排名统计可直接命中缓存。
- 在结果中保留来源和样本信息，方便排查误判。

## 非目标

- 不主动请求新的推栏对局详情或 replay；只读取已缓存的 `jjc_match_detail`。
- 不重建 `role_identities` 或同步队列。
- 不改变 HTTP API 路由和响应外层结构。
- 不把历史对局中的装备、队友、奇穴补成完整缓存；本次只补心法判定所需字段。

## 设计

### 1. 数据来源

读取 Mongo 集合 `jjc_match_detail`：

- `data.detail.team1.won` / `data.detail.team2.won` 判断角色所在队伍是否获胜。
- `data.detail.team*.players_info[].server`、`role_name`、`kungfu`、`kungfu_id` 用于角色与心法统计。
- `data.replay.data.players[].role_id` / `global_role_id` 仅作为稳定角色 ID 兜底匹配来源，其中 replay 数字 `global_role_id` 作为项目内 `global_id` 语义使用。

### 2. 角色匹配规则

优先且必须满足至少一种角色级匹配：

- `server == 目标服务器` 且 `role_name` 等于 `目标角色名` 或 `目标角色名·目标服务器`。
- 若排名数据或 `role_identities` 已有稳定角色 ID，则 replay 玩家 `role_id` 或数字 `global_role_id` 命中后，再映射回同场详情中的同名玩家。

明确不使用：

- `person_id`：账号/人物维度，可能把同账号其他角色混入。
- SK01 `global_role_id`：用于请求 `match/history` 的入口 ID，不作为历史详情玩家唯一身份。

### 3. 当前赛季过滤

按 `JjcRankingService.current_season_start` 解析 `YYYY-MM-DD`，转换为 Unix 秒，查询时只统计 `data.detail.match_time >= season_start_ts` 的对局。解析失败时记录 warning 并不加时间过滤。

### 4. 胜场心法判定

统计每个候选心法：

- `wins`: 该角色所在队伍获胜的场次。
- `total`: 该角色以该心法出现的总场次。
- `latest_win_match_id` / `latest_win_time`: 最新胜场样本。
- `win_samples`: 最多保留若干胜场样本用于调试。

判定规则：

- 过滤 `wins < 3` 的心法。
- 若存在多个合格心法，按 `wins desc`、`latest_win_time desc`、`total desc` 排序取第一。
- 返回 `kungfu_selected_source = "cached_match_detail_win_history"`。

### 5. 代码落点

- `src/services/jx3/jjc_cache_repo.py`
  - 增加历史胜场心法查询方法，封装 Mongo 查询和统计逻辑。
  - 保持 service 通过 repo 访问 Mongo，不在 handler/API 中散写集合查询。
- `src/services/jx3/jjc_ranking.py`
  - `get_user_kungfu()` 在现有 indicator / `defget` fallback 都无法得到心法后调用历史胜场兜底。
  - 成功时设置 `found=True`、写入 `role_jjc_cache`，并让本轮排名统计直接计入。
  - `kungfu_results` 透传新增的历史胜场字段，便于明细和日志诊断。
- `src/storage/mongo_repos/role_jjc_cache_repo.py`
  - `save()` 继续保存透传字段；如需补字段说明，只更新文档，不改变方法签名。
- `src/infra/mongo.py`
  - 补 `jjc_match_detail` 嵌套字段索引，避免历史胜场兜底在大集合上按赛季全表扫描。

### 6. 文档联动

如新增缓存字段或索引，同步更新：

- `docs/design-docs/database-design.md`
- `docs/references/runbook.md` 的 JJC 排名统计回归说明（如验证路径变化）

## 验证

自动化：

```bash
python -m unittest tests.test_jjc_ranking_history_win_kungfu tests.test_jjc_kungfu_global_id tests.test_jjc_weapon_quality
python -m py_compile src/services/jx3/jjc_cache_repo.py src/services/jx3/jjc_ranking.py src/storage/mongo_repos/role_jjc_cache_repo.py
```

手工数据回归：

- 用本次样本角色验证胜场阈值：
  - `龙争虎斗 檀健次@蝶恋花` → `孤锋诀`
  - `蝶恋花 喜欢沈星回` → `灵素`
  - `幽月轮 欧欧小月@唯我独尊` → `惊羽诀`
  - `唯我独尊 独孤的间王花` → `花间游`
  - `斗转星移 蛇咬` → `幽罗引`
  - `唯我独尊 我超好哄的` → `幽罗引`
- 确认这些角色不再进入 `missing_kungfu_lines`，且 `kungfu_selected_source` 为 `cached_match_detail_win_history`。

## 风险与回滚

- 风险：同名角色或改名转服导致历史对局混入。控制方式是当前赛季过滤、严格 `server + role_name` 匹配、仅使用 replay 稳定角色 ID，不使用 `person_id`。
- 风险：对 `jjc_match_detail` 做逐角色查询可能增加统计耗时。控制方式是仅在现有链路失败后触发，并视实现结果补嵌套索引。
- 回滚：移除 `get_user_kungfu()` 中历史胜场兜底调用即可恢复原行为；写入的 `role_jjc_cache` 记录可自然 TTL 过期，必要时按 `kungfu_selected_source` 清理。

## 状态

- 2026-05-24：计划已创建，等待确认进入实现阶段。
- 2026-05-25：已实现并验证。已补历史胜场兜底、缓存诊断字段、`jjc_match_detail` 窄查询和嵌套索引；已通过单测、编译、`diff --check`、真实 Mongo 样本验证和多轮 subagent review。
