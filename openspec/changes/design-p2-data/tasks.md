# P2 数据模型与仓储收敛执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

收敛 MongoDB 写入路径、并发一致性保护、TTL 真实生效机制、不可变 `identity_id` 缓存关联及冗余索引，同时通过只读巡检脚本为线上删旧多键索引提供数据依据。

## Progress
- [x] 完成 P2 方案设计（2026-11-26）
- [x] 子任务 P2-A：`save_match_detail` 单次写入压缩、`jjc_match_participants` CAS 与胜场聚合、快照 `last_seen_at` 类型统一
- [x] 子任务 P2-B：Date TTL 索引、冗余前缀索引清理、`jjc_sync_repo` 退避表收敛、`scripts/audit_mongo_indexes.py` 与 `database-design.md` 更新
- [x] 子任务 P2-C：`JjcRankingCacheRepo` 下沉、`role_jjc_cache` `identity_id` 优先关联与 `jjc_cache_repo` 聚合优先路径
- [x] 双版本测试验证、审查与本地提交

## Surprises & Discoveries
待实现后补充。

## Decision Log
- 2026-11-26：线上 `jjc_match_detail` 既有旧多键索引不在本阶段盲目删除，先提供只读 `scripts/audit_mongo_indexes.py` 采样 `$indexStats` 后再决定下线。

## Outcomes & Retrospective
待完成后回填。

## Context and Orientation
分支 `refactor/design-p2-data` 基于 `refactor/design-p1-domain` (`debce03`)。

## Plan of Work
拆分为 P2-A、P2-B、P2-C 三个严格互斥文件集的并行子任务。

## Concrete Steps
见 `design.md`。

## Validation and Acceptance
Python 3.9 与 Python 3.13 双版本编译及受影响与新增测试全通过。
