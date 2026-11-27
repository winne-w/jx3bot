# P2 数据模型与仓储收敛（design-p2-data）

日期：2026-11-26  
分支：`refactor/design-p2-data`（基于 `refactor/design-p1-domain`）  
关联评审：`design_review.md` 阶段 2

## 背景与目标

1. **消除 `save_match_detail` 两次 60KB 写入与整文档相等 CAS**：先准备并保存幂等快照，再单次写入压缩后的 `jjc_match_detail`（快照保存失败时降级写入原文并标记 `compacted=False`）。
2. **`jjc_match_participants` 引入源水位 CAS 与批量写**：防止并发投影中旧来源覆盖新来源，并新增按 `global_id` 的胜场心法聚合查询，减少对 `jjc_match_detail` 原始 JSON 的 `$elemMatch` 扫描。
3. **附属缓存支持不可变 `identity_id` 主键演进**：`role_jjc_cache` 与 `jjc_role_indicator` 新增 `identity_id` 索引与优先读取路径，防止身份升级后缓存成孤儿；将 `jjc_ranking_cache` 读写下沉至 `src/storage/mongo_repos/jjc_ranking_cache_repo.py`。
4. **TTL 与时间类型治理、冗余前缀索引清理与只读巡检脚本**：为 `server_master_cache` 与 `jjc_role_recent` 补充 `expires_at_dt`（Date TTL 0）；统一快照 `last_seen_at` 为 float Unix 秒；移除 4 个冗余前缀索引；收敛 `jjc_sync_repo` 重复退避表；新增只读 `scripts/audit_mongo_indexes.py` 巡检 `$indexStats` 与混合时间类型。
