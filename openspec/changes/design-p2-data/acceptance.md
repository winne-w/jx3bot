# P2 数据模型与仓储收敛验证与验收记录（acceptance.md）

日期：2026-11-26  
分支：`refactor/design-p2-data`

## 验收结果
- [x] `save_match_detail` 单次写入压缩（`compacted=True`），快照失败时降级单次写入原文（`compacted=False`），消除两次 60KB 写入与脆弱整文档相等 CAS。
- [x] `jjc_match_participants` 增加源水位 `cached_at` CAS 保护、优先 `bulk_write` 及 `aggregate_winning_kungfu` 胜场心法聚合。
- [x] `jjc_equipment_snapshot` / `jjc_talent_snapshot` 统一 `last_seen_at` 为 `float` Unix 秒。
- [x] `server_master_cache` 与 `jjc_role_recent` 写入 UTC `expires_at_dt` 并声明 `expireAfterSeconds=0` 真实 Date TTL 索引；移除 4 个冗余前缀索引；新增 `role_jjc_cache` / `jjc_role_indicator` 的 `idx_identity_id`。
- [x] `JjcRankingCacheRepo` 下沉至 `src/storage/mongo_repos/jjc_ranking_cache_repo.py`；`RoleJjcCacheRepo` 支持不可变 `identity_id` 优先读取与写入；`JjcCacheRepo` 胜场兜底优先走 `jjc_match_participants` 聚合。
- [x] 收敛 `jjc_sync_repo` 重复退避表；新增只读 `scripts/audit_mongo_indexes.py` 巡检 `$indexStats` 与时间字段类型分布；同步更新 `docs/design-docs/database-design.md`。
- [x] Python 3.9 与 Python 3.13 双版本验证全部通过。
