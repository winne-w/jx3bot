# JJC role_identities zone + role_id 索引计划

## 背景

`RoleIdentityRepo.find_by_game_role_id()` 和 `resolve_best_identity_with_id()` 会按 `zone + role_id` 兼容查询旧身份字段：

- `{"zone": zone, "game_role_id": role_id}`
- `{"zone": zone, "role_id": role_id}`
- `{"identity_key": "game:<zone>:<role_id>"}`

当前已有 `idx_zone_game_role_id`，但没有 `zone + role_id` 索引。`explain` 显示 `zone + role_id` 分支会扫描同大区大量文档。

## 目标

- 为 `role_identities` 增加普通复合索引 `idx_zone_role_id`：`zone`, `role_id`。
- 不改变身份解析逻辑和数据结构。
- 同步数据库设计文档。

## 变更范围

- `src/infra/mongo.py`
- `docs/design-docs/database-design.md`
- `docs/exec-plans/index.md`
- 本计划文件

## 验证

- 在当前 Mongo 库创建/确认 `idx_zone_role_id`。
- 对 `{"zone": "...", "role_id": "..."}` 执行 `explain`，确认命中 `idx_zone_role_id`。
- 执行 `python -m py_compile src/infra/mongo.py`。

## 回滚

- 代码回滚：移除 `_ensure_indexes()` 中 `idx_zone_role_id`。
- 数据库回滚：如确认不再需要，可手工 `dropIndex("idx_zone_role_id")`。

## 状态

- 2026-06-09：已实现并验证。
  - `src/infra/mongo.py` 已新增 `role_identities.idx_zone_role_id`。
  - 当前 Mongo 库已创建 `idx_zone_role_id`，键为 `zone`, `role_id`。
  - `zone + role_id` 单分支 explain 命中 `idx_zone_role_id`。
  - `zone + game_role_id / zone + role_id / identity_key` 三分支 `$or` explain 命中 `idx_zone_game_role_id`、`idx_zone_role_id`、`idx_identity_key`。
  - `python -m py_compile src/infra/mongo.py` 通过。
