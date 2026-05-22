# JJC 角色 global_id 身份治理总体计划

状态：阶段 1/2/4/5 已完成首轮实现与离线验证；阶段 3 一次性重建脚本仍待落地
更新时间：2026-05-21

## 背景

JJC 角色身份相关方案此前分散在多份 active 计划中：

- `jjc-match-replay-role-id-backfill-plan.md`：已实现 replay + indicator 补齐 `role_id` / SK01 `global_role_id` 的第一轮止血。
- `jjc-role-identity-governance-plan.md`：规划把身份匹配、审计分类和 key 构造收敛到共享规则。
- `jjc-rebuild-role-identity-from-synced-matches-plan.md`：规划从已同步对局重建 `role_identities` 与 `jjc_sync_role_queue`。
- `jjc-audit-conflict-chain-cycle-plan.md`：修复旧审计脚本冲突链环路，属于历史修复子项。

最新接口验证确认：`/3c/mine/match/replay` 的 `players[].global_role_id` 是数字字符串，可与 replay 事件里的 `casterId/targetId` 对齐；它不是 SK01 `global_role_id`。后续本地和 Mongo 统一命名为 `global_id`，作为 JJC 角色稳定身份主键。

## 总目标

- 将 JJC 角色最终身份主键统一为 `global_id:{global_id}`。
- 将 replay 数字 `players[].global_role_id` 落库为 `global_id`，不再与 SK01 `global_role_id` 混用。
- `role_id`、`zone`、`server`、`name`、SK01 `global_role_id` 都作为同一 `global_id` 的当前画像字段，可随转服、改名、角色 ID 迁移或 SK01 变化更新。
- 所有会识别、缓存或同步推栏 JJC 角色的入口都要检查并尽量补齐 `global_id`，避免新数据继续按旧 `global_role_id` 或 `zone + role_id` 生成身份。
- 清空并重建 `role_identities` 与 `jjc_sync_role_queue`，移除 `name:*` 与旧 `global:*` 主键记录。
- 保留已同步对局、详情缓存、indicator 缓存和装备/奇穴快照，不重新大规模拉取 detail。
- 将线上同步、排名统计、角色近期、离线审计和回填脚本逐步收敛到同一套身份规则。

## 非目标

- 不把 replay 的数字 `global_id` 当作 SK01 `global_role_id` 请求 `match/history`。
- 不清空 `jjc_sync_match_seen`、`jjc_match_detail`、`jjc_role_indicator`、`role_jjc_cache` 或装备/奇穴快照集合。
- 不使用 `/mine/match/person-history` 作为重建主来源；只保留为入口角色缺身份时的兼容 fallback。
- 不新增 QQ 管理命令；临时治理脚本只做手工维护入口。
- 不为了没有 `match_id` 的老缓存大规模反查外部接口；由重建脚本和后续真实同步逐步补齐。

## 核心身份模型

### 字段语义

`role_identities` 与 `jjc_sync_role_queue` 统一包含：

| 字段 | 含义 |
|---|---|
| `identity_key` | `global_id:{global_id}` |
| `identity_level` | 固定为 `global_id` |
| `global_id` | replay 数字稳定角色 ID，来自 `match/replay.players[].global_role_id` |
| `global_role_id` | SK01 全局角色 ID，用于请求 `match/history` |
| `role_id` / `game_role_id` | 当前推栏角色 ID |
| `zone` | 当前大区。优先 indicator 返回；也可由 replay `role_name` 拆出的服务器映射得到 |
| `server` / `name` | 当前服务器和角色名 |
| `person_id` | 当前账号/人物关联 ID，仅作为校验字段 |
| `profile_history` | 当前 `global_id` 曾出现过的 `server/name/zone/role_id/global_role_id/match_id/match_time/source` |
| `role_info_observed_match_time` | 最近一次用于更新角色身份画像的对局时间 |
| `role_info_source` | 画像来源，如 `match_replay_indicator_rebuild` |
| `role_info_updated_at` | 写入时间 |

### 合并规则

- 以 `global_id` 为唯一主键聚合。
- 同一 `global_id` 多次出现时，保留最新 `match_time` 对应的 `server/name/zone/role_id/person_id/global_role_id` 为当前画像。
- 同一 `global_id` 对应多个 `role_id`、`zone`、`server/name` 时，视为转服、改名、角色 ID 迁移或接口画像变化，记录 `profile_history`，不拆分记录。
- 同一 SK01 `global_role_id` 对应多个 `global_id` 时，记为 `global_role_id_global_id_conflict`，不按 SK01 合并。
- 同一 `role_id + zone` 对应多个 `global_id` 时，记为 `role_id_global_id_conflict`，不按旧主键合并。
- 同一 `global_id` 下出现多个互斥 `person_id` 时，记为 `person_id_conflict`，默认跳过该 `global_id`，避免把账号维度关系写错。

## 推栏入口接入范围

### 必须接入

这些入口会创建或更新身份、缓存或同步队列，必须尽量补齐 `global_id`：

- `/竞技排名` 与每日竞技排名推送：
  - 当前链路为 `top200 -> role/indicator -> match/history -> match/detail`，不调用 `match/replay`。
  - 改造为：从 `match/history` 最近对局取可用 `match_id`，调用 `match/replay`，用 `role_id` 优先、`role_name·server` 兜底匹配当前角色，提取 replay `players[].global_role_id` 写入 `global_id`。
  - 排名统计明细成员、心法缓存 warmup、`jjc_role_indicator` 缓存和后续身份写入都要携带 `global_id`。
- JJC 对局同步：
  - 当前 `JjcMatchDataSyncService` 已在保存 detail 时调用 `match/replay` 回填 `role_id/zone/server`，但丢弃 replay 数字 `global_role_id`。
  - 改为把 replay 数字 `global_role_id` 写入玩家字段 `global_id`，后续写 `role_identities` 与 `jjc_sync_role_queue` 时使用 `global_id:{global_id}`。
- `/jjc同步添加`、`/jjc同步单人`：
  - 若用户只提供 `server/name` 或旧 `global_role_id/role_id/zone`，入队前尝试通过现有身份缓存、`match/history + match/replay` 或后续同步 detail 补齐 `global_id`。
  - 暂时无法补齐 `global_id` 时可保留兼容弱身份，但必须标记并在第一次拿到 replay 后迁移到 `global_id:{global_id}`。
- 角色近期/详情下钻：
  - 获取最近对局和按需详情时，如果已有 `match_id` 或触达 `match/detail`，应补调或复用 `match/replay`，把当前角色与详情玩家的 `global_id` 写回缓存。

### 保留的辅助脚本

- `scripts/backfill_jjc_role_id_from_match_replay.py`：改为回填 `global_id`，再用 indicator 补 SK01 `global_role_id`。
- 临时审计、检查、修复脚本已在脚本清理计划中删除，不再作为线上操作入口。

## 数据来源

### 已同步对局

主来源：`jjc_sync_match_seen`

筛选条件：

```json
{"status": "detail_saved", "match_id": {"$exists": true}}
```

读取字段：

- `match_id`
- `match_time`
- `status`

### 对局详情

主来源：`jjc_match_detail`，兼容 `doc.data.detail` 与 `doc.data`。

从 `team1.players_info[]` 和 `team2.players_info[]` 提取：

- `server`
- `role_name`
- `zone`
- `person_id`
- `kungfu` / `kungfu_id`，仅统计和诊断使用

### 对局 replay

请求：

```text
POST https://m.pvp.xoyo.com/3c/mine/match/replay
```

使用字段：

- `players[].role_id`
- `players[].global_role_id` -> `global_id`
- `players[].role_name`
- `players[].kungfu_id`
- `players[].kungfu_name`
- `players[].kungfu_icon`
- `players[].team`
- `players[].treat_trend` / `players[].attack_trend`，仅诊断使用

规则：

- replay `role_name` 通常为 `角色名·服务器`，拆出当前 `name/server`，再通过服务器主数据或别名映射补齐 `zone`。
- 同一场对局中同一 `global_id` 对应多个不同 `role_id` 时，该 `global_id` 记为冲突并跳过。
- 同一场对局中同一 `normalized_server + normalized_name` 对应多个不同 `global_id` 时，只作为同名冲突输出，不作为合并依据。

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
- 返回 `role_info.role_id` 与 replay `role_id` 不一致时，记录 `role_id_changed`；默认保留 `global_id` 身份，并用 indicator 返回的新画像更新字段。
- 返回 `server/name/zone` 与 replay 当前值不一致时，不按名称判定为错人；记录 `profile_changed`，以 `global_id` 为准更新当前画像并写入 `profile_history`。
- detail 与 indicator 均有 `person_id` 且不一致时，记录冲突；该玩家默认跳过。

## 分阶段实施

### 阶段 0：保留已完成止血改造

已完成内容来自旧 `jjc-match-replay-role-id-backfill-plan.md`：

- 新增 `MatchReplayClient` 与 `RoleIndicatorClient`。
- 对局同步保存 detail 时额外请求 replay。
- 用 replay `role_id` + detail/服务器信息请求 indicator，补 SK01 `global_role_id`、`role_id`、`person_id`。
- 缺 SK01 `global_role_id` 的玩家不写入可执行队列。
- 用对局时间控制画像字段覆盖。

这些改造保留，但要在后续阶段把 replay 数字 `global_role_id` 改为 `global_id` 并纳入主键。

### 阶段 1：抽取身份规则模块

状态：已实现并通过验证。

新增：

- `src/services/jx3/role_identity_matching.py`
- `tests/test_role_identity_matching.py`

职责：

- replay 玩家解析：`global_id`、`role_id`、`role_name` 拆分、服务器和大区补齐。
- indicator 结果解析：SK01 `global_role_id`、当前 `role_id/zone/server/name/person_id`。
- 身份 key 构造：优先 `global_id:{global_id}`；弱身份仅作为兼容状态。
- 冲突分类：`global_id_conflict`、`global_role_id_global_id_conflict`、`role_id_global_id_conflict`、`person_id_conflict`、`profile_changed`。
- `profile_history` 生成与去重。

验证：

```bash
python -m unittest tests.test_role_identity_matching
python -m py_compile src/services/jx3/role_identity_matching.py
```

### 阶段 2：改造在线入口防回流

状态：已完成首轮实现。已覆盖仓储 `global_id` 查询/写入、对局同步 replay 合并、完整 replay 原始响应落 `jjc_match_detail.data.replay`、竞技排名 replay 补齐、角色近期/详情下钻 replay 补齐、缓存查询和 Mongo 索引初始化；手工添加/单人同步保留弱身份兼容，首次拿到 `global_id` 后迁移主键。

涉及文件：

- `src/services/jx3/jjc_match_data_sync.py`
- `src/services/jx3/jjc_ranking.py`
- `src/services/jx3/kungfu.py`
- `src/services/jx3/jjc_ranking_inspect.py`
- `src/storage/mongo_repos/role_identity_repo.py`
- `src/storage/mongo_repos/jjc_sync_repo.py`
- `src/storage/mongo_repos/role_jjc_cache_repo.py`
- `src/storage/mongo_repos/jjc_inspect_repo.py`
- `src/services/jx3/singletons.py`

改造点：

- 仓储新增 `global_id` 字段读写与查询，`identity_key` 生成改为优先 `global_id:{global_id}`。
- JJC 对局同步保存 detail 后，将 replay 数字 ID 写入 `global_id` 并随玩家入库。
- JJC 对局详情缓存同步保存完整 replay 原始响应到 `jjc_match_detail.data.replay`，后续页面点击优先复用缓存，不重复请求 replay。
- `/竞技排名` 与每日推送从 `match/history` 最近对局补调 replay，给排名成员、心法缓存和 indicator 缓存补 `global_id`。
- 角色近期/详情下钻在可得 `match_id` 时复用 replay 补 `global_id`。
- 手工添加和单人同步保留弱身份兼容，但首次拿到 `global_id` 后迁移主键并保留水位。
- 缓存查询优先级调整为：`global_id` > SK01 `global_role_id` > `zone + role_id` > `server + name`。

验证：

```bash
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_role_identity_repo tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/services/jx3/jjc_ranking.py src/services/jx3/kungfu.py src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py
```

### 阶段 3：一次性重建身份与同步队列

状态：一次性重建正式脚本未落地；备份、清理、恢复类临时脚本已删除，不再保留为运行手册入口。

重建行为：

- dry-run 只生成候选、冲突和统计，不写库。
- apply 必须显式 `--apply --yes`，并检查近期备份元信息。
- apply 时清空 `role_identities` 与 `jjc_sync_role_queue`，再写入 `global_id:{global_id}` 结果。
- 不清空 `jjc_sync_match_seen` 与 `jjc_match_detail`。
- 可执行队列只写入同时具备 `global_id` 与 SK01 `global_role_id` 的角色。
- 写入 `profile_history`，保留转服/改名/role_id 变化证据。

如后续仍需重建身份表，应重新编写有计划约束的新脚本，并同步新的备份与回滚方案。

### 阶段 4：离线脚本和审计收敛

状态：已完成首轮实现。

- `scripts/backfill_jjc_role_id_from_match_replay.py` 改为补 `global_id`，不再只补 `role_id`。（已实现：replay 数字 `players[].global_role_id` 写入 `global_id`，SK01 `global_role_id` 仍由 indicator 补齐）
- `scripts/backfill_jjc_role_id_from_match_replay.py` 在清空 `role_identities` / `jjc_sync_role_queue` 后也要能从已同步 `jjc_match_detail.data.detail` 与实时 replay 重建身份；当目标文档不存在时，按 replay `global_id` 新建 `role_identities`，并在已补到 SK01 `global_role_id` 时新建可执行的 `jjc_sync_role_queue`。
- `scripts/backfill_jjc_role_id_from_match_replay.py` 每次 replay 成功后写回 `jjc_match_detail.data.replay`，后续页面点击和重跑脚本可复用缓存。
- `scripts/backfill_jjc_role_id_from_match_replay.py` 支持按排序后的 1-based 闭区间分批处理：`--start N --end M`，例如 `--start 21 --end 40` 处理第 21 到 40 条；与 `--match-id` 互斥。
- 临时审计、核验和缓存修复脚本已删除；后续如需要重新检查数据，应新建独立计划和脚本。

### 阶段 5：文档与数据库设计同步

状态：已完成首轮同步。

必须更新：

- `docs/design-docs/database-design.md`（已同步：`global_id` 字段、主键策略、索引策略）
- `docs/references/runbook.md`（已同步：回填与核验命令、`global_id` / SK01 `global_role_id` 语义）
- 如 API 或前端展示新增 `global_id`，同步更新对应 README 或前端说明。

数据库设计至少补充：

- `role_identities.global_id`
- `jjc_sync_role_queue.global_id`
- 相关缓存集合可选 `global_id`
- 唯一/普通索引策略
- 旧 `global:*`、`name:*` 主键迁移规则

## 一致性校验

脚本内置或手工 Mongo 校验：

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

检查项：

- `role_identities.identity_key` 唯一。
- `jjc_sync_role_queue.identity_key` 唯一。
- 同一 `global_id` 只有一条 `global_id:{global_id}` 记录。
- 同一 SK01 `global_role_id` 出现在多个 `global_id` 时输出样本，不自动合并。
- 同一 `role_id + zone` 出现在多个 `global_id` 时输出样本，不自动合并。
- `role_identities` 与 `jjc_sync_role_queue` 的 SK01 `global_role_id` 集合差异需要输出。
- `jjc_role_indicator` / `role_jjc_cache` 中已有同 `global_id`、同 `zone + role_id` 或同 SK01 `global_role_id` 的缓存与重建结果不一致时，输出冲突样本但不自动修改缓存。

## 总体验证

自动化验证：

```bash
python -m unittest tests.test_role_identity_matching
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_role_identity_repo tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/services/jx3/jjc_ranking.py src/services/jx3/kungfu.py src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py
python -m py_compile scripts/backfill_jjc_role_id_from_match_replay.py
```

本轮已执行：

```bash
python -m py_compile src/services/jx3/role_identity_matching.py src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py src/storage/mongo_repos/role_jjc_cache_repo.py src/storage/mongo_repos/jjc_inspect_repo.py src/services/jx3/jjc_cache_repo.py src/services/jx3/jjc_match_data_sync.py src/services/jx3/jjc_ranking.py src/services/jx3/kungfu.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/singletons.py src/infra/mongo.py scripts/backfill_jjc_role_id_from_match_replay.py
python -m unittest tests.test_role_identity_matching tests.test_role_identity_repo tests.test_jjc_sync_repo tests.test_jjc_match_data_sync tests.test_jjc_kungfu_global_id
python -m unittest tests.test_jjc_ranking_inspect.TestJjcRankingInspectRoleRecent.test_role_recent_resolves_replay_global_id_into_identity_hints tests.test_jjc_ranking_inspect.TestJjcRankingInspectRoleRecent.test_cached_match_detail_is_enriched_with_replay_global_id tests.test_jjc_ranking_inspect.TestRankingWarmupInspectCache.test_warmup_writes_indicator_and_match_detail_cache tests.test_jjc_kungfu_global_id tests.test_jjc_match_detail_hydration tests.test_jjc_weapon_quality
git diff --check -- src/services/jx3/role_identity_matching.py src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py src/storage/mongo_repos/role_jjc_cache_repo.py src/storage/mongo_repos/jjc_inspect_repo.py src/services/jx3/jjc_cache_repo.py src/services/jx3/jjc_match_data_sync.py src/services/jx3/jjc_ranking.py src/services/jx3/kungfu.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/singletons.py src/infra/mongo.py scripts/backfill_jjc_role_id_from_match_replay.py docs/design-docs/database-design.md docs/references/runbook.md docs/exec-plans/active/jjc-role-global-id-governance-plan.md
```

说明：完整 `tests.test_jjc_ranking_inspect` 此前在既有 endpoint lock 并发测试处超过 10 秒未结束，本轮使用与 `global_id` 改造相关的 focused tests 覆盖。

手工验证：

- `/竞技排名 debug` 输出仍能生成心法统计，排名成员携带 `global_id`。
- 每日竞技排名推送仍能生成统计并保存 Mongo 明细。
- `/jjc同步单人 <服务器> <角色名>` 能同步已有 SK01 `global_role_id` 的角色，首次 replay 后写入 `global_id`。
- 角色近期/详情下钻能复用或补齐 replay `global_id`。
- 重建 dry-run 能输出候选数、冲突数和跳过原因。

## 回滚

- 阶段 1/2 代码回滚：恢复相关 service/repo/script 改动；保留新增字段不影响旧代码读取。
- 阶段 3 apply 回滚：
  1. 再次备份当前错误结果到 `*_failed_rebuild_backup_<timestamp>`。
  2. 清空 `role_identities` 与 `jjc_sync_role_queue`。
  3. 从指定备份集合恢复。
  4. 校验恢复后文档数与备份文档数一致。
- 不自动回滚重建结果，避免二次破坏；脚本失败时返回非 0 并打印手工回滚步骤。

## 风险与缓解

- 风险：`match/replay` 请求量增加。
  - 缓解：只在需要写身份/队列或有 `match_id` 的缓存路径补齐；纯展示路径只透传已有字段。
- 风险：转服/改名被误判为冲突。
  - 缓解：以 replay `global_id` 为准，将 `role_id/zone/server/name` 变化写入 `profile_history`。
- 风险：SK01 `global_role_id` 与 `global_id` 多对多。
  - 缓解：SK01 只作为 history 请求字段和冲突校验，不作为合并主键。
- 风险：清空目标集合后重建中断。
  - 缓解：先显式备份；apply 前检查备份；候选在内存/临时结构生成完成后再清空正式集合。
- 风险：缓存集合仍保留旧身份引用。
  - 缓解：本计划先输出冲突样本，不自动修改缓存；必要时另行制定缓存清理计划。

## 被合并的原计划

以下计划已合并到本文，原文移至 `docs/exec-plans/superseded/` 作为历史记录：

- `jjc-role-identity-governance-plan.md`
- `jjc-match-replay-role-id-backfill-plan.md`
- `jjc-rebuild-role-identity-from-synced-matches-plan.md`
- `jjc-audit-conflict-chain-cycle-plan.md`
