# P0 止血与高风险缺陷修复执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

在不改变业务外部协议和存量集合 schema 的前提下，一次性消除评审识别的高优先级运行隐患：防止启动时自动删除唯一索引导致唯一约束丢失，补齐本地胜场装备读索引的代码声明与预检函数，修复奇穴快照 `schema_version=2` 无法升级导致的持续回源，消除失败对局退避期间的角色 10 秒重复翻页空转，为内置同步 worker/dispatcher 增加异常退避自愈监督，并修复 `config_manager` 错误吞没、`time_utils` 整年天数计算错误、`role_identity_repo` 别名重复追加及 `requirements.txt` UTF-16 编码问题。

## Progress
- [x] 完成需求边界梳理、存量单测契约排查与 OpenSpec 方案设计（2026-11-26）
- [x] 子任务 A：实现 Mongo 索引保护、装备读索引声明/预检、奇穴快照升级修复、身份别名 `$addToSet` 及单测与 `database-design.md` 更新
- [x] 子任务 B：实现同步对局退避延迟重排、内置 worker/dispatcher 退避自愈监督、清理零调用死代码及同步相关单测
- [x] 子任务 C：修复 `config_manager` 读取错误判断、`time_utils.time_ago_filter`、`config.py` 默认 `MONGO_URI`、`requirements.txt` UTF-8 转码及单测
- [x] 整合复核、Python 3.9 与 Python 3.13 全量测试验证、独立代码审查与本地分支提交

## Surprises & Discoveries

- `tests/test_jjc_match_fact_repo.py:1086` 明确断言非唯一索引 `idx_active_combo_time` 在 `partialFilterExpression` 变更时会由 `_ensure_indexes` 自动重建；因此索引保护应精确限定为“旧索引或目标索引任一为 `unique=True` 时拒绝自动 drop”，既保护全部唯一约束，又保持非唯一部分索引演进兼容。
- `git log` 显示 `save_talent_snapshot` 曾在 `e7afb47` 同时写入 `$setOnInsert` 与 `$set` 触发 Mongo 路径冲突，随后 `4a32c1d` 误从 `$set` 移除而非从 `$setOnInsert` 移除，导致 v1 快照永远无法升级为 v2。将 `created_at` 留在 `$setOnInsert`、`talents` 与 `schema_version` 移入 `$set` 即可同时解决冲突与升级闭环。
- `get_match_detail_sync_state` 返回 `interrupt` 是为了阻止角色同步水位越过尚未终态的对局；因此不能改为 `skip`，而应在 `_release_role_interrupted` 携带 `next_sync_after` 进入 `cooldown`，由 dispatcher 到期后重排。
- `TUILAN_SECRET_KEY` 为推栏公开签名盐值且 `tests/test_tuilan_request.py` 直接依赖其默认值，不能置空；仅清理 `MONGO_URI` 中的示例弱口令 `root:password`。

## Decision Log

- 2026-11-26：项目负责人明确授权按评审结论推进全部阶段直至上线与合入 `main`，并指示基于 `origin/main`（`8a21a2b`）独立开分支避开在途 `feat/unify-visual-style` 修改文件。
- 2026-11-26：本地胜场装备 3 个索引通过 `ensure_equipment_read_indexes` / `verify_equipment_read_indexes` 代码化，仅在 `JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED == 1` 时随 `_ensure_indexes` 自动创建，兼顾默认关闭时的启动耗时安全与开启时的索引自足。

## Outcomes & Retrospective

待实现与全量验证完成后回填。

## Context and Orientation

当前工作树基于 `origin/main`（`8a21a2b`）。涉及文件集中在三块互不重叠的边界：
1. 存储与数据库基础设施：`src/infra/mongo.py`、`src/storage/mongo_repos/jjc_match_snapshot_repo.py`、`src/storage/mongo_repos/role_identity_repo.py`、`docs/design-docs/database-design.md`。
2. JJC 对局同步与后台运行时：`src/services/jx3/jjc_match_data_sync.py`、`src/storage/mongo_repos/jjc_sync_repo.py`、`src/services/jx3/jjc_sync_worker_runtime.py`。
3. 配置、通用工具与依赖文件：`src/plugins/config_manager.py`、`src/utils/time_utils.py`、`config.py`、`requirements.txt`。

上述文件均不在 `feat/unify-visual-style` 的在途修改集合中。

## Plan of Work

将实现拆分为三个文件集合互不重叠的并行工作流（Storage/DB、Sync/Runtime、Config/Utils），由子 agent 或模块级任务分别完成实现与对应单元测试，最后由主 agent 统一运行 Python 3.9 与 Python 3.13 全量回归、执行 `py_compile` 语法与注解兼容检查、完成独立审查并提交到 `refactor/design-p0-stabilize`。

## Concrete Steps

1. 修改 `src/infra/mongo.py`：在 `_safe_index` 中拦截 `existing_unique or desired_unique` 的定义变更自动删除；新增 `EQUIPMENT_READ_V1_INDEXES`、`ensure_equipment_read_indexes`、`verify_equipment_read_indexes` 并在开关启用时调用；移除 `server_master_cache` 与 `jjc_role_recent` 数字字段上的无效 `expireAfterSeconds`；精简 `jjc_sync_role_queue` 启动索引至 `idx_identity_key`。同步更新 `docs/design-docs/database-design.md`。
2. 修改 `src/storage/mongo_repos/jjc_match_snapshot_repo.py:save_talent_snapshot` 与 `tests/test_jjc_snapshot_repo.py`，使 `$set` 写入 `talents`、`schema_version`、`last_seen_at`，`$setOnInsert` 仅写 `created_at`；修改 `src/storage/mongo_repos/role_identity_repo.py:upgrade_identity` 使用 `$addToSet` 维护 `aliases`。
3. 修改 `src/services/jx3/jjc_match_data_sync.py` 与 `src/storage/mongo_repos/jjc_sync_repo.py`：为 `JjcSyncMatchDetailClaimError` 与中断释放链路传递 `next_sync_after`，使退避期对局触发角色 `cooldown` 延迟重排而非 10 秒空转，同时删除 4 个零调用死方法；修改 `src/services/jx3/jjc_sync_worker_runtime.py` 增加带退避的常驻监督循环并同步更新 `tests/test_jjc_sync_worker_runtime.py`。
4. 修改 `src/plugins/config_manager.py`、`src/utils/time_utils.py`、`config.py`、`requirements.txt`，补充对应单元测试（`tests/test_config_manager.py`、`tests/test_time_utils.py`）。

## Validation and Acceptance

- 运行 `python -m py_compile` 覆盖全部改动源码，确保 Python 3.9 语法与注解零问题。
- 在 Python 3.9（`_envs/py39`）与 Python 3.13（主仓 `.venv`）下运行新增及受影响单测与全量 `unittest discover`。
- 验证 `file requirements.txt` 输出为 UTF-8 ASCII/Unicode text（无 UTF-16 BOM 与 CRLF）。
