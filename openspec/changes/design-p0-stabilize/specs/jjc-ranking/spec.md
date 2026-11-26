# JJC 排名与对局查询 Delta（design-p0-stabilize）

## ADDED Requirements

### Requirement: 过期奇穴快照在回源重刷保存时原地升级 schema 版本

当对局详情重刷保存奇穴快照且 `snapshot_hash` 已存在旧版文档时，`JjcMatchSnapshotRepo.save_talent_snapshot` MUST 无字段路径冲突地更新 `talents`、`schema_version` 与 `last_seen_at`，并保留原 `created_at`，使后续读取直接命中最新 schema 版本缓存。

#### Scenario: 旧版奇穴快照触发回源后重新保存相同 hash
- **WHEN** 同一 `snapshot_hash` 再次调用 `save_talent_snapshot`
- **THEN** 更新操作将最新顺序 `talents` 与当前 `TALENT_SNAPSHOT_SCHEMA_VERSION` 写入 `$set`，`created_at` 仅保存在 `$setOnInsert`
