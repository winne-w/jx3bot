# P2 数据模型与仓储收敛技术方案（design.md）

## 1. `save_match_detail` 单次写入压缩（`jjc_inspect_repo.py`）
- 正常路径（非 `unavailable`）：先深拷贝并 `_prepare_snapshots` -> `_save_snapshot_operations`（幂等），若快照成功，直接单次 `update_one(..., upsert=True)` 写入压缩后文档（并附带 `compacted: True` 与 `equipment_source_index`）。
- 降级路径：若快照准备或保存抛异常，记结构化 warning，降级为单次写入原始 `mongo_data`（并附带 `compacted: False` 与 `equipment_source_index`），保证主数据不丢且可供后续回扫压缩。

## 2. `jjc_match_participants` CAS 与胜场心法聚合（`jjc_match_participant_repo.py`）
- `replace_match_participants`：当传入 `participants` 带有效 `cached_at` 时，先查询当前 `match_id` 已存在的最新 `cached_at`（单次 `find_one` 投影 `{"cached_at": 1}`）；若已存在更新的 `cached_at > incoming_cached_at`，跳过本次陈旧投影并返回 `0`（防止旧来源覆盖新来源）。写入优先使用 `bulk_write`（当集合支持 `bulk_write` 时），否则平滑回退 `update_one` 以兼容既有单测替身。
- 新增 `aggregate_winning_kungfu(global_id, *, season_start_time=None, match_type=3)`：利用既有 `idx_global_available_time` 在 `jjc_match_participants` 上聚合各心法胜场数与最新胜场时间。

## 3. 快照时间类型统一与真正生效的 Date TTL
- `JjcMatchSnapshotRepo`：`last_seen_at` 统一为 `float` Unix 秒（`float(seen_at) if seen_at is not None else time.time()`），不再混存 `datetime` 与 `float`。
- `ServerMasterCacheRepo.put` 与 `JjcInspectRepo.save_role_recent`：写入 `expires_at_dt`（UTC `datetime`），并在 `src/infra/mongo.py` 声明 `idx_expires_at_dt`（`expireAfterSeconds=0`）。

## 4. `identity_id` 双轨关联与 `JjcRankingCacheRepo` 下沉
- `RoleJjcCacheRepo` 支持 `load_by_identity_id(identity_id)`，`load_by_best_identity` 新增可选 `identity_id` 参数并排在最高优先级；`save` 保留传入的 `identity_id`。
- 新建 `src/storage/mongo_repos/jjc_ranking_cache_repo.py`，`JjcCacheRepo.load_ranking_cache` / `save_ranking_cache` 委托给它；`JjcCacheRepo` 胜场心法兜底优先尝试 `jjc_match_participants` 聚合，未命中或集合无数据时无缝回退既有 `jjc_match_detail` 路径。

## 5. 索引精简、退避表收敛与只读巡检脚本
- `src/infra/mongo.py`：移除 4 个冗余前缀索引声明（`jjc_match_participants.idx_match_id`、`wanbaolou_subscriptions.idx_user_id`、`jjc_ranking_stat_details.idx_timestamp`、`jjc_ranking_stat_details.idx_timestamp_range_lane`）；新增 `role_jjc_cache.idx_identity_id`、`jjc_role_indicator.idx_identity_id`、`server_master_cache.idx_expires_at_dt`、`jjc_role_recent.idx_expires_at_dt`。
- `jjc_sync_repo.py`：提取 `calculate_role_fail_backoff` 与 `calculate_match_fail_backoff`，消除 `identity_*` 与 `role_*` 重复退避常量。
- `scripts/audit_mongo_indexes.py`：只读脚本，输出 `jjc_match_detail` 的 `$indexStats` 命中次数、装备读索引校验结果及时间字段 BSON 类型分布。
