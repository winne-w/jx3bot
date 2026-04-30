# JJC 对局详情存储拆分计划

更新时间：2026-04-30

## 背景

当前 `jjc_match_detail` 以 `match_id` 为唯一键保存完整对局详情。`data` 字段是 MongoDB 嵌套对象（BSON document），不是 JSON 字符串；这符合 Mongo 的使用方式，问题不在数据类型，而在每局重复保存完整装备与奇穴数组。

2026-04-30 只读观察：

- `jjc_match_detail` 约 341 条，逻辑大小约 20.45 MB，平均每局约 60 KB。
- WiredTiger 压缩后集合存储约 7.0 MB，索引约 80 KB。
- 顺序采样 80 局，单局约 51-61 KB，3v3 对局固定 6 名玩家。
- 体积主要来自玩家维度：`armors` 平均约 4.1 KB/玩家，`talents` 平均约 3.1 KB/玩家，`metrics` 平均约 1.1 KB/玩家，`body_qualities` 平均约 1.0 KB/玩家。

用户明确不希望通过字段裁剪降低体积，因此本计划默认保留原始字段完整性。

## 目标

- 保留历史对局详情的完整字段，不把大字段裁剪掉。
- 降低装备、奇穴在多场对局中重复保存造成的集合膨胀。
- 保持现有对外 API 返回结构基本不变，避免前端大改。
- 为未来统计能力预留路径，但第一阶段不引入事实表。

## 非目标

- 不做字段裁剪。
- 不把历史对局展示改成读取角色当前装备或当前奇穴。
- 第一阶段不实现“某奇穴对局数”“有 CW 对局数”等统计接口。
- 第一阶段不强制迁移 `metrics`、`body_qualities`，除非实现时确认其重复率和收益足够高。

## 设计原则

- `jjc_match_detail` 继续表达“某场对局的业务详情”，`match_id` 仍是幂等主键。
- 装备、奇穴是对局当时快照，不能用角色当前画像替代。
- snapshot 表保存完整原始数组，避免字段丢失。
- API 拼装由 `src/storage/` 或 `src/services/jx3/` 内完成，handler 和前端不感知内部拆表。
- 统计用事实表以后再做；事实表是可重建查询索引，不是完整源数据。

## 推荐集合

### `jjc_equipment_snapshot`

用途：保存完整装备快照，按内容 hash 去重。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `snapshot_hash` | string | 规范化 `armors` 数组后的内容 hash，业务唯一 |
| `armors` | array | 完整装备数组，不裁剪字段 |
| `created_at` | datetime | 首次写入时间 |
| `last_seen_at` | datetime | 最近一次被对局引用的时间 |
| `schema_version` | int | schema 版本 |

建议索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_snapshot_hash` | `snapshot_hash` | unique |
| `idx_last_seen_at` | `last_seen_at` | 普通索引 |

### `jjc_talent_snapshot`

用途：保存完整奇穴快照，按内容 hash 去重。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `snapshot_hash` | string | 规范化 `talents` 数组后的内容 hash，业务唯一 |
| `talents` | array | 完整奇穴数组，不裁剪字段 |
| `created_at` | datetime | 首次写入时间 |
| `last_seen_at` | datetime | 最近一次被对局引用的时间 |
| `schema_version` | int | schema 版本 |

建议索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_snapshot_hash` | `snapshot_hash` | unique |
| `idx_last_seen_at` | `last_seen_at` | 普通索引 |

## `jjc_match_detail` 调整方向

玩家节点中：

- `armors` 从完整数组改为内部存储字段 `equipment_snapshot_hash`。
- `talents` 从完整数组改为内部存储字段 `talent_snapshot_hash`。
- 读取 API 时再把 snapshot 拼回 `players_info[].armors` 和 `players_info[].talents`，保持外部结构兼容。
- 对局动态字段继续留在玩家节点，例如 `kungfu`、`kungfu_id`、`mmr`、`score`、`total_score`、`equip_score`、`equip_strength_score`、`stone_score`、`max_hp`、`mvp`、`fight_seconds`。

角色身份字段可以后续和 `role_identities` 关联，但不能因此丢失历史展示所需字段。

## Hash 规范

必须先规范化再计算 hash，避免同一套装备/奇穴因数组顺序或 key 顺序不同生成多个 hash。

装备建议：

- 仅用于规范化排序，不用于裁剪保存字段。
- 排序优先级：`pos`、`ui_id`、`name`。
- 序列化：`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。
- hash：优先 `sha256`，保存十六进制字符串。

奇穴建议：

- 排序优先级：`level`、`id` 或 `talent_id`、`name`。
- 序列化与 hash 规则同装备。

## 读写流程

写入缓存：

1. 从推栏接口获取并解析 `MatchDetailResponse`。
2. 遍历 `team1/team2.players_info`。
3. 对每个玩家的 `armors` 和 `talents` 分别计算 hash。
4. `upsert` snapshot 集合，更新 `last_seen_at`。
5. 在 `jjc_match_detail` 中保存 hash 引用，避免重复保存完整数组。

读取缓存：

1. 按 `match_id` 读取 `jjc_match_detail`。
2. 收集所有 `equipment_snapshot_hash` 和 `talent_snapshot_hash`。
3. 批量查询 snapshot 集合。
4. 拼回 `players_info[].armors` 和 `players_info[].talents`。
5. 返回与当前 API 兼容的 payload。

## 可执行拆分计划

本节是实施 checklist。每个阶段都按“单测用例 → 代码更改 → 单测 → 测试/验证”推进，不把迁移依赖在人工记忆里。

### 阶段 0：基线确认

单测用例：

- 暂不新增测试，只确认当前行为基线。

代码更改：

- 不改代码。
- 记录一个可用于手工回归的 `match_id`，要求该对局有 6 名玩家、装备、奇穴。
- 通过当前 API 保存一份迁移前响应样本，后续用于结构对比。

单测：

- 不适用。

测试/验证：

```bash
python -m py_compile src/services/jx3/match_detail.py src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/match-detail?match_id=<对局ID>"
```

验收：

- 当前 API 可返回 `detail.team1.players_info[].armors` 与 `detail.team1.players_info[].talents`。
- 记录迁移前响应，后续拆表后同一个 `match_id` 的核心展示字段一致。

### 阶段 1：纯函数抽取与 hash 规则

单测用例：

- 新增 `tests/test_jjc_match_detail_snapshots.py`。
- 测试装备数组不同 key 顺序生成同一个 hash。
- 测试装备数组不同顺序但 `pos/ui_id/name` 相同生成同一个 hash。
- 测试奇穴数组不同顺序但 `level/id/name` 相同生成同一个 hash。
- 测试空数组生成稳定 hash，且不会抛异常。
- 测试输入对象不会被原地修改。

代码更改：

- 新增 `src/services/jx3/match_detail_snapshots.py`。
- 提供纯函数：

```python
normalize_equipment_snapshot(armors: List[Dict[str, Any]]) -> List[Dict[str, Any]]
normalize_talent_snapshot(talents: List[Dict[str, Any]]) -> List[Dict[str, Any]]
calculate_snapshot_hash(items: List[Dict[str, Any]]) -> str
build_equipment_snapshot(armors: List[Dict[str, Any]]) -> Dict[str, Any]
build_talent_snapshot(talents: List[Dict[str, Any]]) -> Dict[str, Any]
```

Python 3.9 兼容要求：

- 类型注解使用 `typing.List`、`typing.Dict`、`typing.Any`、`typing.Optional`，不要使用 `list[...] | None`。

单测：

```bash
python -m unittest tests.test_jjc_match_detail_snapshots
python -m py_compile src/services/jx3/match_detail_snapshots.py tests/test_jjc_match_detail_snapshots.py
```

测试/验证：

- 无需连接 Mongo。
- 手工构造一份装备和奇穴样本，确认 hash 输出稳定。

验收：

- hash 规则稳定、幂等、不修改输入。
- 纯函数没有依赖 Mongo、NoneBot、外部 API。

### 阶段 2：snapshot repo 与索引初始化

单测用例：

- 新增 `tests/test_jjc_snapshot_repo.py`，使用 fake collection 或 `unittest.mock.AsyncMock` 验证 repo 调用。
- 测试保存新 snapshot 时使用 `update_one(..., upsert=True)`。
- 测试重复保存同一 hash 时只更新 `last_seen_at`，不改变完整数组结构。
- 测试批量读取 hash 列表时返回 `hash -> snapshot` 映射。
- 测试缺失 hash 时不会抛异常，由上层决定兼容策略。

代码更改：

- 新增 `src/storage/mongo_repos/jjc_match_snapshot_repo.py`。
- 新增 repo 方法：

```python
save_equipment_snapshot(snapshot_hash, armors, seen_at)
save_talent_snapshot(snapshot_hash, talents, seen_at)
load_equipment_snapshots(snapshot_hashes)
load_talent_snapshots(snapshot_hashes)
```

- 更新 `src/infra/mongo.py:_ensure_indexes()`：

```text
jjc_equipment_snapshot.idx_snapshot_hash unique
jjc_equipment_snapshot.idx_last_seen_at
jjc_talent_snapshot.idx_snapshot_hash unique
jjc_talent_snapshot.idx_last_seen_at
```

- 更新 `docs/design-docs/database-design.md`，正式加入两个 snapshot 集合，而不只写在计划里。

单测：

```bash
python -m unittest tests.test_jjc_snapshot_repo
python -m py_compile src/storage/mongo_repos/jjc_match_snapshot_repo.py src/infra/mongo.py tests/test_jjc_snapshot_repo.py
```

测试/验证：

- 在测试库或本地库执行启动初始化，确认索引存在。
- 若无法连接 Mongo，至少执行 `py_compile`，并把索引验证列入手工回归。

验收：

- 两个 snapshot 集合的唯一索引可由启动流程幂等创建。
- repo 边界位于 `src/storage/mongo_repos/`，没有在 handler/API router 中散写 Mongo。

### 阶段 3：读路径兼容水合

单测用例：

- 新增 `tests/test_jjc_match_detail_hydration.py`。
- 测试旧结构：玩家已有 `armors/talents` 时，读取结果保持不变。
- 测试新结构：玩家只有 `equipment_snapshot_hash/talent_snapshot_hash` 时，读取结果能拼回 `armors/talents`。
- 测试 snapshot 缺失时返回空数组或保留 hash，并记录 warning，不导致整个对局详情失败。
- 测试同一对局多个玩家复用同一 hash 时只批量读取一次。

代码更改：

- 在 `src/storage/mongo_repos/jjc_inspect_repo.py` 或新的 service helper 中增加水合逻辑。
- 推荐让 `JjcInspectRepo.load_match_detail(...)` 返回已经兼容旧 API 的结构，避免上层和前端感知内部拆表。
- 若 repo 需要 snapshot repo，优先通过构造参数注入；无法注入时再使用默认 repo，避免测试困难。

单测：

```bash
python -m unittest tests.test_jjc_match_detail_hydration
python -m py_compile src/storage/mongo_repos/jjc_inspect_repo.py tests/test_jjc_match_detail_hydration.py
```

测试/验证：

```bash
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/match-detail?match_id=<旧结构对局ID>"
```

验收：

- 旧数据不迁移也能继续读取。
- 新结构数据能拼回原 `players_info[].armors/talents`。
- API payload 对前端保持兼容。

### 阶段 4：新写入路径拆表

单测用例：

- 新增或扩展 `tests/test_jjc_match_detail_hydration.py`。
- 测试保存新对局详情时，完整 `armors/talents` 被写入 snapshot 集合。
- 测试 `jjc_match_detail` 玩家节点保存 `equipment_snapshot_hash/talent_snapshot_hash`。
- 测试保存后再读取，可还原出完整 `armors/talents`。
- 测试 snapshot repo 写入失败时，不应静默写入半残缺 match detail；推荐整体失败并返回外部请求错误或保留旧完整结构兜底，具体策略实现前必须明确。

代码更改：

- 修改 `src/services/jx3/jjc_ranking_inspect.py:get_match_detail(...)` 的缓存写入流程。
- 写入 `jjc_match_detail` 前调用 snapshot helper 生成 hash 并保存 snapshot。
- `payload` 对外返回时仍包含完整 `armors/talents`，内部落库数据不重复保存完整数组。
- 对已有旧缓存命中路径不做破坏性改动。

单测：

```bash
python -m unittest tests.test_jjc_match_detail_hydration tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo
python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py src/storage/mongo_repos/jjc_match_snapshot_repo.py
```

测试/验证：

```bash
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/match-detail?match_id=<未缓存对局ID>"
```

手工检查：

- `jjc_match_detail` 新文档中玩家节点有 `equipment_snapshot_hash/talent_snapshot_hash`。
- `jjc_equipment_snapshot` 与 `jjc_talent_snapshot` 有对应文档。
- API 返回仍有完整装备与奇穴。

验收：

- 新写入路径完成拆表。
- 前端无感。
- 失败策略明确且有测试覆盖。

### 阶段 5：迁移脚本实现

单测用例：

- 新增 `tests/test_migrate_jjc_match_detail_snapshots.py`。
- 测试 dry-run 不调用写操作。
- 测试 apply 会写 snapshot、更新玩家 hash、移除内部重复数组。
- 测试已迁移文档重复执行不会再次改变结果。
- 测试旧文档中缺少某个玩家的 `armors` 或 `talents` 时跳过该玩家对应字段，不中断整局。
- 测试 rollback 从备份集合恢复原始 `data`。

代码更改：

- 新增 `scripts/migrate_jjc_match_detail_snapshots.py`。
- 脚本参数：

```text
--dry-run              默认模式，只统计不写库
--apply                执行迁移
--rollback             从备份集合恢复
--verify-only          只校验迁移结果
--limit N              限制处理文档数
--match-id ID          只处理单局，便于灰度
--batch-size N         批处理大小，默认 100
--resume-after ID      从某个 match_id 之后继续
--drop-backup          验证完成后清理备份集合，必须单独显式执行
```

- 脚本读配置：

```text
优先环境变量 MONGO_URI
其次 runtime_config.json 中的 MONGO_URI
数据库名沿用连接串路径
```

- 迁移集合：

```text
源集合：jjc_match_detail
目标集合：jjc_equipment_snapshot、jjc_talent_snapshot
临时备份集合：jjc_match_detail_snapshot_migration_backup
```

- 备份策略：

```text
每个 match_id 首次 apply 前，把原始 data、cached_at、backup_at 写入备份集合
备份集合以 match_id unique
重复 apply 不覆盖已有备份
rollback 按 match_id 或全量恢复 data/cached_at
drop-backup 必须单独执行，不和 apply 绑定
```

- 文档更新策略：

```text
对每个 player：
  如果存在 armors：写 equipment snapshot，设置 equipment_snapshot_hash，unset/remove armors
  如果存在 talents：写 talent snapshot，设置 talent_snapshot_hash，unset/remove talents
  保留 metrics/body_qualities 和其他动态字段
文档顶层写入 snapshot_migration:
  version: 1
  migrated_at: datetime
  equipment_snapshot_count: int
  talent_snapshot_count: int
```

- 输出统计：

```text
matched_docs
migrated_docs
skipped_docs
players_seen
equipment_snapshots_written
talent_snapshots_written
backup_docs_written
failed_docs
estimated_original_bson_bytes
estimated_new_bson_bytes
estimated_saved_bson_bytes
```

单测：

```bash
python -m unittest tests.test_migrate_jjc_match_detail_snapshots
python -m py_compile scripts/migrate_jjc_match_detail_snapshots.py tests/test_migrate_jjc_match_detail_snapshots.py
```

测试/验证：

```bash
python scripts/migrate_jjc_match_detail_snapshots.py --dry-run --limit 10
python scripts/migrate_jjc_match_detail_snapshots.py --apply --match-id <对局ID>
python scripts/migrate_jjc_match_detail_snapshots.py --verify-only --match-id <对局ID>
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/match-detail?match_id=<对局ID>"
python scripts/migrate_jjc_match_detail_snapshots.py --rollback --match-id <对局ID>
```

验收：

- dry-run 无写库。
- 单局 apply 后 API 响应仍能展示完整装备和奇穴。
- 单局 rollback 能恢复旧结构。
- 重复 apply 结果稳定。

### 阶段 6：小批量迁移与全量迁移

单测用例：

- 不新增单测，复用前面所有测试。

代码更改：

- 不新增业务代码，只执行脚本。

单测：

```bash
python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration tests.test_migrate_jjc_match_detail_snapshots
python -m py_compile src/services/jx3/match_detail_snapshots.py src/storage/mongo_repos/jjc_match_snapshot_repo.py src/storage/mongo_repos/jjc_inspect_repo.py src/services/jx3/jjc_ranking_inspect.py scripts/migrate_jjc_match_detail_snapshots.py
```

测试/验证：

```bash
python scripts/migrate_jjc_match_detail_snapshots.py --dry-run
python scripts/migrate_jjc_match_detail_snapshots.py --apply --limit 20
python scripts/migrate_jjc_match_detail_snapshots.py --verify-only --limit 20
python scripts/migrate_jjc_match_detail_snapshots.py --apply
python scripts/migrate_jjc_match_detail_snapshots.py --verify-only
```

手工回归：

- 统计页点击迁移前已有对局详情。
- 统计页点击迁移后新缓存对局详情。
- 抽样检查 5 个 `match_id`，比较迁移前样本或备份中的 `armors/talents` 与 API 当前返回一致。

验收：

- 全量迁移失败数为 0，或失败清单可解释且不影响后续重跑。
- `jjc_match_detail` 平均文档体积下降。
- snapshot 集合数量明显小于“对局数 × 6 玩家”的理论最大值，说明去重生效。
- 备份集合保留到至少一次线上回归完成后，再人工执行 `--drop-backup`。

### 阶段 7：文档收口

单测用例：

- 不适用。

代码更改：

- 更新 `docs/design-docs/database-design.md`，将 `jjc_equipment_snapshot`、`jjc_talent_snapshot` 从计划集合改为正式集合。
- 更新 `docs/references/runbook.md`，补充迁移 dry-run、apply、verify、rollback 命令。
- 若新增了单测目录，更新 `PROJECT_CONTEXT.md` 的常用验证命令。
- 迁移完成后，把本计划从 `docs/exec-plans/active/` 移动到 `docs/exec-plans/completed/`，并更新 `docs/exec-plans/index.md`。

单测：

```bash
python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration tests.test_migrate_jjc_match_detail_snapshots
```

测试/验证：

- 检查所有文档引用路径存在。
- 检查 README 或 runbook 中没有泄露连接串、Cookie、token。

验收：

- 代码、脚本、数据库设计、runbook、执行计划状态一致。

## 未来统计路径

第一阶段不做事实表。后续若需要统计：

- 轻量统计可先在 snapshot 表补索引字段，例如 `talent_ids`、`talent_names`、`item_ui_ids`、`item_names`、`has_cw`。
- 高频或组合统计再建 `jjc_match_player_fact`，从 `jjc_match_detail + snapshot` 回填。
- 事实表必须带 `schema_version` 和 `extracted_at`，并允许通过完整源数据重建。

## 验收标准

- 点击统计页对局详情时，前端展示与拆表前一致。
- 新写入对局不再在 `jjc_match_detail` 里重复保存完整 `armors`/`talents` 数组。
- 老数据迁移可重复执行，重复执行结果稳定。
- Mongo 中 snapshot 集合存在唯一索引，`jjc_match_detail.match_id` 唯一索引保持不变。
- 文档、索引初始化和迁移脚本说明同步完成。
