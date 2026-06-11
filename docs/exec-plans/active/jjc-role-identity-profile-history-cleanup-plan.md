# JJC role_identities profile_history 清理与热路径瘦身计划

## 背景

2026-06-11 排查 JJC 对局详情身份投影耗时，日志表现为：

- `update_ms` 通常只有 11-15ms，实际写入不慢。
- `queue_ms` 通常约 10-20ms，队列写入不是主瓶颈。
- `resolve_ms` 与 `reload_ms` 经常达到 1-5 秒。

使用 `runtime_config.json` 的 MongoDB 配置只读诊断后确认：

- `role_identities.idx_identity_key`、`idx_global_id`、`idx_normalized_server_name` 等索引存在。
- 查询 `identity_key` / `global_id` 的 `explain` 均命中 IXSCAN，`keysExamined=1`，`docsExamined=1` 或 2。
- 慢点不是索引缺失，而是命中索引后完整读取 `role_identities` 大文档。

样本文档中，`profile_history` 数组已经显著膨胀：

| 角色 | BSON 大小 | `profile_history` 长度 | 完整读取中位数 | 瘦投影读取中位数 |
|---|---:|---:|---:|---:|
| 白梓 | 264KB | 1193 | 2426ms | 24ms |
| 芙云 | 258KB | 1163 | 4857ms | 57ms |
| 轩辕青锋 | 137KB | 601 | 2887ms | 29ms |
| 安染染 | 105KB | 460 | 3330ms | 20ms |

当前项目代码没有线上业务按 `profile_history` 查询或计算。重要画像覆盖前的旧文档快照已有 `role_identities_history` 承担回溯职责，因此本次方案决定直接从 `role_identities` 主文档清除 `profile_history`，并停止后续写入。

## 目标

- 将 JJC 对局详情身份投影中的 `resolve_ms` / `reload_ms` 从秒级降回几十毫秒级。
- `role_identities` 主文档只保留当前有效身份画像与热路径所需字段。
- 历史回溯统一依赖 `role_identities_history`，不再在主文档保存每次来源观测事件。
- 对现有 `profile_history` 执行可审计、可回滚策略明确的批量清理。

## 非目标

- 不调整 `identity_key` 生成规则。
- 不调整 `global_id`、SK01 `global_role_id`、`zone + role_id` 等身份解析优先级。
- 不新增 `role_identity_profile_events` 之类事件集合；本轮直接清理主文档字段。
- 不自动合并身份冲突数据。

## 变更范围

- `src/storage/mongo_repos/role_identity_repo.py`
  - 为 match_detail 热路径增加瘦投影，避免读取废弃字段和大数组。
  - 停止新建身份时写入 `profile_history`。
  - 停止更新已有身份时 `$addToSet.profile_history`。
  - 保留 `sources`、`last_seen_at`、`updated_at`、`role_info_observed_match_time` 等当前状态字段写入。
  - 保留 `role_identities_history` 旧文档快照归档逻辑。
- `scripts/`
  - 新增一次性清理脚本，支持 dry-run 与 execute 两种模式。
- `docs/design-docs/database-design.md`
  - 将 `role_identities.profile_history` 标记为废弃并说明清理策略。
  - 明确历史机制：当前画像在 `role_identities`，重要覆盖快照在 `role_identities_history`。
- `tests/`
  - 更新不再断言 `profile_history` 写入的单测。
  - 补充热路径 projection 与停止写入的行为测试。
- `docs/exec-plans/index.md`
  - 登记本计划。

## 设计方案

### 1. 热路径查询使用瘦投影

新增内部投影常量，例如 `MATCH_DETAIL_IDENTITY_PROJECTION`，字段只覆盖身份解析、更新判断、队列入库需要的内容：

```python
{
    "_id": 1,
    "identity_key": 1,
    "identity_level": 1,
    "server": 1,
    "normalized_server": 1,
    "name": 1,
    "normalized_name": 1,
    "zone": 1,
    "game_role_id": 1,
    "role_id": 1,
    "person_id": 1,
    "global_role_id": 1,
    "global_id": 1,
    "aliases": 1,
    "sources": 1,
    "profile_observed_at": 1,
    "role_info_observed_match_time": 1,
    "last_seen_at": 1,
    "updated_at": 1,
}
```

应用位置：

- `resolve_best_identity_with_id()` 支持可选 projection，match_detail 调用传入瘦投影。
- `find_best_by_name_with_id()` 支持可选 projection，避免按名称 fallback 时拉取完整文档。
- `_update_existing()` 更新后的 reload 查询使用瘦投影：
  - 当前慢查询为 `find_one({"identity_key": lookup_key})`。
  - 修改为 `find_one({"identity_key": lookup_key}, projection)`。

### 2. 停止写入 profile_history

主文档不再维护 `profile_history`：

- 新建身份文档时不再设置 `"profile_history": [history_entry]`。
- 更新已有身份时从 `$addToSet` 中移除 `profile_history`。
- `build_profile_history_entry()` 可暂时保留给迁移脚本或历史兼容测试使用；后续无调用后再单独清理。

`sources` 仍通过 `$addToSet` 维护来源集合，用于判断该身份曾经被哪些入口观察到。

### 3. 历史回溯统一走 role_identities_history

继续保留 `_should_archive_profile_change()` 与 `_archive_profile_snapshot()`：

- 当 `server`、`name`、`global_role_id` 等重要画像字段发生覆盖时，将旧主文档快照写入 `role_identities_history`。
- `global_id` 冲突继续按现有逻辑警告并跳过，不自动覆盖。
- 普通重复观测、`last_seen_at` 刷新、无实质画像变化不写历史事件。

### 4. 一次性数据清理脚本

新增脚本建议命名：

```text
scripts/cleanup_role_identity_profile_history.py
```

脚本行为：

- 默认 dry-run，不修改数据。
- 统计：
  - `profile_history` 存在的文档数。
  - 样本最大 `profile_history` 长度。
  - 样本最大 BSON 大小。
  - 清理前样本完整读取与瘦投影读取耗时。
- execute 模式执行：

```javascript
db.role_identities.updateMany(
  {"profile_history": {"$exists": true}},
  {"$unset": {"profile_history": ""}}
)
```

- 输出 matched / modified 数量。
- 清理后再次抽样验证字段不存在、文档大小下降、完整读取耗时下降。

### 5. 文档与测试同步

- `docs/design-docs/database-design.md`
  - 不再把 `profile_history` 作为标准字段。
  - 增加废弃说明：历史版本可能残留，清理脚本会 `$unset`。
- 单测调整：
  - 删除或改写 `profile_history` 写入断言。
  - 增加断言：match_detail 更新不会写入 `profile_history`。
  - 增加断言：更新后 reload 使用 projection 返回队列所需字段。

## 验证计划

### 自动化验证

执行：

```bash
python -m unittest tests.test_role_identity_repo tests.test_role_identity_matching tests.test_backfill_jjc_role_id_from_match_replay
python -m py_compile src/storage/mongo_repos/role_identity_repo.py scripts/cleanup_role_identity_profile_history.py
```

如果修改了数据库设计文档以外的脚本 import 路径，再补充对应脚本 dry-run 编译或单测。

### 数据库只读验证

执行清理前 dry-run：

```bash
python scripts/cleanup_role_identity_profile_history.py --dry-run
```

确认输出包含：

- 待清理文档数。
- 最大/样本 `profile_history` 长度。
- 清理前完整读取耗时与瘦投影耗时。

### 数据库写入验证

确认执行窗口后执行：

```bash
python scripts/cleanup_role_identity_profile_history.py --execute
```

执行后验证：

```javascript
db.role_identities.countDocuments({"profile_history": {"$exists": true}})
```

结果应为 0。

### 线上观察

观察 JJC 对局详情身份投影日志：

- `resolve_ms`
- `reload_ms`
- `identity_ms`
- `queue_ms`

预期：

- `reload_ms` 从 700-2000ms 降到 20-100ms。
- 命中 `global_id` / `identity_key` 的 `resolve_ms` 显著下降。
- `update_ms` 与 `queue_ms` 基本保持原水平。

## 风险与回滚

### 风险

- 清理后不能再从 `role_identities.profile_history` 查看每一次来源观测记录。
- 如果存在仓库外部脚本直接读取 `profile_history`，会受到影响；当前仓库内未发现线上业务依赖。

### 风险缓解

- 清理前 dry-run 输出统计，确认字段规模与样本。
- 清理动作只 `$unset profile_history`，不修改身份主键、当前画像、索引和队列。
- 重要画像变更仍通过 `role_identities_history` 回溯。

### 回滚

- 代码回滚：
  - 恢复新建/更新时写入 `profile_history`。
  - 移除 match_detail projection 改造。
- 数据回滚：
  - `$unset` 后无法从当前集合直接恢复 `profile_history`。
  - 如必须恢复，只能依赖执行前数据库备份或 MongoDB 快照。
  - 因此执行清理前必须确认备份策略或接受该字段不可恢复。

## 状态

- 2026-06-11：方案确认，待实现。
- 2026-06-11：已实现仓储瘦投影、停止运行时与 replay 回填脚本写入 `profile_history`，新增 `scripts/cleanup_role_identity_profile_history.py`，并更新数据库设计文档；待自动化验证和 review。
- 2026-06-11：自动化验证通过，已完成自查 review；清理脚本已执行线上 dry-run，只读确认待清理 54708 条，未执行 `--execute` 写库。
