# JJC 对局同步 person-history 本地身份优先计划

状态：计划中
更新时间：2026-05-07

## 背景

当前 JJC 对局数据同步在保存单局详情后，会从 `team1.players_info` 和 `team2.players_info` 提取双方玩家。若某个玩家在对局详情里缺少 `global_role_id`，但存在 `person_id`，同步流程会直接请求推栏 `person-history` 补全身份。

这会导致一场 3v3 对局最多对 6 个玩家各请求一次 `person-history`。即使这些玩家的身份已经存在于 MongoDB 的 `role_identities` 或同步队列中，当前流程也不会先查本地身份缓存，外部请求量偏高。

## 目标

- 对局详情玩家缺少 `global_role_id` 时，优先从 MongoDB 已有身份数据补全。
- 本地命中 `global_role_id` 后，不再请求推栏 `person-history`。
- 本地未命中时，保留现有 `person-history` fallback 行为。
- 保持现有同步队列写入、身份表 upsert、对局详情失败重试和水位推进规则不变。
- 补充单测覆盖本地命中跳过外部请求、本地未命中继续 fallback、无可用身份字段时不额外请求。

## 非目标

- 不新增 MongoDB 集合、字段、索引或迁移脚本。
- 不改变推栏 `person-history` API 的签名、分页参数或限速策略。
- 不引入多玩家并发请求；同步流程仍保持串行，避免放大外部接口压力。
- 不改变 `match/history` 拉取逻辑和对局详情缓存策略。
- 不解决同名同服历史身份冲突的全局治理问题；本次只使用现有 `RoleIdentityRepo.resolve_best_identity` 的匹配策略。

## 涉及文件

- `src/services/jx3/jjc_match_data_sync.py`
  - 在对局详情玩家身份补全流程中增加 Mongo 身份优先查询。
  - 复用已有 `identity_repo`，优先按 `global_role_id > zone + role_id > server + role_name` 查询。
  - 命中后将 `global_role_id`、`role_id`、`person_id`、`zone` 等字段回填到 player。
- `tests/test_jjc_match_data_sync.py`
  - 增加本地身份命中时不调用 `person-history` 的单测。
  - 增加本地身份未命中时继续调用 `person-history` 的单测。
  - 增加 player 已有 `global_role_id` 时不查 Mongo、不查外部接口的单测或补充现有断言。
- `docs/exec-plans/index.md`
  - 登记本计划。

## 设计方案

1. 新增私有方法 `_resolve_player_identity_from_local_repo(player)`。
   - 若 `identity_repo` 为空，返回空 dict。
   - 从 player 提取 `server`、`role_name`、`zone`、`role_id`、`global_role_id`。
   - 若缺少 `server` 或 `role_name`，且没有 `zone + role_id` 或 `global_role_id`，返回空 dict。
   - 调用 `identity_repo.resolve_best_identity(server=..., name=..., zone=..., game_role_id=..., global_role_id=...)`。
   - 捕获异常并记录 warning，不中断同步。

2. 调整 `_resolve_player_identity_from_person_history(player)` 的调用入口。
   - 在 `_enqueue_players_from_detail` 中，对缺少 `global_role_id` 的 player 先调用本地查询。
   - 本地返回身份后复用现有字段回填逻辑。
   - 本地未返回身份时，再调用现有 `person-history` 方法。
   - player 已有 `global_role_id` 时保持当前短路行为，不查本地也不查外部。

3. 抽取字段回填小方法，避免本地查询和 `person-history` 查询重复写映射逻辑。
   - 方法只负责将身份 dict 中的 `global_role_id`、`role_id`/`game_role_id`、`person_id`、`zone`、`server`、`role_name` 回填到 player 的空字段。
   - 不覆盖对局详情已经带出的非空字段，降低误合并风险。

4. 保持后续写入逻辑不变。
   - 回填后的 player 继续走 `_upsert_role_identity_from_resolved`。
   - 回填后的 player 继续走 `jjc_sync_role_queue.upsert_role`。
   - 如果本地身份只提供 `global_role_id`，但没有 `person_id`，不强行补造 person_id。

## 验证方案

自动化验证：

```bash
python -m unittest tests.test_jjc_match_data_sync
python -m py_compile src/services/jx3/jjc_match_data_sync.py
```

重点用例：

- 对局详情玩家缺少 `global_role_id`，但 `identity_repo.resolve_best_identity` 返回 `global_role_id`：应回填并写入队列，`person_history.calls` 为空。
- 本地身份查询返回空，player 有 `person_id`：应继续调用 `person-history`，行为与现状一致。
- player 已带 `global_role_id`：不查本地、不查 `person-history`，直接写入身份表和队列。
- 本地身份查询异常：记录 warning 后继续 fallback 到 `person-history`，不导致整场对局详情同步失败。

手工回归：

- 准备 Mongo 中已有某角色 `role_identities`，对局详情 mock 或线上样本中该角色缺少 `global_role_id`。
- 执行一轮 JJC 同步，观察日志和 fake/mock 调用计数，确认本地命中时没有请求 `person-history`。
- 对 Mongo 未命中的新角色执行同步，确认仍可通过 `person-history` 补全并进入同步队列。

## 风险与回滚

- 风险：同服同名返回旧身份，可能把 player 绑定到旧 `global_role_id`。缓解方式是优先使用 `zone + role_id`，只有缺少更强身份时才退到 `server + role_name`，并且不覆盖对局详情已有非空字段。
- 风险：本地 Mongo 查询增加一次读操作。相比外部 `person-history` 请求，延迟和稳定性更可控；若 Mongo 查询失败则 fallback，不中断同步。
- 风险：测试 fake repo 与真实 `RoleIdentityRepo` 字段名不一致。通过单测覆盖 `role_id` 与 `game_role_id` 两种字段。
- 回滚：删除本地优先查询方法和 `_enqueue_players_from_detail` 中的本地查询分支，恢复直接调用 `_resolve_player_identity_from_person_history` 的现有行为。
