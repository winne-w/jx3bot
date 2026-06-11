# JJC role_identities global_id 索引命中修复计划

## 背景

JJC 对局详情身份投影中，`role_identities` 的 `global_id` 查询偶发慢。线上 `explain` 显示：

- `{"identity_key": "global_id:<id>"}` 可命中 `idx_identity_key`
- `{"global_id": "<id>"}` 会走 `COLLSCAN`
- `{"global_id": {"$eq": "<id>", "$type": "string"}}` 可命中 partial index `idx_global_id`

原因是 `idx_global_id` 是 `global_id` 为 string 的 partial index，普通等值查询没有显式包含 partial 条件，Mongo 查询计划可能不使用该索引。

## 目标

- 修改 `RoleIdentityRepo` 中按 `global_id` 查身份的查询条件，使其显式包含 `$type: "string"`。
- 保持现有身份解析优先级和返回结构不变。
- 避免扩大到索引结构调整或数据迁移。

## 变更范围

- `src/storage/mongo_repos/role_identity_repo.py`
  - 增加内部 helper 构造 `global_id` string 查询条件。
  - 替换 `find_by_global_id()` 与 `resolve_best_identity_with_id()` 中的 `global_id` 等值查询。
- 本计划文件与 `docs/exec-plans/index.md`。

## 验证

- 使用 `runtime_config.json` 的 Mongo 连接对目标查询执行 `explain`，确认：
  - `keysExamined=1`
  - `docsExamined=1`
  - `winningPlan` 包含 `idx_global_id`
- 执行 `python -m py_compile src/storage/mongo_repos/role_identity_repo.py`。

## 回滚

- 将 `global_id` 查询条件恢复为普通等值查询即可；不涉及数据变更和索引变更。

## 状态

- 2026-06-09：已实现并验证。
  - `role_identity_repo.py` 的 `global_id` 查询已显式包含 `$type: "string"`。
  - Mongo `explain` 确认新版 `$or` 查询命中 `idx_global_id` 与 `idx_identity_key`，`keysExamined=1`、`docsExamined=2`、`executionTimeMillis=0`。
  - `python -m unittest tests.test_role_identity_repo` 通过。
  - `python -m py_compile src/storage/mongo_repos/role_identity_repo.py tests/test_role_identity_repo.py` 通过。
