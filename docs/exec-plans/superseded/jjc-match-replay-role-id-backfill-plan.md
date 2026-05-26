# JJC 对局回放与 indicator 补全角色身份计划

> 已合并至 `docs/exec-plans/completed/jjc-role-global-id-governance-plan.md`，本文仅作历史参考。

状态：已实现，待提交
更新时间：2026-05-19

## 背景

当前竞技场对局同步主要流程为：

1. 使用队列角色的 `global_role_id` 请求 `/3c/mine/match/history`。
2. 从历史列表拿 `match_id`。
3. 请求 `match/detail` 保存详情，并从 `team1/team2.players_info` 自动发现其他玩家。
4. 对缺少 `role_id/global_role_id` 的玩家，当前通过本地身份库或 `/mine/match/person-history` 补全。
5. 将玩家写入 `role_identities` 和 `jjc_sync_role_queue`。

实测发现：

- `match/detail.players_info[].role_id` 字段存在但通常为空。
- `match/detail.players_info[].global_role_id` 字段存在但通常为空。
- `/mine/match/person-history` 能补 `SK01-... global_role_id`，但不返回 `role_id`，且同一 `person_id` 可能关联多个角色，必须做角色级校验。
- `/3c/mine/match/replay` 和 `/3d/mine/match/replay` 的 `players[].role_id` 有值。
- `/role/indicator` 可用 `role_id + zone + server` 查询，并返回 `SK01-... global_role_id`、`role_id`、`person_id`、区服和角色名。
- `/3c/mine/match/history` 与 `/3d/mine/match/history` 对同一请求体实测响应完全一致。

因此后续同步对局详情时，应额外请求 `match/replay`，再通过 `role/indicator` 将回放中的 `role_id` 转换为同步主流程需要的 `SK01-... global_role_id`。`person-history` 不再作为对局玩家身份补全主路径，只保留为入口角色缺身份时的兼容 fallback。

## 目标

- 同步每场对局时请求 `/3c/mine/match/replay`，从 `players[]` 提取 `role_id`。
- 将 `match/detail` 的 `person_id/server/zone/role_name` 与 `match/replay` 的 `role_id/role_name` 合并为完整的 indicator 查询参数。
- 对匹配成功的玩家请求 `/role/indicator`，补齐 `SK01-... global_role_id`、`role_id`、`person_id`、`zone/server/name`。
- 写入或更新 `role_identities` 与 `jjc_sync_role_queue` 时补充 `global_role_id`、`role_id` / `game_role_id`、`person_id`。
- 队列中能参与 history 同步的入口角色必须最终具备 `SK01-... global_role_id`；无法补齐的角色不应作为可执行入口进入普通同步队列。
- 对已存在于本地身份库但缺少 `role_id` 或 `global_role_id` 的角色，优先用 replay + indicator 补齐。
- 每次用对局数据更新角色信息时，记录对局发生时间。
- 若对局发生在角色信息上次更新之后，则允许用该对局数据更新角色信息。
- 若对局发生在角色信息上次更新之前，且角色没有缺失字段，则不更新。

## 非目标

- 不把 replay 中的纯数字 `players[].global_role_id` 当作 `SK01-... global_role_id` 使用。
- 不改变 `match/history` 按 `global_role_id` 拉取对局历史的主流程。
- 不自动修改已有 `identity_key`，避免触发唯一索引冲突；identity_key 升级另行评估。
- 不用装备接口补身份，因为 `/mine/equip/get-role-equip` 存在权限限制。
- 不再把 `/mine/match/person-history` 作为对局玩家补全 `global_role_id` 的首选路径。

## 数据字段

在 `role_identities` 和 `jjc_sync_role_queue` 中新增运行时字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `role_info_observed_match_time` | int/null | 最近一次用于更新角色身份信息的对局时间 Unix 秒 |
| `role_info_source` | string/null | 角色信息来源，如 `match_replay_indicator` |
| `role_info_updated_at` | float/null | 写入时间 Unix 秒 |

更新规则：

- 如果目标文档缺少 `global_role_id`、`person_id`、`role_id` / `game_role_id`，允许补写，即使该对局早于 `role_info_observed_match_time`。
- 如果目标文档不缺字段，只有当 `match_time > role_info_observed_match_time` 时才更新。
- 如果目标文档不缺字段，且 `match_time <= role_info_observed_match_time`，不更新。
- 如果没有 `match_time`，只允许补缺失字段，不覆盖已有完整字段。

## 在线同步改造方案

### 1. 新增 replay 与 indicator client

执行状态：已完成。

新增或扩展 service：

- `src/services/jx3/match_replay.py`
  - `MatchReplayClient.get_match_replay(match_id)`
  - 默认 URL：`https://m.pvp.xoyo.com/3c/mine/match/replay`
  - 与 history/detail 一样复用 `tuilan_request`
- `src/services/jx3/role_indicator.py`
  - `RoleIndicatorClient.get_role_indicator(role_id, zone, server)`
  - 默认 URL：`https://m.pvp.xoyo.com/role/indicator`
  - 与 history/detail 一样复用 `tuilan_request`

返回解析：

- 只依赖 `data.players[]`
- 提取字段：
  - `role_id`
  - `role_name`
  - `kungfu_id`
  - `kungfu_name`
  - `team`

indicator 返回解析：

- 只依赖 `data.role_info` 和 `data.person_info`
- 提取字段：
  - `role_info.global_role_id`
  - `role_info.role_id`
  - `role_info.name`
  - `role_info.zone`
  - `role_info.server`
  - `person_info.person_id`

### 2. 合并 detail 与 replay 玩家

执行状态：已完成。

在 `JjcMatchDataSyncService._sync_match_detail()` 成功获取 `detail` 后：

1. 请求 replay。
2. 将 replay 玩家转为索引：
   - 优先按规范化 `role_name` 匹配。
   - `role_name` 中最后一个 `·` 右侧作为服务器后缀。
   - 若同名无法唯一匹配，记录冲突并跳过该玩家的 replay 补充。
3. 对 `extract_players_from_detail(detail)` 的每个玩家：
   - 保留 detail 中的 `person_id/server/zone/role_name`。
   - 若 replay 匹配成功，补充 `role_id`。
   - 不使用 replay 的数字 `global_role_id` 覆盖 `SK01-... global_role_id`。

### 3. 通过 indicator 补齐 SK01 global_role_id

执行状态：已完成。

对合并后的玩家执行身份补全：

1. 若玩家已有 `role_id + zone + server`，请求 `/role/indicator`。
2. 用 indicator 返回的 `role_info.global_role_id` 作为 `SK01-... global_role_id`。
3. 用 indicator 返回的 `person_info.person_id` 校验或补齐 `person_id`：
   - detail 与 indicator 均有 `person_id` 且一致，认为可信。
   - detail 无 `person_id` 时，用 indicator 补齐。
   - detail 与 indicator 的 `person_id` 不一致时，记录冲突，不覆盖已有值。
4. 用 indicator 返回的 `role_info.name/server/zone/role_id` 校验 replay/detail 合并结果：
   - `role_id + zone + server` 一致时写入。
   - 角色名不一致时记录 warning；不自动覆盖已有 `server/name`。
5. indicator 请求失败时：
   - 已有本地身份可证明 `global_role_id` 的，允许按本地身份写入缺失 `role_id`。
   - 没有 `SK01-... global_role_id` 的，不作为可执行 history 同步入口。

### 4. 写入角色身份

执行状态：已完成。

更新 `_enqueue_players_from_detail()` 或拆出新 helper：

- 将合并后的玩家传给 `_upsert_role_identity_from_resolved()`。
- 调用 `JjcSyncRepo.upsert_role()` 时传入 `global_role_id`、`role_id`、`person_id`、`zone`。
- 若已有文档缺少 `role_id`，补齐。
- 若已有文档已有 `role_id` 且与 replay 不一致，记录 warning，不自动覆盖。
- 若已有文档缺少 `global_role_id`，补齐 indicator 返回的 `SK01-... global_role_id`。
- 若已有文档已有不同 `global_role_id`，记录 conflict，不自动覆盖。
- 新增从对局发现的角色，只有在补齐 `SK01-... global_role_id` 后才进入普通可执行队列；未补齐时可记录到身份库或待补全状态，但不得被 `claim_next_roles()` 拉去执行 history 同步。

### 5. 使用对局时间判断是否更新

执行状态：已完成。在线同步沿用 `profile_observed_at`/`observed_match_time` 写入；离线脚本写入 `role_info_observed_match_time`。

写入 `role_identities` 与 `jjc_sync_role_queue` 时统一应用：

```text
should_update = missing_required_fields
             or no role_info_observed_match_time
             or match_time > role_info_observed_match_time
```

其中 `missing_required_fields` 对 `role_identities` 表示缺 `global_role_id`、`person_id`、`role_id` 或 `game_role_id`，对 `jjc_sync_role_queue` 表示缺 `global_role_id`、`person_id` 或 `role_id`。

### 6. 同步入口角色规则

执行状态：已完成。对局详情自动发现链路中，缺少 `SK01-... global_role_id` 的玩家不会写入可执行同步队列。

入口角色来源包括：

- 管理命令 `/jjc同步添加`。
- CLI `scripts/jjc_sync.py add/single`。
- 对局详情发现的参战玩家。
- 治理或审计脚本补录的角色。

统一规则：

1. `match/history` 只能用 `SK01-... global_role_id` 查询，因此普通同步队列中的可执行角色必须有 `global_role_id`。
2. 人工入口如果只提供 `server/name` 或 `role_id + zone + server`：
   - 先尝试 `/role/indicator` 补齐 `global_role_id`。
   - 若没有 `role_id`，可 fallback 到现有 inspect resolver 或 `person-history`，但补齐后才允许进入可执行队列。
3. 对局详情发现入口时：
   - 主链路为 `detail + replay + indicator`。
   - 成功补齐 `global_role_id` 后写入 `jjc_sync_role_queue`。
   - 未补齐时不写入可执行队列，避免后续同步时再失败。
4. `person-history` 只保留两类用途：
   - 兼容历史入口角色缺 `global_role_id` 的兜底。
   - 审计旧数据时用 `person_id` 找疑似遗漏角色，但写入前仍要做角色级校验。

## 离线回填脚本

脚本：`scripts/backfill_jjc_role_id_from_match_replay.py`

执行状态：已完成。

输入来源：

- `jjc_sync_match_seen`
- 默认筛选 `status="detail_saved"` 且存在 `match_id`

处理流程：

1. 分页读取已同步对局。
2. 对每个 `match_id` 请求 `/3c/mine/match/replay`。
3. 从 `players[]` 提取 `role_id` 和 `role_name`。
4. 从 `role_name` 末尾服务器后缀解析 `server`，得到规范化 `server/name`。
5. 在 `role_identities` 与 `jjc_sync_role_queue` 中查找同 `normalized_server + normalized_name` 的文档。
6. 可选请求 `/role/indicator`，用 `role_id + zone + server` 补齐 `SK01-... global_role_id` 与 `person_id`。
7. 按 `role_info_observed_match_time` 更新规则决定是否写入。
8. 默认 dry-run；只有 `--apply --yes` 写库。

写入字段：

- `role_id`
- `game_role_id`（仅 `role_identities`）
- `global_role_id`（仅 indicator 成功返回 `SK01-...` 时）
- `person_id`（仅 indicator 成功且无冲突时）
- `role_info_observed_match_time`
- `role_info_source="match_replay_indicator_backfill"` 或 `match_replay_backfill`
- `role_info_updated_at`
- `updated_at`

冲突处理：

- 如果目标文档已有不同 `role_id`，跳过并计入 conflict。
- 如果目标文档已有不同 `global_role_id`，跳过并计入 conflict。
- 如果 indicator 返回的 `person_id` 与 detail/本地已有 `person_id` 不一致，跳过该字段并计入 conflict。
- 如果 replay 玩家无法从 `role_name` 解析服务器，跳过。
- 如果同一场 replay 中规范化 `server/name` 不唯一，跳过该 key。

## 文档联动

- 更新 `docs/references/tuilan-api-reference.md`，记录 replay、detail、history、indicator 的出入参和字段限制。
- 更新 `docs/design-docs/database-design.md`，记录新增角色信息观测字段。
- 更新 `docs/references/runbook.md`，如后续把脚本纳入常规治理流程。

## 验证方案

自动化验证：

```bash
python -m py_compile scripts/backfill_jjc_role_id_from_match_replay.py
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py
```

已执行：

```bash
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/services/jx3/match_replay.py src/services/jx3/role_indicator.py src/services/jx3/singletons.py scripts/backfill_jjc_role_id_from_match_replay.py config.py
python -m unittest tests.test_jjc_match_data_sync
```

结果：通过。

手工验证：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 5 --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 5 --apply --yes
```

验收标准：

- dry-run 能输出扫描对局数、replay 成功数、候选玩家数、可更新数、跳过数和冲突数。
- apply 后，缺少 `role_id` 的角色文档被补齐。
- indicator 成功时，缺少 `SK01-... global_role_id` 的角色文档被补齐。
- 对局时间早于 `role_info_observed_match_time` 且字段完整的文档不会被更新。
- 已有不同 `role_id` 或 `global_role_id` 的文档不会被覆盖。

## 风险与回滚

- 风险：用 `role_name` 匹配 replay 玩家时遇到同名或服务器后缀缺失。
  - 缓解：同场同 key 不唯一时跳过，不强行写入。
- 风险：replay 的数字 `global_role_id` 与 `SK01-...` 不是同一体系。
  - 缓解：不使用 replay `global_role_id` 写入现有 `global_role_id` 字段。
- 风险：indicator 查询增加外部请求量。
  - 缓解：按对局玩家去重，请求失败不阻断详情保存，并保留限速 sleep。
- 风险：入口角色缺 `global_role_id` 时无法拉 history。
  - 缓解：写入可执行队列前先补齐；历史遗留数据继续在 `_sync_one_role()` 做兜底补全，补不到则失败并记录原因。
- 风险：给旧 name 身份补 `role_id` 后，`identity_key` 仍是 `name:*`。
  - 缓解：本计划不自动改 identity_key；后续身份治理阶段再评估升级。
- 回滚：
  - 可根据 `role_info_source` 为 `match_replay_indicator_backfill` 或 `match_replay_backfill`，并结合 `role_info_updated_at` 定位本次写入。
  - 如需回滚，按备份或 Mongo 查询结果清除脚本新增字段；不删除角色文档。
