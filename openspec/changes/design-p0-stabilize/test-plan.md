# P0 止血测试与验证记录（test-plan.md）

日期：2026-11-26  
环境：Python 3.9.25（`_envs/py39`）与 Python 3.13.2（主仓 `.venv`）

## 自动化验证

1. **Python 3.9 语法与注解编译检查**：
   - 命令：`py_compile` 覆盖全部 9 个改动源码文件（`config.py`, `src/infra/mongo.py`, `src/plugins/config_manager.py`, `src/services/jx3/jjc_match_data_sync.py`, `src/services/jx3/jjc_sync_worker_runtime.py`, `src/storage/mongo_repos/jjc_match_snapshot_repo.py`, `src/storage/mongo_repos/jjc_sync_repo.py`, `src/storage/mongo_repos/role_identity_repo.py`, `src/utils/time_utils.py`）。
   - 结果：全部通过，无语法或 Python 3.9 注解不兼容错误。
2. **文件编码检查**：
   - 命令：`file requirements.txt`
   - 结果：`requirements.txt: ASCII text`（已从 UTF-16LE BOM CRLF 转为无 BOM UTF-8/ASCII LF）。
3. **双版本单元测试**：
   - Python 3.13：`tests.test_mongo_index_safety`, `tests.test_jjc_match_fact_repo`, `tests.test_jjc_snapshot_repo`, `tests.test_role_identity_repo`, `tests.test_jjc_sync_worker_runtime`, `tests.test_jjc_sync_p0_backoff`, `tests.test_jjc_sync_worker_queue`, `tests.test_jjc_match_data_sync`, `tests.test_config_manager`, `tests.test_time_utils`, `tests.test_tuilan_request` 共 227 项全部 `OK`。
   - Python 3.9：覆盖上述新增与核心回归及相邻 `test_jjc_ranking_force_sync`、`test_jjc_inspect_repo`、`test_jjc_match_detail_hydration` 全部 `OK`。
   - 备注：`tests.test_jjc_sync_repo.TestJjcSyncRepoRoleQueue.test_recover_expired_leases_updates_role_and_match` 为基线 `8a21a2b` 既有漂移（`FakeCollection` 未实现 `find`），与本阶段改动无关。

## 未离线覆盖项（需线上发布时手工/冒烟核验）

- 真实 MongoDB 启动 `_ensure_indexes` 日志（确认唯一索引无自动 drop、旧队列仅校验 `idx_identity_key`）。
- 线上 `jjc_talent_snapshot` 存量 `schema_version < 2` 文档抽样，验证回源后原地升级为 `schema_version=2`。
- 线上 4 个同步 worker 与 dispatcher 启动日志与 15 分钟观察。
