# JJC 角色身份表 schema 归一化计划

状态：已完成并归档
更新时间：2026-05-22

## 背景

线上 `role_identities` 已同时存在两类主要写入来源：

- `sources` 包含 `indicator`：由 `RoleIdentityRepo.upsert_from_indicator()` 经线上 service/repo 路径写入。
- `sources` 包含 `match_replay_indicator_backfill`：由 `scripts/backfill_jjc_role_id_from_match_replay.py` 直接写库写入。

2026-05-22 只读抽样和聚合结果：

| 分组 | 数量 | 主要现象 |
|---|---:|---|
| `sources: indicator` | 约 237 | 时间字段多为 `datetime`；`person_id` 缺失多；`created_at` 多数不存在；`profile_history` 由共享函数构造，空字段较少 |
| `sources: match_replay_indicator_backfill` | 约 1945 | `updated_at` / `created_at` / `role_info_updated_at` 多为 float；`person_id` 更完整；`profile_history` 手工拼装，可能包含 `person_id: null` |

精确差异样本：

- `indicator`
  - `person_id` 缺失约 209/237。
  - `created_at` 缺失约 234/237。
  - `updated_at` 主要为 `datetime`，少量被 backfill 更新后变为 float。
  - `profile_history[].observed_at` 为 `datetime`。
- `match_replay_indicator_backfill`
  - `person_id` 缺失约 118/1945。
  - `created_at` 全部存在且为 float。
  - `updated_at` 多数为 float。
  - `role_info_updated_at` 全部为 float。
  - `profile_history[].observed_at` 为 `datetime`，但 entry 手工拼字段，不复用共享过滤规则。

造成差异的直接原因：

- `indicator` 路径走 `RoleIdentityRepo`，使用 `datetime.now(timezone.utc)` 和 `build_profile_history_entry()`；但 `upsert_from_indicator()` 当前没有 `person_id` 参数，调用方也没有传递 `person_info.person_id`。
- `match_replay_indicator_backfill` 路径绕过 `RoleIdentityRepo`，脚本直接 `insert_one/update_one`，用 `time.time()` 写 `updated_at` / `created_at`，并手工拼 `profile_history`。

## 目标

- 统一 `role_identities` 的字段类型和必填/可选语义。
- 让线上 service/repo 写入路径和离线 backfill 脚本写入同一类文档结构。
- 修复 indicator 路径缺少 `person_id` 的问题。
- 修复 backfill 路径时间字段类型和 `profile_history` 构造不一致的问题。
- 提供线上只读检查、dry-run 规范化和 apply 规范化脚本，避免手工 Mongo 修改。

## 非目标

- 不改变 `global_id:{global_id}` 作为最终身份主键。
- 不重建 `role_identities` / `jjc_sync_role_queue`。
- 不清理 `jjc_match_detail`、`jjc_sync_match_seen`、`role_jjc_cache`、`jjc_role_indicator`。
- 不在本计划中处理 JJC 排名统计 Mongo 迁移。
- 不把 `created_at` 作为 `role_identities` 的必需字段；只做兼容处理。

## 正确 schema 口径

以 `docs/design-docs/database-design.md` 和 `RoleIdentityRepo` 为准：

| 字段 | 正确类型 | 说明 |
|---|---|---|
| `identity_key` | string | 业务唯一，JJC 新数据优先 `global_id:{global_id}` |
| `identity_level` | string | 新数据优先 `global_id` |
| `server` / `normalized_server` / `name` / `normalized_name` | string | 当前角色画像 |
| `zone` | string/null | 当前大区 |
| `role_id` / `game_role_id` | string/null | 当前推栏角色 ID |
| `global_id` | string/null | replay 数字稳定 ID |
| `global_role_id` | string/null | SK01，全局战绩 history 请求字段 |
| `person_id` | string/null | 可选，但能从 indicator/person_info 或 detail 得到时应写入 |
| `aliases` | array | 旧 key 和兼容 key |
| `sources` | array | 观察来源集合 |
| `profile_observed_at` | datetime | 当前画像观测时间 |
| `profile_history` | array | 使用 `build_profile_history_entry()` 构造；不写空字段 |
| `first_seen_at` / `last_seen_at` / `updated_at` | datetime | 仓储时间字段 |
| `role_info_observed_match_time` | int/null | 对局来源画像覆盖水位 |
| `role_info_source` | string/null | 最近画像来源 |
| `role_info_updated_at` | float/null | 最近画像字段写入 Unix 秒 |
| `schema_version` | int | 当前为 1 |

`created_at`：

- `role_identities` 设计文档未将其列为标准字段。
- 线上已有 float `created_at` 不影响读取，但不应作为后续新写入必需字段。
- 若保留历史字段，规范化脚本可选择把 float 转为 datetime；更推荐后续新写入不再新增该字段，避免和 `first_seen_at` 重复。

## 改造方案

### 1. 修复 indicator 写入链路

涉及文件：

- `src/services/jx3/role_indicator.py`
- `src/services/jx3/jjc_cache_repo.py`
- `src/storage/mongo_repos/role_identity_repo.py`
- `src/services/jx3/jjc_ranking_inspect.py`
- `tests/test_role_identity_repo.py`

方案：

- `RoleIdentityRepo.upsert_from_indicator()` 增加 `person_id: Optional[str] = None` 参数，并传入 `_upsert_identity()`。
- `JjcCacheRepo.upsert_from_indicator()` 增加 `person_id` 参数并透传。
- 所有解析 `/role/indicator` 的入口，从 `data.person_info.person_id` 提取 `person_id`。
- 对 indicator 来源仍按时间保护计划处理：没有 `observed_match_time` 时只补缺失字段，不覆盖已有当前画像。
- 单测覆盖：
  - 新建 indicator 身份时写入 `person_id`。
  - 已有身份缺 `person_id` 时 indicator 可补齐。
  - 已有身份有不同 `person_id` 时不静默覆盖，按现有冲突/时间保护规则处理。

### 2. 修复 backfill 写入结构

涉及文件：

- `scripts/backfill_jjc_role_id_from_match_replay.py`
- `tests/test_backfill_jjc_role_id_from_match_replay.py`

方案：

- 引入并复用 `build_profile_history_entry()` 构造 `profile_history`。
- 新建 `role_identities` 时：
  - `profile_observed_at`、`first_seen_at`、`last_seen_at`、`updated_at` 使用 `datetime`。
  - 不再新增 float `created_at`；如确需保留，使用 `datetime`。
  - `role_info_updated_at` 保持 float，与设计文档一致。
  - `person_id` 没有值时不写字段或写 `None`，但 `profile_history` entry 不写 `person_id: None`。
- 更新已有 `role_identities` 时：
  - `updated_at` 使用 `datetime`。
  - `role_info_updated_at` 保持 float。
  - `$addToSet.profile_history` 使用共享函数构造。
- `jjc_sync_role_queue` 仍可使用 float `updated_at/created_at`，因为队列集合设计当前使用运行时 Unix 秒；不要把队列规则误套到身份表。

### 3. 线上规范化脚本

状态：该一次性规范化脚本已在脚本清理计划中删除，不再作为线上操作入口。历史 schema 差异后续如需处理，应重新立项并编写新的受控脚本。

功能：

- 默认 dry-run，只输出统计和样本。
- `--apply --yes` 后才写库。
- 支持 `--source indicator`、`--source match_replay_indicator_backfill`、`--source all`。
- 支持 `--limit`、`--skip`、`--identity-key`。
- 对 `role_identities` 执行：
  - `updated_at` float → `datetime`。
  - `created_at` float → 可选移除或转 `datetime`；默认 dry-run 报告，apply 时按参数控制。
  - `first_seen_at` / `last_seen_at` 若异常为 float，转 `datetime`。
  - `profile_history[]` 清理空值字段，保留已有有效字段。
  - 缺 `person_id` 不凭空补；只在文档已有 `profile_history.person_id` 或后续 indicator 入口再次观察到时补。
- 输出：
  - 扫描数、需修复数、实际更新数。
  - 各字段类型分布前后对比。
  - 无法修复或冲突样本。

安全约束：

- 不修改 `identity_key`。
- 不修改 `global_id`、`global_role_id`、`role_id`、`game_role_id`、`zone`、`server`、`name` 等画像值。
- 不合并文档。
- 每条更新只做 schema 类型和 history 空字段清理。

### 4. 数据库设计文档同步

涉及文件：

- `docs/design-docs/database-design.md`
- `docs/references/jjc-global-id-online-runbook.md`

方案：

- 明确 `role_identities.updated_at` 是 `datetime`。
- 明确 `role_info_updated_at` 是 float Unix 秒。
- 明确 `created_at` 非标准必需字段，历史数据可存在但新写入不依赖。
- 不再保留 `normalize_jjc_role_identity_schema.py` 的线上操作步骤。

## 验证方案

自动化验证：

```bash
python -m unittest tests.test_role_identity_repo tests.test_backfill_jjc_role_id_from_match_replay
python -m py_compile src/storage/mongo_repos/role_identity_repo.py src/services/jx3/jjc_cache_repo.py scripts/backfill_jjc_role_id_from_match_replay.py
```

Mongo 抽样检查：

```javascript
db.role_identities.countDocuments({updated_at: {$type: "double"}})
db.role_identities.countDocuments({first_seen_at: {$type: "double"}})
db.role_identities.countDocuments({last_seen_at: {$type: "double"}})
db.role_identities.countDocuments({"profile_history.person_id": null})
db.role_identities.countDocuments({sources: "indicator", person_id: {$exists: false}})
```

手工回归：

- 触发一次角色 indicator 解析，确认新写入/更新的 `role_identities.person_id` 能从 `person_info.person_id` 补齐。
- 跑一小批 backfill dry-run，确认新建 identity 的 `updated_at` 是 datetime，`role_info_updated_at` 是 float。
- 页面角色近期和对局详情仍能按 `global_id` 命中身份。

## 线上执行步骤

一次性规范化脚本、备份恢复脚本和检查脚本已删除；不再提供线上执行步骤。

## 回滚

- 代码回滚：回退本计划涉及的 repo/service/script 改动。
- 数据回滚：脚本已删除，不再提供自动恢复路径；如需处理历史数据，先重新制定数据操作计划。

## 风险与缓解

- 风险：规范化脚本误改画像字段。
  - 缓解：脚本只允许修改时间类型、`created_at`、`profile_history` 空字段；不修改身份值。
- 风险：indicator 路径补 `person_id` 后与已有 person_id 冲突。
  - 缓解：沿用时间保护和冲突规则，不静默覆盖不同非空值。
- 风险：历史 float `updated_at` 被业务当 Unix 秒读取。
  - 缓解：当前 repo 设计和文档均以 datetime 为准；修改前用 rg 确认读取方，必要时兼容 datetime/float。
- 风险：`created_at` 处理口径影响外部脚本。
  - 缓解：第一版脚本默认只报告 `created_at`，是否移除或转 datetime 通过参数显式控制。

## 执行记录

- 2026-05-22：已修复 indicator 写入链路，支持从 `person_info.person_id` 透传并写入 `role_identities.person_id`。
- 2026-05-22：已修复 `scripts/backfill_jjc_role_id_from_match_replay.py` 写入结构，`role_identities.updated_at` 等仓储时间字段改为 datetime，`role_info_updated_at` 继续保留 Unix 秒；`profile_history` 改为复用 `build_profile_history_entry()`。
- 2026-05-22：曾新增 `scripts/normalize_jjc_role_identity_schema.py` 处理历史 schema 类型差异；后续脚本清理计划已删除该一次性脚本。
- 2026-05-22：已将分段回填排序改为 `match_time desc, match_id desc`，避免同一秒多场对局时分页窗口不稳定。
- 2026-05-22：已通过身份相关单测、`py_compile` 和相关文件 `git diff --check`。
- 2026-05-22：相关代码和脚本清理已提交，计划归档到 completed。
