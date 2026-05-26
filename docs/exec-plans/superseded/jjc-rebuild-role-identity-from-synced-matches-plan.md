# JJC 已同步对局重建角色身份与同步队列计划

> 已合并至 `docs/exec-plans/completed/jjc-role-global-id-governance-plan.md`，本文仅作历史参考。

状态：待实现
更新时间：2026-05-21

## 背景

现有 `role_identities` 与 `jjc_sync_role_queue` 中存在历史污染：

- 同一 `server/name/role_id/person_id` 可能出现多个 `global_role_id`。
- `jjc_sync_role_queue` 中同时存在 `global:*` 与 `name:*` 弱身份记录。
- 旧审计脚本基于 `person-history` 修复时曾出现冲突链和环路，继续增量修补成本高。
- 新确认的推栏链路 `match/detail + match/replay + role/indicator` 能从已同步对局重新获得更可信的 `role_id`、`SK01-... global_role_id`、`person_id`。

因此需要新增一次性临时脚本：保留已同步对局和详情缓存，先备份身份表与同步队列，再清空并从 `jjc_sync_match_seen` / `jjc_match_detail` 遍历历史对局，重新生成 `role_identities` 和 `jjc_sync_role_queue`。

## 目标

- 从已经同步过的 `detail_saved` 对局重建角色身份数据。
- 清空并重建以下集合：
  - `role_identities`
  - `jjc_sync_role_queue`
- 保留以下集合，不清空：
  - `jjc_sync_match_seen`
  - `jjc_match_detail`
  - `jjc_role_indicator`
  - `role_jjc_cache`
  - 装备/奇穴快照集合
- 重建结果中，身份主键使用 `match/replay.players[].global_role_id`，本地与 Mongo 字段命名为 `global_id`；普通可执行同步队列仍只保留当前带 `SK01-... global_role_id` 的角色。
- 不再生成 `name:*` 弱身份队列记录。
- 所有重建写库操作默认 dry-run；正式执行必须显式 `--apply --yes`。
- 备份与重建拆成两个临时脚本，先显式备份，再执行重建。
- 不把脚本接入 QQ 命令、CLI 管理命令或常驻流程；本次治理完成后可保留为手工维护脚本。
- 当前同步任务已经完全停止，脚本不强制检查或修改 `jjc_sync_state.paused`。

## 非目标

- 不重新拉取 `match/detail`。重建来源优先使用已有 `jjc_match_detail`。
- 不清空 `jjc_sync_match_seen`，避免丢失已发现对局和详情状态。
- 不清空 `jjc_match_detail`，避免重新请求大量详情。
- 不在本次自动合并 `role_jjc_cache` / `jjc_role_indicator`，这些集合只作为校验参考。
- 不使用 `/mine/match/person-history` 作为重建来源。
- 不新增 QQ 管理命令，不修改 `/jjc同步*` 入口。

## 数据来源

### 对局列表

主来源：`jjc_sync_match_seen`

筛选条件：

```json
{"status": "detail_saved", "match_id": {"$exists": true}}
```

读取字段：

- `match_id`
- `match_time`
- `status`

支持参数：

- `--limit`
- `--skip`
- `--match-id`
- `--status`，默认 `detail_saved`
- `--season-start-time`，可选；用于跳过赛季开始前对局

### 对局详情

主来源：`jjc_match_detail`

按 `match_id` 读取缓存详情。兼容两种结构：

- `doc.data.detail`
- `doc.data`

从 `team1.players_info[]` 和 `team2.players_info[]` 提取，作为 replay 合并与校验参考：

- `server`
- `role_name`
- `zone`
- `person_id`
- `kungfu` / `kungfu_id`，仅统计和诊断使用

角色名规范化规则复用 `normalize_role_name()`：

- 若 `role_name` 为 `角色名·服务器` 且后缀等于 `server`，写入纯角色名。
- 不改写 `jjc_match_detail` 原始缓存。

### 对局 replay

请求：

```text
POST https://m.pvp.xoyo.com/3c/mine/match/replay
```

入参：

```json
{"match_id": 123}
```

使用字段：

- `players[].role_id`
- `players[].global_role_id`，数字字符串，重命名为本地字段 `global_id`
- `players[].role_name`
- `players[].kungfu_id`
- `players[].kungfu_name`
- `players[].kungfu_icon`
- `players[].team`
- `players[].treat_trend` / `players[].attack_trend`，仅诊断使用，不进入身份主键

规则：

- `players[].global_role_id` 是 replay 稳定角色 ID，写入 `global_id`，作为重建身份主键；不写入 `global_role_id`，避免与 SK01 全局角色 ID 混淆。
- replay `role_name` 通常为 `角色名·服务器`，拆出当前 `name/server`；再通过服务器主数据或别名映射补齐当前 `zone`。
- 同一场对局中同一 `global_id` 对应多个不同 `role_id` 时，该 `global_id` 记为冲突并跳过。
- 同一场对局中同一 `normalized_server + normalized_name` 对应多个不同 `global_id` 时，该名字 key 只作为同名冲突输出，不作为合并依据。

### role/indicator

请求：

```text
POST https://m.pvp.xoyo.com/role/indicator
```

入参：

```json
{"role_id": "31314176", "zone": "电信区", "server": "唯我独尊"}
```

使用字段：

- `role_info.global_role_id`
- `role_info.role_id`
- `role_info.name`
- `role_info.zone`
- `role_info.server`
- `person_info.person_id`

规则：

- 只接受 `role_info.global_role_id` 以 `SK01-` 开头的结果。
- 返回 `role_info.role_id` 与 replay `role_id` 不一致时，记录 `role_id_changed`；默认仍保留该 `global_id` 对应身份，并用 indicator 返回的新 `role_id/zone/server/name/global_role_id` 更新画像字段。
- 返回 `server/name/zone` 与 replay 当前值不一致时，不按名称判定为错人；记录 `profile_changed`，以 `global_id` 为准更新当前画像字段，并把旧 `server/name/zone/role_id` 追加到历史字段。
- detail 与 indicator 均有 `person_id` 且不一致时，记录冲突；该玩家默认跳过，避免把同名角色写错。

## 输出集合设计

### `role_identities`

每个可信角色按 `global_id:{global_id}` 写一条。`global_id` 来自 `match/replay.players[].global_role_id`，是重建主键；`role_id/zone/server/name/global_role_id` 都是该稳定身份的当前画像字段，可随转服、改名或 SK01 变动而更新。

字段：

- `identity_key = global_id:{global_id}`
- `identity_level = "global_id"`
- `global_id`
- `global_role_id`
- `role_id`
- `game_role_id = role_id`
- `person_id`
- `zone`
- `server`
- `normalized_server`
- `name`
- `role_name = name`
- `normalized_name`
- `sources = ["match_replay_indicator_rebuild"]`
- `identity_source = "match_replay_indicator_rebuild"`
- `profile_observed_at`
- `first_seen_at`
- `last_seen_at`
- `updated_at`
- `role_info_observed_match_time`
- `role_info_source = "match_replay_indicator_rebuild"`
- `role_info_updated_at`
- `profile_history`，数组，记录该 `global_id` 曾出现过的 `server/name/zone/role_id/global_role_id/match_id/match_time/source`
- `schema_version`

合并规则：

- 以 `global_id` 为主键聚合。
- 同一 `global_id` 多次出现时，保留最新 `match_time` 对应的 `server/name/zone/role_id/person_id/global_role_id` 作为当前画像。
- 若同一 `global_id` 对应多个 `role_id` 或多个 `zone`，视为转服、角色 ID 迁移或数据更新，记录 `profile_history`，不拆分记录。
- 若同一 `global_id` 对应多个 `server/name`，视为改名或转服，记录 `profile_history`，不按名称拆分。
- 若同一 `global_role_id` 对应多个 `global_id`，记为 `global_role_id_global_id_conflict`；不按 SK01 `global_role_id` 合并这些角色，默认跳过这些候选的 `global_role_id` 写入，保留 `global_id` 身份记录供诊断。
- 若同一 `role_id + zone` 对应多个 `global_id`，记为 `role_id_global_id_conflict`；不按 `role_id + zone` 合并，默认保留各自 `global_id` 身份并输出冲突样本。
- 若同一 `global_id` 下出现多个互斥 `person_id`，记为 `person_id_conflict`，默认跳过该 `global_id`，避免把账号维度关系写错。

### `jjc_sync_role_queue`

每个可信角色按 `global_id:{global_id}` 写一条可执行队列。队列主键与身份表一致；`global_role_id` 作为请求 `match/history` 的当前参数字段保存。

字段：

- `identity_key = global_id:{global_id}`
- `identity_level = "global_id"`
- `global_id`
- `global_role_id`
- `role_id`
- `person_id`
- `zone`
- `server`
- `normalized_server`
- `name`
- `role_name = name`
- `normalized_name`
- `source = "match_replay_indicator_rebuild"`
- `identity_source = "match_replay_indicator_rebuild"`
- `priority = -10`
- `status = "pending"`
- `season_id`
- `season_start_time`
- `full_synced_until_time = null`
- `oldest_synced_match_time = null`
- `latest_seen_match_time = null`
- `history_exhausted = null`
- `next_sync_after = null`
- `fail_count = 0`
- `last_cursor = 0`
- `lease_owner = null`
- `lease_expires_at = null`
- `created_at`
- `updated_at`
- `role_info_observed_match_time`
- `role_info_source = "match_replay_indicator_rebuild"`
- `role_info_updated_at`
- `profile_history`

队列规则：

- 不写入 `name:*` 队列。
- 不写入旧 `global:{global_role_id}` 队列。
- 不写入缺少 `global_role_id` 的角色。
- 不写入缺少 `global_id` 的角色。
- `role_id + zone + server` 缺失时先尝试用 replay `role_name` 的服务器与服务器主数据补齐；仍缺失则只写入 `role_identities` 诊断记录，不写入可执行队列。
- 重建完成后 `claim_next_roles()` 只能领取可直接请求 `match/history` 的角色。
- 后续同步发现同一 `global_id` 的 `global_role_id/role_id/zone/server/name` 变化时，只更新字段和 `profile_history`，不改写 `identity_key`，不重置水位。

## 推栏角色入口接入范围

本次 `global_id` 不只用于一次性重建脚本。所有会从推栏接口识别、缓存或同步 JJC 角色的入口都需要检查是否能补齐 `global_id`，避免新数据继续按旧 `global_role_id` 或 `zone + role_id` 生成身份。

### 必须接入 `global_id`

这些入口会创建或更新 `role_identities`、`jjc_sync_role_queue`，或会产生后续同步队列，必须在写入前尽量通过 `match/replay` 补齐 `global_id`：

- `/竞技排名` 与每日竞技排名推送：
  - 当前链路为 `top200 -> role/indicator -> match/history -> match/detail`，不调用 `match/replay`。
  - 改造为：从 `match/history` 最近对局取可用 `match_id`，调用 `match/replay`，用 `role_id` 优先、`role_name·server` 兜底匹配当前角色，提取 replay `players[].global_role_id` 写入 `global_id`。
  - 排名统计明细成员、心法缓存 warmup、`jjc_role_indicator` 缓存和后续身份写入都要携带 `global_id`。
- JJC 对局同步：
  - 当前 `JjcMatchDataSyncService` 已在保存 detail 时调用 `match/replay` 回填 `role_id/zone/server`，但明确丢弃 replay 数字 `global_role_id`。
  - 改造为：把 replay 数字 `global_role_id` 写入玩家字段 `global_id`，后续 `_enqueue_players_from_detail()` 写 `role_identities` 与 `jjc_sync_role_queue` 时以 `global_id:{global_id}` 作为主键。
- 手工添加/单人同步入口：
  - `/jjc同步添加`、`/jjc同步单人` 若用户只提供 `server/name` 或旧 `global_role_id/role_id/zone`，在真正入队前应尝试通过现有身份缓存、`match/history + match/replay` 或后续同步 detail 补齐 `global_id`。
  - 暂时无法补齐 `global_id` 时，可以保留兼容写入，但必须标记为弱身份并在第一次拿到 replay 后迁移到 `global_id:{global_id}`，不得长期把旧 key 当最终身份。
- 角色近期/详情下钻：
  - `JjcRankingInspectService` 获取最近对局和按需详情时，如果触达 `match/detail` 或已有 `match_id`，应补调或复用 `match/replay`，把当前角色与详情玩家的 `global_id` 写回缓存。

### 可延后但必须审计

这些脚本或缓存不一定立即创建新同步队列，但会读取或修复身份字段，需要在迁移到 `global_id` 后更新查询优先级：

- `scripts/backfill_jjc_role_id_from_match_replay.py`：已有 replay 调用，应改为回填 `global_id`，再用 indicator 补 SK01 `global_role_id`。
- `scripts/audit_jjc_person_history_identity.py`：旧逻辑按 person-history 和 SK01 `global_role_id` 修复，后续应降级为冲突审计，不再按 SK01 改写主键。
- `scripts/check_role_identity_migration.py`：增加 `global_id` 唯一性、旧 `global:*` 残留、`zone + role_id` 多 `global_id` 的检查。
- `scripts/fix_jjc_ranking_weapon_names.py`：查询缓存时优先使用 `global_id`，再 fallback 到 SK01 `global_role_id` 与 `zone + game_role_id`。

### 暂不强制接入

- 只做展示、图片渲染或纯统计聚合且不写身份/队列的代码，可以只透传已有 `global_id` 字段，不主动发起额外 `match/replay` 请求。
- 对没有 `match_id` 的老缓存，不为了补 `global_id` 大规模反查外部接口；由重建脚本和后续真实同步逐步补齐。

## 临时脚本设计

新增两个临时脚本：

```text
scripts/backup_jjc_role_identity_collections.py
scripts/rebuild_jjc_role_identity_from_synced_matches.py
```

### 1. 备份脚本

脚本：

```text
scripts/backup_jjc_role_identity_collections.py
```

用途：

- 只备份 `role_identities` 与 `jjc_sync_role_queue`。
- 不清空、不修改源集合。
- 备份集合名默认带时间戳，避免覆盖。

示例：

```bash
python scripts/backup_jjc_role_identity_collections.py --dry-run
python scripts/backup_jjc_role_identity_collections.py --apply --yes
```

参数：

- `--backup-prefix`：可选；默认 `jjc_role_identity_rebuild_backup_<timestamp>`。
- `--apply`：执行备份。
- `--yes`：确认执行备份。

备份集合：

- `role_identities_rebuild_backup_<timestamp>`
- `jjc_sync_role_queue_rebuild_backup_<timestamp>`

备份元信息集合：

- `jjc_identity_rebuild_backup_meta`

元信息字段：

- `source_collection`
- `backup_collection`
- `created_at`
- `doc_count`
- `script`
- `args`

### 2. 重建脚本

脚本：

```text
scripts/rebuild_jjc_role_identity_from_synced_matches.py
```

用途：

- 从已同步对局重建 `role_identities` 与 `jjc_sync_role_queue`。
- dry-run 只生成候选和统计，不清空、不写库。
- apply 时清空 `role_identities` 与 `jjc_sync_role_queue`，再写入重建结果。
- 不负责备份；正式运行前必须先手工执行备份脚本。

参数：

```bash
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --dry-run
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --limit 100 --dry-run
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --match-id 256372723 --dry-run
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --apply --yes
```

参数列表：

- `--limit`：最多处理多少场。
- `--skip`：跳过多少场。
- `--match-id`：只处理指定对局。
- `--status`：默认 `detail_saved`；传空字符串则不过滤。
- `--sleep-min`：默认 `1.0`。
- `--sleep-max`：默认 `3.0`。
- `--apply`：正式写库。
- `--yes`：确认正式写库。
- `--no-clear`：调试参数，只生成候选、不清空目标集合；正式重建不使用。
- `--require-backup`：默认开启；apply 前检查 `jjc_identity_rebuild_backup_meta` 中存在本次指定或最近备份。
- `--backup-prefix`：可选；用于指定必须存在的备份前缀。

### dry-run 行为

dry-run 不写库，不备份，不清空。

输出统计：

- 扫描对局数
- 找到详情数 / 缺详情数
- replay 成功数 / 失败数
- indicator 成功数 / 失败数 / 跳过数
- 候选玩家数
- 有效身份数
- 将写入 `role_identities` 数
- 将写入 `jjc_sync_role_queue` 数
- 冲突数
- 跳过原因分布

输出样例：

```json
{
  "stats": {
    "matches": 100,
    "details_found": 98,
    "replay_success": 97,
    "indicator_success": 520,
    "valid_identities": 480,
    "role_identity_writes": 480,
    "queue_writes": 480,
    "conflicts": 6
  },
  "skip_reasons": {
    "detail_missing": 2,
    "replay_match_conflict": 1,
    "indicator_person_id_conflict": 3
  }
}
```

### 重建 apply 行为

正式执行必须满足：

- 参数包含 `--apply --yes`。
- 脚本不检查 `jjc_sync_state.paused`，因为当前同步已经完全停止。
- 默认检查近期是否存在 `role_identities` 与 `jjc_sync_role_queue` 备份元信息；若没有备份，拒绝执行。
- 清空 `role_identities` 与 `jjc_sync_role_queue`。
- 批量写入重建后的 `role_identities`。
- 批量写入重建后的 `jjc_sync_role_queue`。
- 写入完成后执行一致性校验。

## 一致性校验

脚本内置校验并输出结果：

1. `role_identities.identity_key` 唯一。
2. `jjc_sync_role_queue.identity_key` 唯一。
3. `role_identities` 中不存在 `identity_key` 以 `name:` 开头的记录。
4. `jjc_sync_role_queue` 中不存在 `identity_key` 以 `name:` 开头的记录。
5. `jjc_sync_role_queue` 中不存在缺 `global_role_id` 的可执行状态记录。
6. `role_identities` 中同一 `global_id` 只有一条 `global_id:{global_id}` 记录。
7. `jjc_sync_role_queue` 中同一 `global_id` 只有一条 `global_id:{global_id}` 记录。
8. `role_identities` 与 `jjc_sync_role_queue` 的 `global_role_id` 集合差异需要输出。
9. `jjc_role_indicator` / `role_jjc_cache` 中已有同 `global_id`、同 `zone + role_id` 或同 `global_role_id` 的缓存与重建结果不一致时，输出冲突样本但不自动修改缓存。
10. 同一 SK01 `global_role_id` 出现在多个 `global_id` 时输出冲突样本；该检查用于发现 SK01 漂移或历史污染，不作为合并依据。
11. 同一 `role_id + zone` 出现在多个 `global_id` 时输出冲突样本；该检查用于发现旧主键污染或区服映射错误，不作为合并依据。

若 apply 后校验失败：

- 脚本返回非 0。
- 不自动回滚，避免二次破坏。
- 输出回滚命令建议。

## 回滚方案

回滚可先用手工 Mongo 操作完成；如需要，再补单独临时恢复脚本。

最低要求：

```bash
python scripts/restore_jjc_role_identity_collections.py \
  --role-identities-backup role_identities_rebuild_backup_<timestamp> \
  --sync-role-queue-backup jjc_sync_role_queue_rebuild_backup_<timestamp> \
  --apply --yes
```

回滚行为：

1. 再次备份当前错误结果到 `*_failed_rebuild_backup_<timestamp>`。
2. 清空 `role_identities` 与 `jjc_sync_role_queue`。
3. 从指定备份集合恢复。
4. 校验恢复后文档数与备份文档数一致。

如果先不实现恢复脚本，备份脚本和重建脚本必须在 apply 输出中打印手工回滚步骤。

## 运行步骤

### 1. 确认同步已停止

当前同步任务已经完全停止，本计划不要求脚本再接入暂停命令。执行前人工确认没有正在运行的 `/jjc同步开始`、后台同步或相关脚本即可。

### 2. 备份

```bash
python scripts/backup_jjc_role_identity_collections.py --dry-run
python scripts/backup_jjc_role_identity_collections.py --apply --yes
```

### 3. 小样本 dry-run

```bash
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --limit 20 --dry-run
```

检查：

- replay / indicator 成功率。
- 冲突样本是否符合预期。
- 是否仍出现大量同名冲突。

### 4. 指定冲突对局 dry-run

```bash
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --match-id 256372723 --dry-run
```

检查类似 `唯我独尊/江南气纯` 的污染样本是否会被重建为 indicator 返回的 `SK01-IDC...`。

### 5. 全量 dry-run

```bash
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --sleep-min 1 --sleep-max 3 --dry-run
```

### 6. 正式 apply

```bash
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --sleep-min 1 --sleep-max 3 --apply --yes
```

### 7. 复查

不自动恢复同步；本次目标只是完成身份表与同步队列重建。

## 验证方案

自动化验证：

```bash
python -m py_compile scripts/rebuild_jjc_role_identity_from_synced_matches.py
python -m py_compile scripts/backup_jjc_role_identity_collections.py
```

脚本 dry-run 验证：

```bash
python scripts/rebuild_jjc_role_identity_from_synced_matches.py --limit 5 --sleep-min 0 --sleep-max 0 --dry-run
```

Mongo 校验查询：

```javascript
db.role_identities.countDocuments({identity_key: /^name:/})
db.jjc_sync_role_queue.countDocuments({identity_key: /^name:/})
db.role_identities.countDocuments({identity_key: /^global:/})
db.jjc_sync_role_queue.countDocuments({identity_key: /^global:/})
db.role_identities.countDocuments({global_id: {$exists: false}})
db.jjc_sync_role_queue.countDocuments({global_id: {$exists: false}})
db.jjc_sync_role_queue.countDocuments({
  status: {$in: ["pending", "cooldown", "exhausted"]},
  $or: [{global_role_id: {$exists: false}}, {global_role_id: ""}, {global_role_id: null}]
})
```

验收标准：

- dry-run 能稳定生成候选身份和冲突统计。
- 备份脚本会创建备份集合和备份元信息。
- apply 前必须能检查到符合要求的备份元信息。
- apply 后 `role_identities` 与 `jjc_sync_role_queue` 不再有 `name:*` 记录。
- apply 后 `role_identities` 与 `jjc_sync_role_queue` 不再有旧 `global:*` 主键记录，身份主键统一为 `global_id:{global_id}`。
- apply 后可执行队列记录均有 `SK01-... global_role_id`。
- `唯我独尊/江南气纯` 这类样本以 `/role/indicator` 返回的 `SK01-IDC...` 为准重建，不保留 `SK01-RY...` 污染身份。
- `python -m py_compile` 通过。

## 风险与缓解

- 风险：清空目标集合后重建中断。
  - 缓解：先显式执行备份脚本；重建脚本 apply 前检查备份元信息；写入候选先在内存/临时结构生成完成，再清空正式集合。
- 风险：外部接口限流或失败导致重建身份不完整。
  - 缓解：默认 dry-run；apply 前先全量 dry-run；请求间默认随机 sleep 1 到 3 秒；失败样本统计输出。
- 风险：已同步详情缓存本身有旧名字或缺 `zone`。
  - 缓解：以 replay + indicator 为准；缺关键字段的玩家跳过，不写入可执行队列。
- 风险：同名同服不同角色被误合并。
  - 缓解：最终身份以 replay `global_id` 为准，不以 `server/name`、`role_id + zone` 或 SK01 `global_role_id` 作为最终主键。
- 风险：重建后队列同步水位丢失，可能重新遍历历史。
  - 缓解：这是本计划接受的代价；`jjc_sync_match_seen` 保留，已同步 match 详情不会重复保存，只会补齐角色后继续发现缺失对局。
- 风险：缓存集合仍保留旧 global 引用。
  - 缓解：本计划只输出冲突样本，不修改缓存；后续若需要，再制定缓存清理计划。
