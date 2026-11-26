# P0 止血代码审查记录（review.md）

日期：2026-11-26  
审查范围：`refactor/design-p0-stabilize` 相对 `8a21a2b` 全部 diff。

## 审查结论：通过

1. **分层与兼容性**：未新增反向依赖；`JjcMatchDataSyncService._release_role_interrupted` 对 `next_sync_after` 采用向后兼容回退，不破坏既有单测替身；所有改动兼容 Python 3.9。
2. **数据安全与正确性**：
   - `_safe_create_index` 在 `existing_unique or desired_unique` 不一致时仅记 error 并返回，绝不自动 `drop_index`；非唯一索引保留原有演进重建语义。
   - `save_talent_snapshot` 将 `created_at` 与 `talents`/`schema_version`/`last_seen_at` 严格分置于 `$setOnInsert` 与 `$set`，无字段冲突且解决 v1 升级死循环。
   - `release_identity_interrupted` / `release_role_interrupted` 在对局处于 `failed` 退避或 `detail_syncing` 持租时转入 `cooldown` + `next_sync_after`，保留同步水位且消除 10 秒空转。
   - `upgrade_identity` 改用 `$addToSet` 维护 `aliases`。
3. **跨版本发现与修复**：
   - 首轮 Python 3.13 测试发现 `tests/test_jjc_sync_p0_backoff.py` 对 frozen dataclass 实例使用 `patch.object(repo, ...)` 触发 `FrozenInstanceError`；已修正为 `patch.object(JjcSyncRepo, ...)` 并在 Python 3.9 与 3.13 双版本验证通过。
4. **文档同步**：`docs/design-docs/database-design.md` 已同步更新唯一索引维护规则、装备读索引代码入口、`server_master_cache` / `jjc_role_recent` TTL 说明及 `jjc_sync_role_queue` 索引精简说明。
