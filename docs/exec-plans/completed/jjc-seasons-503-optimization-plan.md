# JJC 赛季列表接口（`?action=seasons`）503 排查与优化计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

排查并彻底优化 `https://qike.rickchen.cn/jx3/jjc-ranking-stats.html` 页面加载时 `GET /jx3bot/api/jjc/ranking-stats?action=seasons` 容易返回 HTTP 503（`read_failed`）的问题，在不破坏现有 V2 装备快照完整性与 1.5s 读预算契约的前提下，从数据库索引、服务端聚合、业务层缓存/Singleflight 并发合并、前端自动重试与手动恢复四层联动根治。

## Progress

- [x] 复现线上 503 并定位 4 项根因（`time=1.689s` 精确命中 `METADATA_READ_TIMEOUT = 1.5s`）
- [x] 补齐 `jjc_ranking_stat_summaries` 两个复合索引并同步 `docs/design-docs/database-design.md`
- [x] `JjcRankingStatsRepo.list_seasons()` 改为服务端 `aggregate` 分组聚合，解除 512 快照文档硬上限，并在 `_readable_snapshot_query` 复用 BSON 长度避免重复编码
- [x] 新增 `src/services/jx3/jjc_seasons_cache.py`（30s 短 TTL 缓存 + epoch 护栏 + Singleflight 并发合并），在 `jjc_ranking_stats.py` 接入并在 `jjc_ranking.py` 写入后主动失效
- [x] 同步更新 `public/jjc-ranking-stats.html` 与 `public/index.html`（`seasonsRequestId` 防重入、网络与 502/503/504 自动退避重试、失败“重试”按钮）
- [x] 补齐单测与真实 Mongo 传输契约适配（`tests/test_jjc_seasons_optimization.py`、`tests/test_jjc_ranking_equipment_metadata_batch.py`、`tests/test_jjc_ranking_stats_repo.py`）
- [x] 完成三轮独立只读子 Agent Code Review（全部 P0/P1/P2 问题闭环）
- [x] 完成 Python 3.9 编译检查、双 HTML 一致性检查与 57 项单测回归

## Surprises & Discoveries

- 线上实测 `GET /jx3bot/api/jjc/ranking-stats?action=seasons` 耗时 `1.689s` 返回 `503 {"status_code":1,"status_msg":"read_failed","data":{}}`，证明核心瓶颈是无索引全表扫描（`find({"schema_version": 2})` + 全表 `find` 拉回 Python 聚合）触发了 1.5 秒 `METADATA_READ_TIMEOUT`。
- 第一轮实现将缓存放在 `storage/mongo_repos` 层并使用了 `id(db)` 作 key，经独立 review 发现：① 违反 `PROJECT_CONTEXT.md` 缓存策略应归属 `services` 层的分层约束；② 开启 `JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED=1` 时读侧 `_equipment_db` 与写侧 `_get_db()` 对象不同导致写失效失效；③ 真实 Mongo 传输测试 `MetadataBatchMongo` 对 `mode="seasons"` 断言 `len(finds) == 2`。
- 第二轮独立 review 进一步发现 `getattr(repo.db, "name", None)` 会提前触发 `_EquipmentReadDatabase.__getattr__`，破坏懒加载语义且可能在热缓存命中前抛出 `EquipmentReadRuntimeError`。最终通过 `_seasons_cache_key(repo)` 按类型安全分流彻底解决。

## Decision Log

- 缓存与 Singleflight 独立收敛到 `src/services/jx3/jjc_seasons_cache.py`（纯标准库，零 NoneBot/Mongo 反向依赖），由 `src/api/routers/jjc_ranking_stats.py` 调用，由 `src/services/jx3/jjc_ranking.py` 在快照写入成功后统一 `invalidate()`。
- 维持原有 `METADATA_READ_TIMEOUT = 1.5s` 和 V2 完整性校验语义不变，不放宽预算、不截断数据。
- `list_seasons()` 优先使用 MongoDB 服务端 `aggregate`（带 `maxTimeMS=1500` 与 `batchSize=512`），在仅 mock 了 `find` 的旧测试中优雅回退到 `find`。

## Outcomes & Retrospective

- 所有改动严格符合 Python 3.9 类型注解、分层依赖方向、双 HTML 一致性与数据库文档同步规范。
- 多轮独立只读 review 发现了跨库写失效、Singleflight 异常消费、真实 Mongo 传输断言和懒代理提前触发 4 个关键问题并全部在提交前修复。

## Context and Orientation

- 路由层：`src/api/routers/jjc_ranking_stats.py`
- 缓存编排层：`src/services/jx3/jjc_seasons_cache.py`、`src/services/jx3/jjc_ranking.py`
- 存储层：`src/storage/mongo_repos/jjc_ranking_stats_repo.py`、`src/infra/mongo.py`
- 前端双入口：`public/jjc-ranking-stats.html`、`public/index.html`
- 文档与测试：`docs/design-docs/database-design.md`、`tests/test_jjc_seasons_optimization.py`、`tests/test_jjc_ranking_equipment_metadata_batch.py`、`tests/test_jjc_ranking_stats_repo.py`

## Plan of Work

按“索引补齐 -> 服务端聚合 + V2 BSON 复用 -> `services` 层缓存/Singleflight 与写失效 -> 前端防重入退避重试 -> 测试与多轮独立 Review -> 提交与生产发布”顺序推进。

## Concrete Steps

1. `src/infra/mongo.py` 新增 `idx_schema_version_season_timestamp` 与 `idx_current_season_timestamp`，同步 `docs/design-docs/database-design.md`。
2. `src/storage/mongo_repos/jjc_ranking_stats_repo.py` 将 `list_seasons()` 改为服务端 `aggregate`，并在 `_readable_snapshot_query` 复用 BSON 长度。
3. 新增 `src/services/jx3/jjc_seasons_cache.py`，接入 `src/api/routers/jjc_ranking_stats.py`（安全 `_seasons_cache_key`）与 `src/services/jx3/jjc_ranking.py`（写后 `invalidate()`）。
4. 同步更新 `public/jjc-ranking-stats.html` 与 `public/index.html` 的 `loadDateList` / `fetchSeasonsWithRetry` 与 `.status-retry-btn`。
5. 更新并扩充单测，执行编译、双 HTML 校验、全量测试与多轮独立评审。

## Validation and Acceptance

- 编译检查：`_envs/py39/bin/python -m py_compile src/infra/mongo.py src/services/jx3/jjc_seasons_cache.py src/services/jx3/jjc_ranking.py src/api/routers/jjc_ranking_stats.py src/storage/mongo_repos/jjc_ranking_stats_repo.py tests/test_jjc_seasons_optimization.py tests/test_jjc_ranking_equipment_metadata_batch.py`（通过）
- 双入口一致：`diff -q public/index.html public/jjc-ranking-stats.html`（零差异）
- 回归测试：`_envs/py39/bin/python -m unittest tests.test_jjc_seasons_optimization tests.test_jjc_ranking_stats_frontend tests.test_jjc_data_center_navigation tests.test_jjc_ranking_equipment_metadata.MetadataScanBudgets tests.test_jjc_ranking_equipment_metadata_batch tests.test_jjc_ranking_equipment_snapshot_reader`（57 项全部通过，2 项需显式 `JJC_TEST_MONGO_URI` 跳过）
- 回滚方案：非破坏性变更；两个新索引可保留，代码回退至上一提交并重启服务即可恢复原行为。
