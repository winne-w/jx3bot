# JJC 角色身份写入入口统一时间保护计划

状态：已完成并归档，核心仓储时间保护已落地并通过相关单测
更新时间：2026-05-21

## 背景

`role_identities` 和 `jjc_sync_role_queue` 当前有多条写入路径：

- `RoleIdentityRepo.upsert_from_match_detail()` / `upsert_from_indicator()` / `upsert_from_ranking()`
- `JjcSyncRepo.upsert_role()` / `update_role_identity_fields()` / `update_role_identity_fields_and_key()`
- `JjcMatchDataSyncService` 在对局详情同步、手工添加、单人同步中间接写入身份表和同步队列
- `JjcRankingInspectService` 通过 indicator 写入身份表
- `scripts/backfill_jjc_role_id_from_match_replay.py` 等治理脚本直接写库；历史审计和迁移脚本已在脚本清理计划中删除

其中 `scripts/backfill_jjc_role_id_from_match_replay.py` 已有相对保守的 `role_info_observed_match_time` 判断：字段完整且当前对局不更新时不刷新，并且先拦截 `role_id/global_id/global_role_id` 强冲突。但线上通用入口并未统一这个规则：

- `RoleIdentityRepo._update_existing()` 只对 `match_detail` 来源的 `server/name/profile_observed_at` 做时间保护，外部 ID 字段仍是传了非空就 `$set`。
- `JjcSyncRepo` 写 `jjc_sync_role_queue` 时没有按对局时间判断，只保证不重置同步水位。
- indicator、ranking、manual 入口没有明确的“来源可信度 + 对局时间”统一规则。
- 治理脚本有各自的冲突和修复策略，缺少共享入口，后续容易出现旧对局或低可信来源覆盖当前角色画像。

## 目标

- 统一梳理所有会更新 `role_identities` / `jjc_sync_role_queue` 身份字段的入口。
- 将“对局来源的角色画像更新”统一改为按 `observed_match_time` 判断，只有更新的对局允许覆盖当前画像字段。
- 对已有完整身份字段，旧对局或同时间对局不覆盖，只允许补齐缺失字段或追加历史记录。
- 对同一 `global_id` 下出现 `role_id/zone/server/name/global_role_id/person_id` 变化的场景，按对局时间和来源可信度更新当前画像，并保留历史轨迹。
- 避免 `global_id` 一致但 `role_id` 等字段被旧对局、旧详情或低可信入口回写成旧值。
- 将时间保护逻辑收敛到 repo 或共享领域函数，不在 service 和脚本中重复散写。

## 非目标

- 不在本计划中清空或重建 `role_identities`、`jjc_sync_role_queue`。
- 不改变 `global_id:{global_id}` 作为最终身份主键的治理方向。
- 不取消手工添加、单人同步等弱身份兼容；这些入口仍可在没有 `global_id` 时创建兼容记录。
- 不大规模改造 `role_jjc_cache` 的心法、武器、队友缓存字段，除非身份 key 迁移需要同步缓存 key。
- 不把 SK01 `global_role_id` 重新提升为唯一身份依据。

## 统一规则设计

### 角色画像字段

以下字段属于“当前角色画像”，需要受时间保护：

- `server`
- `normalized_server`
- `name`
- `normalized_name`
- `zone`
- `role_id`
- `game_role_id`
- `global_role_id`
- `person_id`

以下字段属于身份主键或审计字段，按独立规则处理：

- `identity_key`
- `identity_level`
- `global_id`
- `aliases`
- `sources`
- `profile_history`
- `role_info_observed_match_time`
- `role_info_source`
- `role_info_updated_at`
- `updated_at`
- `last_seen_at`

### 时间字段

统一使用：

- `role_info_observed_match_time`：Unix 秒，表示当前画像字段来自哪一场对局。
- `profile_observed_at`：datetime，保留兼容现有 `RoleIdentityRepo` 逻辑；对局来源从 `observed_match_time` 派生。

后续实现中 `role_info_observed_match_time` 作为对局来源画像覆盖的主判断字段，`profile_observed_at` 与其保持一致或逐步降级为展示/兼容字段。

### 覆盖规则

对带 `global_id` 的身份更新：

1. 如果现有文档没有 `global_id`，且新数据有 `global_id`，允许升级到 `global_id:{global_id}`。
2. 如果现有 `global_id` 与新 `global_id` 不一致，不自动覆盖，记录冲突并跳过。
3. 如果 `global_id` 一致：
   - 新数据有 `observed_match_time`，且现有 `role_info_observed_match_time` 为空：允许覆盖画像字段。
   - 新数据有 `observed_match_time`，且比现有值更大：允许覆盖画像字段。
   - 新数据有 `observed_match_time`，且小于或等于现有值：不覆盖已有非空画像字段，只补齐缺失字段。
   - 新数据没有 `observed_match_time`：默认不覆盖已有非空画像字段，只补齐缺失字段；manual 可作为显式例外。
4. 每次观察到同一 `global_id` 的不同画像时，追加或去重写入 `profile_history`，用于追踪改名、转服、role_id 变化。

对没有 `global_id` 的弱身份更新：

1. `zone + role_id`、SK01 `global_role_id`、`server + name` 只能作为兼容查找和临时入队依据。
2. 弱身份来源不得覆盖已存在 `global_id` 身份的当前画像，除非通过同一 `global_id` 或人工确认入口关联。
3. 弱身份记录拿到 `global_id` 后执行 key 升级，并保留旧 key 到 `aliases`。

### 来源规则

来源按默认可信度和覆盖能力区分：

| 来源 | 是否可覆盖当前画像 | 规则 |
|---|---|---|
| `match_replay` / `match_detail` | 是 | 必须携带 `observed_match_time`，只允许更新对局覆盖 |
| `match_replay_indicator` | 是 | 以 replay 的 `global_id` 和 `observed_match_time` 为锚，indicator 只补 SK01、zone、person 等画像字段 |
| `ranking` | 否，默认只补缺失 | 排名没有对局时间，除非后续补到 replay match_time |
| `indicator` | 否，默认只补缺失 | indicator 没有对局时间，不能单独覆盖已有当前画像 |
| `manual` | 可显式覆盖 | 手工入口必须标记来源，后续可增加 `force_profile_update` 参数 |
| `audit` / `migration` | 按脚本策略 | 治理脚本需要调用共享函数，显式声明是否允许修复冲突 |

## 入口梳理与改造方案

### 1. `RoleIdentityRepo`

涉及文件：

- `src/storage/mongo_repos/role_identity_repo.py`
- `tests/test_role_identity_repo.py`

方案：

- 新增统一入参 `observed_match_time: Optional[int]` 或内部标准对象，保留 `observed_at` 兼容。
- 抽取 `_build_profile_update_decision(existing, incoming)`：
  - 返回 `allow_profile_overwrite`
  - 返回 `missing_fields_to_fill`
  - 返回 `conflict_reason`
  - 返回 `history_entry`
- `_update_existing()` 中不再无条件 set `zone/game_role_id/global_role_id/role_id/person_id`。
- 对 `match_detail` 来源，只有更新对局覆盖画像；旧对局只补空字段和追加历史。
- 对 `indicator/ranking` 来源，默认只补空字段，不覆盖已有非空画像。
- 对 `manual` 来源预留显式覆盖参数，默认先按只补缺失处理。

验证：

```bash
python -m unittest tests.test_role_identity_repo
python -m py_compile src/storage/mongo_repos/role_identity_repo.py
```

### 2. `JjcSyncRepo`

涉及文件：

- `src/storage/mongo_repos/jjc_sync_repo.py`
- `tests/test_jjc_sync_repo.py`

方案：

- 给 `upsert_role()`、`update_role_identity_fields()`、`update_role_identity_fields_and_key()` 增加可选 `observed_match_time`。
- 队列身份字段和 `role_identities` 使用同一套覆盖决策：
  - 新对局覆盖画像字段。
  - 旧对局只补缺失。
  - 无对局时间的入口默认只补缺失。
- 保留现有“不重置同步水位”约束。
- 迁移 `identity_key` 到 `global_id:{global_id}` 时继续保留水位和 aliases。
- 为队列补写 `role_info_observed_match_time`、`role_info_source`、`role_info_updated_at`。

验证：

```bash
python -m unittest tests.test_jjc_sync_repo
python -m py_compile src/storage/mongo_repos/jjc_sync_repo.py
```

### 3. `JjcMatchDataSyncService`

涉及文件：

- `src/services/jx3/jjc_match_data_sync.py`
- `tests/test_jjc_match_data_sync.py`

方案：

- 所有从 `match_detail` / replay 玩家派生的身份写入必须传入 `detail_match_time`。
- `_upsert_role_identity_from_resolved()` 继续负责把 `observed_match_time` 传到身份 repo。
- `_enqueue_players_from_detail()` 调用 `upsert_role()` 时也传入同一个 `detail_match_time`。
- person-history / 本地身份缓存只用于补齐缺失字段，不作为覆盖当前画像的依据。

验证：

```bash
python -m unittest tests.test_jjc_match_data_sync
python -m py_compile src/services/jx3/jjc_match_data_sync.py
```

### 4. 排名与 indicator 入口

涉及文件：

- `src/services/jx3/jjc_ranking_inspect.py`
- `src/services/jx3/jjc_cache_repo.py`
- 相关测试：`tests/test_jjc_ranking_inspect.py`

方案：

- 纯 ranking / indicator 写身份时默认只补缺失字段。
- 如果排名链路已经补到最近对局 replay 的 `global_id` 和 `match_time`，则以该 `match_time` 进入统一时间保护逻辑。
- indicator 返回的 SK01 `global_role_id`、zone、role_id 只有在同一 `global_id` 锚定且对局时间更新时才覆盖当前画像。

验证：

```bash
python -m unittest tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/services/jx3/jjc_cache_repo.py
```

### 5. 治理脚本

涉及文件：

- `scripts/backfill_jjc_role_id_from_match_replay.py`
- 可选新增：`scripts/check_role_identity_time_guard.py`

方案：

- `backfill_jjc_role_id_from_match_replay.py` 保留现有时间保护，但改为调用共享决策函数，避免与线上 repo 规则分叉。
- 历史审计、迁移和检查类脚本已删除，不再纳入本计划后续实现范围。
- 新增检查脚本用于输出：
  - `role_info_observed_match_time` 缺失但已有 `global_id` 的样本
  - 同一 `global_id` 下画像字段与最新 `profile_history` 不一致样本
  - 队列与身份表 `role_info_observed_match_time` 不一致样本

验证：

```bash
python -m py_compile scripts/backfill_jjc_role_id_from_match_replay.py
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 1 --dry-run
```

## 数据库与文档联动

需要更新：

- `docs/design-docs/database-design.md`
  - 明确 `role_info_observed_match_time` 是画像覆盖水位。
  - 明确无对局时间来源默认只补缺失。
  - 为 `jjc_sync_role_queue` 补充同名字段说明。
- `src/infra/mongo.py`
  - 视查询需求增加 `role_info_observed_match_time` 普通索引；如果只按 `_id/identity_key` 更新，可不加。
- `PROJECT_CONTEXT.md`
  - 如新增通用身份写入规则，需要在数据库或 JJC 规则摘要中补一句入口约束。

## 实施步骤

1. 补测试固定当前风险。
   - 状态：已完成首轮。
   - 构造同一 `global_id`，旧对局传入不同 `role_id/server/name` 不应覆盖当前画像。
   - 构造新对局传入不同 `role_id/server/name` 应覆盖当前画像，并更新 `role_info_observed_match_time`。
   - 构造无对局时间的 indicator/ranking 只补缺失，不覆盖已有字段。

2. 抽取共享覆盖决策。
   - 状态：已完成首轮，当前落在 `src/services/jx3/role_identity_matching.py`。
   - 优先放在 `src/services/jx3/role_identity_matching.py` 或新增 `src/services/jx3/role_identity_profile_guard.py`。
   - 输入为 existing doc、incoming fields、source、observed_match_time、manual override 标记。
   - 输出 `$set` 字段、冲突/跳过原因、history entry。

3. 改造 `RoleIdentityRepo`。
   - 状态：已完成首轮。
   - 使用共享决策函数。
   - 保留 identity key 升级、aliases、cache key 迁移逻辑。
   - 不再对外部 ID 字段无条件 set。
   - 当更新对局覆盖 `server`、`name` 或 SK01 `global_role_id` 时，将旧文档快照归档到 `role_identities_history`。

4. 改造 `JjcSyncRepo`。
   - 状态：已完成首轮。
   - 增加 `observed_match_time` 参数。
   - 对队列身份字段执行同样的覆盖决策。
   - 保留同步水位不重置。

5. 改造服务层调用。
   - 状态：已完成对局详情派生写入链路。
   - 对局详情和 replay 派生写入传递 match_time。
   - ranking/indicator/manual 入口按来源传递覆盖策略。

6. 改造脚本。
   - 状态：未开始。
   - 先迁移 `backfill_jjc_role_id_from_match_replay.py`。
   - 再收敛 audit 和 migration 脚本。
   - 新增只读检查脚本辅助上线前审计。

7. 更新数据库文档和运行说明。
   - 状态：数据库文档已更新首轮规则。

8. 执行自动化和 dry-run 验证。
   - 状态：已执行核心仓储与同步服务单测、相关文件 py_compile；`tests.test_jjc_ranking_inspect` 限时 20 秒未完成，暂未作为通过项。

## 风险与回滚

- 风险：过于保守会导致最新身份字段补不进去。
  - 缓解：允许新对局覆盖；manual/audit 保留显式修复通道。
- 风险：历史文档缺少 `role_info_observed_match_time`，首次旧对局可能被当作可覆盖。
  - 缓解：实现前先用检查脚本评估缺失比例；对于已有 `profile_observed_at` 可派生初始水位。
- 风险：队列和身份表规则不一致导致同一角色画像分裂。
  - 缓解：两处共用同一个决策函数和同一批测试样例。
- 风险：脚本直接写库绕过 repo。
  - 缓解：脚本改为调用共享决策函数；不能改的历史脚本在文档中标记只读/停止使用。

回滚：

- 代码层回滚到旧 repo 写入逻辑即可。
- 数据层不新增破坏性字段；新增 `role_info_observed_match_time` 等字段可保留。
- 若新规则误跳过更新，可通过 audit/manual 修复脚本带显式 override 重放。

## 验收标准

- 所有线上身份写入入口都能说明是否带 `observed_match_time`，以及无时间时是否只补缺失。
- `role_identities` 中同一 `global_id` 的旧对局不会覆盖更新画像。
- `jjc_sync_role_queue` 中同一 `global_id` 的旧对局不会覆盖更新画像，且同步水位不被重置。
- `backfill_jjc_role_id_from_match_replay.py` 与线上 repo 使用同一套覆盖规则。
- 单测覆盖：
  - 新对局覆盖
  - 旧对局不覆盖
  - 旧对局补缺失
  - 无时间来源只补缺失
  - `global_id` 冲突跳过
  - 队列 key 迁移不重置同步水位

## 建议验证命令

```bash
python -m unittest tests.test_role_identity_matching tests.test_role_identity_repo tests.test_jjc_sync_repo tests.test_jjc_match_data_sync tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/role_identity_matching.py src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py src/services/jx3/jjc_match_data_sync.py src/services/jx3/jjc_ranking_inspect.py scripts/backfill_jjc_role_id_from_match_replay.py
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 1 --dry-run
```
