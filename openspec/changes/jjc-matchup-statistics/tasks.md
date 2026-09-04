# JJC 组合对阵统计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可按绝对时间、双方 0～3 心法包含组合和双方三人平均游戏分区间查询的 JJC 3v3 原始胜率统计，并分页下钻现有装备与奇穴详情。

**Architecture:** `jjc_match_detail` 继续作为完整主事实，统一持久化编排只在主事实确认成功后分别触发身份、玩家和新增对局事实投影。新增每场一条的 `jjc_match_facts` active/tombstone 读模型，以纯构建函数、源摘要和 CAS 保证实时写入与历史回填一致；查询 service 在事实 repo 上计算方向、统计和唯一分页，FastAPI router 与独立静态页面只承担输入输出适配。

**Tech Stack:** Python 3.9、NoneBot2、FastAPI、Motor/PyMongo、MongoDB aggregation、标准库 `unittest`、原生 HTML/CSS/JavaScript、OpenSpec。

---

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

用户完成本计划后，可以选择最近 1/3/7/14 天或最长 14 天自定义范围，输入双方平均游戏分左闭右开区间，并让两边分别选择 0～3 个心法。非空组合使用队内无序、保留重复数量的“包含”匹配；空边表示任意配置；双方为空时只浏览该时间和分段内的全部有效对局。页面仅展示唯一对局数、方向样本数、双方胜场与胜率、双向命中数和缺分数，不输出优势判断。

实现必须先解决现有 `JjcInspectRepo.save_match_detail()` 吞写入异常和多保存入口重复投影的问题，再建立事实双写。历史数据先 dry-run、后显式 `--apply --yes` 回填，并在目标 Mongo 通过索引体积和查询性能门禁后才注册页面入口。点击列表对局继续调用现有 `/api/jjc/ranking-stats/match-detail`，不复制装备、奇穴或 replay。

## Progress

### 1. 主事实保存契约与统一持久化编排

- [x] 1.1 新建 `tests/test_jjc_inspect_repo.py`，增加主事实写入失败抛异常、成功返回 `True`、非法 `match_id` 抛 `ValueError`、主文档先于装备/奇穴快照写入以及快照失败不改变主事实成功结果的失败测试；运行 `python -m unittest tests.test_jjc_inspect_repo -v`，确认新用例先失败。
- [x] 1.2 修改 `src/storage/mongo_repos/jjc_inspect_repo.py:JjcInspectRepo.save_match_detail()`：先按规范整数 `match_id` 执行 `jjc_match_detail.update_one` 的 upsert，成功返回 `True`，主写异常原样抛出；把 `_extract_snapshots()` 调整为主写后的独立 best-effort 派生并用结构化日志记录失败；运行 1.1 测试确认通过。
- [x] 1.3 新建 `tests/test_jjc_match_detail_persistence.py`，用 fake repo/projector 写出 `MatchDetailPersistenceService.persist()` 的失败测试：只有主保存返回 `True` 才分别尝试身份、玩家、事实三个投影，任一派生失败不得阻断另外两个，unavailable 触发玩家清理和事实 tombstone，主保存失败不得调用任何派生。
- [x] 1.4 新建 `src/services/jx3/match_detail_persistence.py`，实现 `MatchDetailPersistenceService` 和结构化 `PersistMatchDetailResult`；事实 projector 依赖在阶段一允许为 `None`，配置后才调用。对主事实、身份投影、玩家投影、事实投影分别记录 `match_id/source/schema/error`，满足 1.3 测试，不在 service 中依赖 NoneBot 事件或发送能力。
- [x] 1.5 修改 `src/services/jx3/jjc_ranking_inspect.py`、`src/services/jx3/jjc_ranking.py` 和 `src/services/jx3/jjc_match_data_sync.py` 的保存入口，删除“直接 save 后各自投影”的重复编排：覆盖 inspect cache miss、cache hit replay 补齐、`no data found`、排名预热和 sync 补 occurrence `match_time`/replay 后重新保存；规范源摘要变化时分配较新的 `cached_at`，仅补不进入摘要的 replay/身份字段时允许沿用版本。先补 `tests/test_jjc_ranking_inspect.py`、`tests/test_jjc_match_data_sync.py` 入口顺序、版本与失败隔离测试，再做最小改动使其通过。
- [x] 1.6 修改 `src/services/jx3/singletons.py`，先以 fact projector 未配置的方式装配一个共享 `MatchDetailPersistenceService` 并注入 ranking、inspect、sync 三条链路，阶段二再注入实际事实 projector；运行 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_match_data_sync tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration -v`，确认现有详情、装备、奇穴和 replay 行为无回归。
- [x] 1.7 只暂存本组源码与测试，检查 `git diff --cached --check` 后提交 `refactor: unify JJC match detail persistence`；提交不得包含用户工作区中的其他改动。

### 2. 对局事实纯构建、源摘要与 CAS 存储

- [x] 2.1 新建 `tests/test_jjc_match_fact.py`，先覆盖并运行失败测试：正整数 ID/时间、显式非 3v3、两队各三人、六个心法 ID、胜负 XOR、无 `global_id` 仍构建、`total_score` 到 `score` 回退、0 分有效、非法分数变缺失、时间来源优先级、重复心法组合键、active/tombstone、canonical SHA-256 和 schema 重建。
- [x] 2.2 新建 `src/services/jx3/jjc_match_fact.py`，实现 Python 3.9 兼容的纯函数 `normalize_positive_int()`、`normalize_game_score()`、`extract_match_time()`、`encode_combo_key()`、`build_match_fact()` 和 `build_source_hash()`；组合键固定为 `v1:<count>:<sorted ids>`，hash 使用 UTF-8、键排序和紧凑分隔符的 canonical JSON，运行 2.1 测试至通过。
- [x] 2.3 新建 `tests/test_jjc_match_fact_repo.py`，用 fake Motor collection 先覆盖失败测试：`match_id` 整数唯一、较新版本 active/tombstone 可互换、较旧版本跳过、等时异 hash 冲突、等时同 hash 高 schema 重建、其余 no-op，以及 tombstone 清除组合/分数/摘要字段。
- [x] 2.4 新建 `src/storage/mongo_repos/jjc_match_fact_repo.py`，实现 `JjcMatchFactRepo.apply_projection()`、`get_projection_state()` 和批量核验读取；返回稳定状态 `inserted/updated/tombstoned/skipped_old/conflict/noop`，以单条条件更新或事务外原子 CAS 防止旧回填复活，运行 2.3 测试至通过。
- [x] 2.5 在 `tests/test_jjc_match_fact_repo.py` 增加查询索引合同测试，再修改 `src/infra/mongo.py:_safe_index()` 使其比较 `partialFilterExpression`，并为 `jjc_match_facts` 创建 `idx_match_id` unique、`idx_active_combo_time` partial active 与 `idx_active_time` partial active；断言每个复合索引最多一个数组字段且 tombstone 不进入 partial index。
- [x] 2.6 新建 `src/services/jx3/match_detail_fact_projection.py` 和对应 `tests/test_jjc_match_fact_projection.py`，实现由同一 `build_match_fact()` 生成 active 或 tombstone 后调用 repo CAS；将该 projector 接入 `MatchDetailPersistenceService`，并证明 unavailable、结构非法、分数缺失、旧来源晚到和投影异常日志行为。
- [x] 2.7 运行 `python -m unittest tests.test_jjc_match_fact tests.test_jjc_match_fact_repo tests.test_jjc_match_fact_projection tests.test_jjc_match_detail_persistence -v` 与相关文件 `python -m py_compile`；只暂存本组改动后提交 `feat: add JJC match fact projection`。

### 3. 组合查询领域服务与 Mongo 聚合

- [x] 3.1 新建 `tests/test_jjc_matchup_service.py`，先覆盖请求规范化失败测试：时间正整数且不超过 14 天、分数整数 `0..1000000` 且下限小于上限、双方数组最多三项且保留重复、`page=1..100000`、`page_size=20/50/100`、未知但合法历史心法 ID 可查、双方 ID 升序回显。
- [x] 3.2 新建 `src/services/jx3/jjc_kungfu_meta.py`，把 `public/jjc-ranking-stats.html` 的 `kungfuIconIdByName` 迁为服务端 ID/名称/类别/图标/展示序号目录，并合并 `config.KUNGFU_META`；新增测试保证 ID 唯一、正整数、目录排序稳定、所有现有可展示心法有名称与类别。
- [x] 3.3 新建 `src/services/jx3/jjc_matchup.py`，实现 `JjcMatchupFilters`、`JjcMatchupService.get_meta()`、`normalize_filters()` 和 `search()`；meta 固定返回时间预设、分页大小与 limits，service 只返回原始数据，不产生优势、置信区间或样本充分性字段，使 3.1 与 3.2 测试通过。
- [x] 3.4 扩展 `tests/test_jjc_match_fact_repo.py`，先用确定的事实样本覆盖候选与统计失败测试：奶秀 vs 明教其余不限、策藏 vs 奶花、策藏 vs 气明歌、重复心法、A/B 交换、单边空、双方空、A=B、正向/反向/双向、分数左闭右开、缺分计数和唯一分页。
- [x] 3.5 在 `src/storage/mongo_repos/jjc_match_fact_repo.py` 实现查询 pipeline：固定 `active=true` 与 `[start_time,end_time)`；双方非空取规范组合键中字典序较小者做单键索引锚点，单边非空锚定该边，双方空走时间索引；按 `match_time DESC, match_id DESC` 排序后计算 forward/reverse，再用 `$facet` 同时返回缺分、统计、total 和当前页，不在 facet 内重复排序。
- [x] 3.6 在 service 层固化统计响应：`total=match_count`，有方向时 `orientation_sample_count=match_count+bidirectional_match_count`、双方胜场之和等于方向样本数、百分比胜率四舍五入一位；有方向零样本返回胜场 0/胜率 null，双方空返回方向样本与双向数 0、胜场和胜率 null；摘要保持源 team1/team2 并返回四种 `matched_orientations`。
- [x] 3.7 运行 `python -m unittest tests.test_jjc_matchup_service tests.test_jjc_match_fact_repo -v`，并针对 A/B 交换、双向、单边空、双方空逐项断言统计恒等式；只暂存本组改动后提交 `feat: query JJC matchup statistics`。

### 4. FastAPI 元数据与搜索接口

- [x] 4.1 新建 `tests/test_jjc_matchups_router.py`，沿用现有 fake FastAPI/router 测试模式，先覆盖 `GET /api/jjc/matchups/meta` 统一成功结构，以及 `POST /api/jjc/matchups/search` 的正常响应、非对象 JSON、损坏 JSON、字段类型错误、页码越界和 service 异常统一错误结构。
- [x] 4.2 新建 `src/api/routers/jjc_matchups.py`：router 接收 `Request` 并在函数内捕获 `await request.json()` 失败，不使用会在进入函数前产生默认 422 的 Pydantic body；调用 singleton 中的 `JjcMatchupService`，仅通过 `success_response()`/`error_response()` 返回 `status_code/status_msg/data`。
- [x] 4.3 修改 `src/api/__init__.py` 显式 include 新 router，修改 `src/services/jx3/singletons.py` 装配共享 fact repo 与 matchup service；增加路由注册测试并运行 `python -m unittest tests.test_jjc_matchups_router tests.test_jjc_ranking_stats_router -v`。
- [x] 4.4 执行 `python -m py_compile src/api/routers/jjc_matchups.py src/services/jx3/jjc_matchup.py src/services/jx3/jjc_kungfu_meta.py src/storage/mongo_repos/jjc_match_fact_repo.py`，确认没有 Python 3.10 `X | None` 或内置泛型联合注解进入 FastAPI 可解析路径；提交 `feat: expose JJC matchup APIs`。

### 5. 独立查询页面与详情复用

- [x] 5.1 新建 `tests/test_jjc_matchups_frontend.py`，先用静态结构断言失败测试覆盖：meta/search API、默认最近 7 天、绝对时间 URL、`Asia/Shanghai` 结束日期次日 00:00、双方 0～3 标签、重复心法、交换按钮、分数未填禁用、20/50/100 分页、原始统计字段、四种方向标记和现有 match-detail API。
- [x] 5.2 新建 `public/jjc-matchups.html`，从 meta API 加载心法目录，不保留第二份心法 ID 常量；实现滚动 N×24 小时与自定义日期转换、URL 恢复、请求竞态序号、加载/空/错误状态、筛选重置页码、交换双方但不重排源队伍摘要。
- [x] 5.3 实现统计与列表展示：只显示 match_count、orientation_sample_count、双方胜场/百分比胜率、bidirectional_match_count、missing_score_match_count；每场显示时间、地图、时长、双方三人心法/游戏分、平均分和胜负，双向样本在列表中只出现一次。
- [x] 5.4 从 `public/jjc-ranking-stats.html` 提取或在新页内最小复用现有详情弹窗所需适配，点击 `match_id` 调用 `/api/jjc/ranking-stats/match-detail` 展示装备与奇穴；不得修改详情接口合同或新增奇穴选择率统计。
- [x] 5.5 运行 `python -m unittest tests.test_jjc_matchups_frontend tests.test_jjc_ranking_stats_frontend -v`，本地启动后手工检查 `/public/jjc-matchups.html` 的查询、交换、URL 刷新、分页和详情弹窗；提交 `feat: add JJC matchup statistics page`。

### 6. 历史回填、核验与性能门禁

- [x] 6.1 新建 `tests/test_backfill_jjc_match_facts.py`，先覆盖 CLI 与批处理失败测试：默认 dry-run、写入必须同时 `--apply --yes`、`--verify-only` 只读、正整数 `--resume-after-match-id` 水位、batch/limit、active/tombstone、缺分、结构跳过、旧版本跳过、冲突和异常计数。
- [x] 6.2 新建 `scripts/backfill_jjc_match_facts.py`，只投影 `jjc_match_detail` 必需字段，按整数 `match_id ASC` 分批复用 `build_match_fact()` 与 repo CAS；输出批次范围、累计统计和最后成功水位，verify 报告缺失、孤儿、应失效、hash 不一致、schema 过期与构建失败，运行 6.1 测试和 `--help`。
- [x] 6.3 新建 `tests/test_check_jjc_matchup_performance.py` 与 `scripts/check_jjc_matchup_performance.py`：复用实际 repo pipeline，对单心法、双心法、完整组合、单边空、双方空和 7/14 天输出 `explain("executionStats")` 的索引名、阻塞 SORT、keys/docs examined、耗时和 facet 错误，并抽样外推 active/tombstone 文档、组合索引项和 BSON 体积。
- [x] 6.4 在目标 Mongo 先运行 backfill dry-run 和存储外推，不满足磁盘/缓存预算时停止；确认后才运行 `python scripts/backfill_jjc_match_facts.py --apply --yes --batch-size 500`，保存开始/结束水位和统计，再执行 `python scripts/backfill_jjc_match_facts.py --verify-only --batch-size 500`，要求缺失、孤儿、应失效、hash 不一致与 schema 过期均为 0 或有逐条解释。
- [x] 6.5 对目标数据运行性能脚本：常见 7 天查询要求不超过 2 秒，14 天或双方空不超过 5 秒，并检查无不可接受阻塞 SORT/facet 内存；若失败，先拆分统计/分页 pipeline 或增加按日预聚合及其测试，全部已确认查询形态达标前不开放页面。
- [x] 6.6 运行 `python -m unittest tests.test_backfill_jjc_match_facts tests.test_check_jjc_matchup_performance -v` 与两个脚本的 `python -m py_compile`；提交 `feat: backfill and verify JJC match facts`，不提交包含线上数据、Mongo URI 或凭据的输出文件。

### 7. 文档、全量回归、review 与验收

- [x] 7.1 更新 `README.md` 增加 meta/search API 与 `/jx3/jjc-matchups.html` 页面说明；更新 `docs/design-docs/database-design.md` 记录 `jjc_match_facts` 字段、active/tombstone、三个索引和 repo 归属；更新 `docs/references/runbook.md` 记录 dry-run/apply/verify、性能门禁、页面冒烟与非破坏性回滚。
- [x] 7.2 在当前 change 新增并填写 `test-plan.md`，逐项映射 spec scenarios 到自动化测试、目标 Mongo explain 和手工页面冒烟；不得把未执行的命令记录为已通过。
- [x] 7.3 运行新功能自动化集：`python -m unittest tests.test_jjc_inspect_repo tests.test_jjc_match_detail_persistence tests.test_jjc_match_fact tests.test_jjc_match_fact_repo tests.test_jjc_match_fact_projection tests.test_jjc_matchup_service tests.test_jjc_matchups_router tests.test_jjc_matchups_frontend tests.test_backfill_jjc_match_facts tests.test_check_jjc_matchup_performance -v`。
- [x] 7.4 运行既有 JJC 回归：`python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration tests.test_jjc_match_participant_projection tests.test_jjc_match_participant_repo tests.test_jjc_ranking_inspect tests.test_jjc_match_data_sync tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend -v`，再执行相关源码和脚本 `python -m py_compile`、`nb plugin list --json` 与 `openspec validate jjc-matchup-statistics --strict`。
- [x] 7.5 使用子 agent 对照 proposal/design/spec/tasks/diff 做只读 code review，强制检查凭据硬编码、分层依赖、所有保存入口、CAS/tombstone、统计恒等式、Python 3.9、URL 时间、错误包装和文档一致性；主 agent 复核意见并把结论写入 change 的 `review.md`。
- [x] 7.6 手工验收最近 7 天奶秀 vs 明教、策藏 vs 奶花、策藏 vs 气明歌、单边空、双方空、重复心法、双向命中、分数边界、越界页、URL 分享和奇穴详情；把输入、结果和未覆盖外部依赖写入 `acceptance.md`。
- [x] 7.7 仅在自动化、回填核验、性能门禁、review 和手工验收都有新鲜证据后更新本计划的 Progress、Surprises、Decision Log 与 Outcomes，并提交最终文档；方案生效后再执行 OpenSpec specs sync/archive 流程。

## Surprises & Discoveries

现有 `JjcInspectRepo.save_match_detail()` 在同一个 `try` 中先写装备/奇穴快照、再写主详情，并吞掉所有异常。实现任务 1 必须先把主事实成功语义从派生快照中分离，否则统一编排仍无法证明“保存成功后才投影”。

现有详情保存/补齐至少分布在 inspect cache miss、cache hit replay 后台补齐、unavailable、排名预热和 sync worker 的 occurrence time/replay 补齐阶段。sync 当前会补临时 payload 后直接投影，因此本计划要求补齐后重新持久化主详情，再进入同一编排。

`config.KUNGFU_META` 只有拼音、名称和类别，心法图标 ID 目前硬编码在 `public/jjc-ranking-stats.html`。实现时必须把 ID 目录迁到 Python 元数据模块，让新页面只消费 meta API，同时保持旧页面兼容直至另行评估是否复用该 API。

现有测试主要使用标准库 `unittest`、fake repo/collection 和 import stub；本计划沿用该模式，不为单一功能引入新的测试框架或前端构建工具。

任务 1.1/1.2 实现时确认，若主写前已将完整装备/奇穴替换为 hash，快照失败会留下无法补水的主详情；最终采用“完整详情主写 → 快照派生 → CAS 压缩”的两阶段写法。压缩更新同时匹配 `match_id/cached_at/完整 data` 且禁用 upsert，避免较慢旧保存覆盖同一对局的较新详情。

任务 1.5/1.6 复审时确认，统一事件来源不能直接替代既有派生来源语义：参与者继续使用 `ranking_detail/warmup/sync_worker`，sync 身份投影继续使用 `match_detail_sync` 与 `priority=-10`。默认 Python 3.13.2 在多个 `IsolatedAsyncioTestCase`/`asyncio.to_thread` 用例整套串行时出现可复现的事件循环停滞；相同用例单跑、分组回归和 reviewer 运行均可通过，阶段验证因此保留分组证据，未为该环境行为修改生产代码。

任务 2.1/2.2 复审时确认，`cached_at` 版本水位可以是带小数的有限正数，但不接受数值文本；同步补入的 `data.match_time` 优先于旧 `detail.match_time`。`source_hash` 仅覆盖规范源摘要，保留原始 `total_score/score` 而排除 `game_score/score_source`、组合键与聚合分数等派生字段，使同源高 schema 可重建而不被误判为等时冲突。

任务 2.3/2.4 复审时确认，CAS 首写正确性依赖 `match_id` 唯一索引；因此必须先完成 2.5 的 `idx_match_id unique`，才能在 2.6 接入并启用事实 projector。repo 拒绝缺失或超出 BSON 边界的源水位，并在替换前移除调用方 `_id`，避免不可变 `_id` 或重复键异常被误判为 CAS 竞争。质量复审遗留两项不阻断观察：可再增加首写 `_id` 冗余断言，repo 虽接受大写 SHA-256 文本，但当前唯一构建器固定产生小写 hash。

任务 2.5 复审确认，`partialFilterExpression` 已纳入既有索引定义漂移比较，三个事实索引的键序、唯一性和 active partial 合同准确；组合索引只包含 `any_team_combo_keys` 一个数组字段，tombstone 不进入查询索引。规格与质量复审均无 Critical、Important 或 Minor 问题，37 项事实构建与 repo 测试通过。

任务 2.6/2.7 复审确认，事实 projector 只复用 `build_match_fact()` 并透明交给共享 repo CAS，不复制 active/tombstone 领域规则；`source` 保留为统一调用合同和持久化日志上下文，事实版本仍来自 payload。singleton 已启用共享 projector，repo 异常由持久化编排按 `stage=fact` 结构化记录且不阻断其他派生。规格与质量复审均批准，主 agent 独立运行 60 项阶段测试、相关 `py_compile` 和 `git diff --check` 通过。

任务 3.1 的 RED 测试复审补齐了 A/B 两侧对非列表输入与未知历史心法 ID 的对称覆盖，并避免宽泛捕获 `ImportError` 掩盖真实依赖错误。最终 20 个测试在生产模块尚不存在时产生预期 RED，规格与质量复审均批准；该任务只定义请求规范化合同，GREEN 留给 3.3。

任务 3.2 将旧页面 32 项心法 ID/图标映射固化为服务端目录，保留旧页兼容；当前展示目录按名称合并 `config.KUNGFU_META`，配置独有条目不会扩大目录，缺失或非法类别回退到目录默认分类。复审补充了配置快照、返回隔离、名称 trim 和 `dps/healer/tank` 白名单；最终 8 项测试与 `py_compile` 通过，规格和质量复审均批准。

任务 3.3 完成严格请求规范化、固定 meta 合同与异步 repo 委托；service 只在 repo 原始结果上附加独立的 `normalized_filters`，不生成优势、置信区间或样本充分性字段。31 项 service/meta 测试与 `py_compile` 通过，规格和质量复审均批准；仅保留一个不阻断的测试增强建议，可后续用完整请求深拷贝直接断言输入不变性。

任务 3.4 的 RED 测试复审将 aggregate fake 从关键字扫描收紧为可执行 Mongo 阶段的精确合同，并模拟 `$facet` 原始数组形状，要求 repo 独立解包缺分、统计、total 与 items。8 个场景覆盖包含组合、重复数量、空边、双向、精确分数和时间边界、真实 tombstone、零有效但有缺分，以及同时间跨页的 `match_id DESC` tie-break；既有 18 项 repo/index 回归保持通过，规格与质量复审均批准。

任务 3.5 实现单次 aggregate 的候选、稳定排序、方向、分数与四分支 facet，并对空 facet 提供稳定零值解码。质量复审发现新增 repo 反向依赖 services，最终将 `normalize_positive_int`/`encode_combo_key` 唯一下沉至 `src/utils/jjc_match_fact.py`，service 保持公开重导出，repo 与 service 都只依赖 utils；100 项相关回归、`py_compile` 与 diff 检查通过，规格与质量复审均批准。真实 Mongo 的阻塞排序、扫描量与 facet 容量仍按 6.3/6.5 门禁验证。

任务 3.6/3.7 固化方向样本恒等式、半入舍入胜率、双空 null 语义和分页元数据。复审发现 Mongo `_id` 与内部投影字段若原样透传会破坏 JSON 编码和摘要合同，最终由 service 构造全新的白名单对局摘要，并按查询上下文校验三种有方向标记或双空的空方向；ObjectId、CAS、组合键和分数中间字段不再进入响应。主 agent 独立运行 62 项查询主回归与 50 项相关事实/投影回归，相关 `py_compile` 和 diff 检查通过，规格与质量复审均批准；保留 `duration=True`/`score_avg=NaN` 的显式测试增强建议，现实现已正确拒绝。

任务 4.1 的 RED 测试锁定 meta/search 路径、Request 内 JSON 解析、非对象/损坏 JSON、参数与服务异常的稳定公共错误，以及必须调用项目统一 success/error wrapper。复审补齐了 `sys.modules` 桩恢复、wrapper 精确签名与调用 spy、meta 异常和错误详情不泄漏；最终 8 个测试方法、11 个场景仅因 router 尚未实现而预期失败，规格与质量复审均批准。

任务 4.2 实现 `Request` 内部 JSON 解析与固定公开错误映射，所有成功和失败只经过项目统一 response wrapper；普通异常不会泄漏内部详情，且不捕获 `BaseException`，保留取消传播。Terra 规格与质量复审均批准，凭据红线 PASS；主 agent 独立运行 8 项路由测试、`py_compile` 和新增文件 diff 检查通过。

任务 4.3 显式注册 matchup router，并以已有唯一 `jjc_match_fact_repo` 同时装配事实 projector 与 `JjcMatchupService`。首次规格复审指出缺少共享实例回归合同，原实现 agent 补充隔离构造 spy，锁定 repo 只实例化一次且两项服务接收同一对象；复审和质量审查随后批准，凭据红线 PASS。主 agent 独立运行 40 项 API/事实投影测试、相关 `py_compile` 与 diff 检查通过。

任务 4.4 提交前门禁确认 40 项 API/事实投影回归通过，任务列出的 router/service/repo 及装配和测试文件全部 `py_compile` 通过，新增 FastAPI 路径未使用 Python 3.10 `X | Y` 联合注解；diff 空白检查通过。凭据扫描仅命中既有 `cfg.TOKEN` 配置引用与测试空值，不存在硬编码凭据。

任务 5.1 的静态合同先后收敛了两类风险：不以孤立 token 冒充运行时证明，也不把合法页面锁死在具名 payload、特定 swap 或请求封装。最终 11 项页面合同覆盖规定结构，另有 2 项 endpoint/本地心法目录 helper 正反例；Terra 规格与质量审查均批准，凭据红线 PASS。主 agent 独立运行时 2 项 helper 通过、11 项仅因 `public/jjc-matchups.html` 缺失而按预期 RED，测试文件 `py_compile` 与 no-index 空白检查通过。运行时数据流、交换、重复选择、方向与详情点击精确行为保留给 5.5 浏览器 QA。

任务 5.2 直接沿用现有排行榜的浅色蓝粉视觉体系，用户明确跳过 ImageGen，不保留概念图资产。首轮规格审查发现生产 API 前缀、在途请求失效、非法绝对时间 URL 降级和 meta 分页大小回显四项运行时缺口；复审又发现查询按钮会把 `MouseEvent` 误作请求体。质量审查进一步发现非法 URL 降级后控件未同步，以及自定义时间上限、meta 防御和交换状态重置问题。全部问题修复后，Terra 规格复审为 `Spec compliant`、质量复审为 `Approved`，凭据红线 PASS。主 agent 独立运行新页面 13 项合同测试、旧排行榜 4 项前端回归、内联 JavaScript 语法与新文件 no-index 空白检查均通过；真实浏览器中的数据流、响应式和视觉验收仍按 5.5 执行。

任务 5.3 完成六类客观统计、四种方向说明、源 `team1/team2` 顺序下的唯一对局列表和页码状态。审查先后发现残缺统计/玩家可能显示 `undefined`、大型列表不应作为 live region、统计与列表非原子渲染、合法零方向样本会被误拒、胜率未按 service 的 half-up 一位小数复核，以及规范化筛选回写前缺少 meta 边界校验；全部改为先验证统计恒等式、精确胜率、完整摘要、分页与规范筛选，再一次性渲染，异常时清空半真状态。Terra 规格复审 `Spec compliant`、质量复审 `Approved`，凭据与 DOM 注入红线 PASS；主 agent 独立运行 17 项新旧前端回归、JavaScript 语法、no-index 空白检查通过。浏览器真实数据、分页与移动端视觉仍按 5.5 验收。

任务 5.4 在新页面内用 DOM API 最小适配现有详情能力：点击对局 ID 请求生产前缀下的既有 match-detail 路由，按源 `team1/team2` 展示六名玩家、装备与奇穴，并提供 unavailable、加载、格式错误和请求错误状态。弹窗加入 AbortController 与请求序号、成功缓存、遮罩/Escape 关闭、Tab 焦点环、焦点恢复和移动端内层滚动；外部图片仅允许 HTTP(S)，失败时显示可访问占位，动态数据不使用 HTML 注入。审查发现最初玩家结构校验过松，硬化后又误拒 service 合法的空姓名字符串，最终按 `MatchDetailPlayerInfo` 真实合同允许空字符串并保留“未知角色”降级，同时拒绝空对象和非法装备/奇穴元素。Terra 规格与质量复审均通过，凭据/XSS 红线 PASS；主 agent 独立运行 17 项前端回归、JavaScript 语法与 no-index 空白检查通过，真实焦点、图片和详情数据仍按 5.5 浏览器验收。

任务 5.5 验收时当前会话未提供 Browser plugin，按前端测试技能记录为 `Browser plugin not available` 并使用 Playwright Chromium 1.51。用户明确跳过 ImageGen，因此没有概念图资产可对照；视觉 fidelity 直接对照 `public/jjc-ranking-stats.html` 的浅色蓝粉、白色面板和克制阴影体系。主 agent 在 1440×1000 与 390×844 两种 viewport 下以真实浏览器和 route mock 验证 meta/search/match-detail 数据流：默认 7 天、分数未填禁用、重复心法与空边、绝对时间 URL、交换双方 payload 且源 `team1/team2` 不重排、刷新 URL 自动重放、20/50/100 每页、前后翻页、四种方向中的正向/反向/双向、六名玩家装备与奇穴、Escape 关闭、焦点恢复、移动端弹窗内层 `overflow:auto` 均符合预期；两种 viewport 均无横向溢出，console warning/error 与 page error 均为空。首次浏览器运行发现 `.match-detail-overlay { display:grid }` 覆盖 `hidden` 状态并透明拦截页面点击，随后先增加失败测试，再用 `.match-detail-overlay[hidden] { display:none!important }` 做单点修复，最终重复浏览器全流程通过。截图只保存在 `/tmp/jjc-matchups-{desktop,detail,mobile,mobile-detail}.png`，不作为仓库资产提交。

任务 5.5 的 Terra 规格复核确认页面实现 `Spec compliant`；质量/安全复核为 `Approved`，凭据红线 PASS，未发现 Blocker、High 或 Medium 问题。唯一 Low 观察是仓库测试仍以静态合同为主，浏览器级路径由本任务的临时 Playwright 脚本和记录证据覆盖。主 agent 随后独立运行 18 项新旧前端回归、测试文件 `py_compile`、内联 JavaScript 解析、凭据/危险 DOM API 扫描及空白检查，均通过。

任务 6.1/6.2 以 TDD 完成安全回填与只读核验脚本。多轮真实 Motor 无网络探针和 Terra 规格复核发现并修复了 Database 真值判断、无默认数据库 URI 的 `ConfigurationError` 回退、非法 schema 漏报、必要字段投影过宽/缺失、孤儿游标批大小和异常路径 client 释放问题；字段级投影同时兼容 `data` 直接详情与 `data.detail` 包装，且不读取装备、奇穴大字段。最终独立 Terra 规格复核为 `Spec compliant`，质量复核为 `Approved`、凭据红线 PASS；主 agent 独立运行 71 项回填/事实/repo 回归、CLI `--help`、`py_compile`、空白检查、凭据扫描与 Motor 默认库/真值探针均通过。全程未连接真实 Mongo，未执行 `--apply --yes`。

任务 6.3 以 TDD 完成只读 explain 与容量外推脚本：10 种查询形态直接捕获实际 repo pipeline，容量在历史回填前从 `jjc_match_detail` 以 `$sample` 后字段级 `$project` 抽样，并复用同一 `build_match_fact()` 区分 active、缺分 active、tombstone、非法 ID 与构建失败。Terra 规格与质量复核发现并修复了 rejected plan SORT/索引误报、standalone 与 shard `stages[].$cursor` 获选计划提取、大集合抽样阶段顺序以及假 builder 镜像测试问题；四轮范围复审关闭所有 Critical/Important，凭据红线 PASS。主 agent 独立运行 21 项性能脚本测试、46 项回填/性能组合测试与 92 项回填/性能/事实/repo 回归，两个 CLI `--help`、`py_compile`、空白、凭据和写操作扫描均通过。全程未连接真实 Mongo；目标数据容量、explain 结构与耗时仍属 6.4/6.5 未完成门禁。

2026-08-27 首次进入 6.4/6.5 时得到的宿主 Motor/PyMongo `AutoReconnect` 是隔离环境的假故障：诊断命令运行在 `network: restricted` 沙箱中。同时 feature worktree 没有主工作区被 Git 忽略的 `runtime_config.json`，脚本因而继承了全局 `MONGO_URI`，错误指向本机另一个项目 `fuyao-ai-quality-inspector-scheduler` 占用的 27017；非隔离 ping 虽成功，但实际读命令返回 Mongo 错误码 13 `Unauthorized`。在 worktree 建立同样受 Git 忽略的本地符号链接，复用主工作区真实运行配置后，脱敏 ping 返回 `ok`，无需修改业务代码、Mongo 服务或凭据。

真实目标库只读容量检查确认 `jjc_match_detail` 有 1,622,185 条；1000 条随机样本外推约 1,552,431 条 active、69,754 条 tombstone，active BSON 约 3.34 GB、组合索引项约 20.72 million。500 条默认 dry-run 成功读取并构建 400 条 active 与 100 条 tombstone，`apply_failed/build_failed/blocking_failure/conflict` 均为 0，全程未写库。当前 `jjc_match_facts` 为空，10 种 explain 虽均成功但扫描 0 条，不能作为真实性能结论；6.4/6.5 继续保持未完成，必须先取得明确 apply 授权并核对容量预算，再在已回填数据上重跑性能门禁。

2026-09-01 在 MongoDB 4.4.30 目标库完成新的上线前门禁。预检时数据库 storage 约 26.1 GB、索引约 1.95 GB，文件系统约 100.2 GB；只针对空 `jjc_match_facts` 创建并逐项核对 `idx_match_id` unique、`idx_active_combo_time` active partial 与 `idx_active_time` active partial，没有调用会影响其他集合的全局索引初始化。全量默认 dry-run 先以 `batch-size=500` 扫描 169,500 条至稳定水位 `254438072`，再用 `--resume-after-match-id 254438072 --batch-size 5000` 完成剩余 1,454,288 条；合并后覆盖全部 1,623,788 条详情，预测 active 1,494,220、tombstone 129,568、结构非法 7,326，`invalid_match_id/score_incomplete/build_failed/apply_failed/conflict/blocking_failure` 均为 0。复核事实文档仍为 0，说明 dry-run 全程未写事实；结束时文件系统统计约 73.3 GB 已用、26.9 GB 可用。阶段六/事实投影 100 项回归、相关 `py_compile` 与 diff 检查通过；凭据扫描只命中测试专用 `example.invalid` URI。6.4/6.5/6.6 仍保持未完成，下一步必须取得明确 `--apply --yes` 授权，按 500 条批次写入并核验后才能得到真实性能结论和提交阶段六。


## Decision Log

2026-08-25：用户确认不固定主客方向，配置只表示两边分别包含所选心法；每边允许 0～3 项、队内无序且可重复，单边空表示任意，双方空表示浏览全部。

2026-08-25：双方同时满足 A/B 时，一场产生两个方向样本但分页只出现一次；只展示原始数据，不输出优势判断、置信区间或样本充分性结论。

2026-08-25：分数使用双方各三人游戏分平均值，双方都必须命中 `[score_min, score_max)`；结构有效但缺分的事实保留并只计入 `missing_score_match_count`。

2026-08-25：选择每场一条 `jjc_match_facts`，不在八百余万玩家投影上做主查询；失效使用保留源水位的 inactive tombstone，防止较旧回填恢复已失效事实。

2026-08-25：首版保留普通页码和 `match_time DESC, match_id DESC`，只保证事实集合不变时分页稳定；同步/回填期间允许页码漂移，不增加快照或游标协议。

2026-08-25：最近 N 天在查询时转为绝对 Unix 秒写入 URL，自定义结束日期包含全天；点击对局复用现有详情接口查看装备与奇穴，首版不做奇穴选择率汇总。

2026-08-25：三路只读方案复审最终均为 Ready；关键修订包括明确保存成功契约、入口矩阵、时间/分数规范化、canonical hash/CAS 真值表、tombstone、单键组合索引锚点、请求错误包装和性能门禁。

2026-08-25：事实构建的 `source_hash` 与派生 schema 解耦；同一规范源在不同 schema 版本下 hash 保持一致，仅真实源字段变化才改变 hash。

2026-08-25：事实 repo 使用完整替换与源水位/hash/schema 三元精确条件实现无事务 CAS；`idx_match_id unique` 是启用首写前的强前置，任务顺序固定为 2.5 建索引后才执行 2.6 接入。

## Outcomes & Retrospective

阶段一已完成主详情保存契约和统一持久化编排：inspect、ranking warmup 与 sync 共享主保存边界，主保存失败不触发派生，unavailable、版本推进和既有身份/参与者来源语义均有回归测试。规格复审与质量复审均已批准；本阶段未创建 `jjc_match_facts`，未执行线上数据回填或外部写入。后续阶段仍需记录实际数据规模、查询性能、未覆盖风险以及与原设计的偏差。

## Context and Orientation

`src/storage/mongo_repos/jjc_inspect_repo.py` 是 `jjc_match_detail` 保存边界并负责详情中的装备/奇穴快照抽取；`src/services/jx3/jjc_ranking_inspect.py`、`jjc_ranking.py` 和 `jjc_match_data_sync.py` 是当前详情保存与补齐入口。`src/services/jx3/match_detail_identity_projection.py` 和 `match_detail_participant_projection.py` 分别派生身份及玩家读模型；新增 `match_detail_persistence.py` 只负责编排这些既有投影与新增事实投影，不吸收查询业务。

新增 `src/services/jx3/jjc_match_fact.py` 只做无副作用的规范化、组合键、事实/tombstone 和 source hash 构建。`src/storage/mongo_repos/jjc_match_fact_repo.py` 是 `jjc_match_facts` 唯一 Mongo 访问边界，负责 CAS、聚合与核验读取。`src/services/jx3/jjc_matchup.py` 负责 API 输入合同、方向统计和响应结构；`src/api/routers/jjc_matchups.py` 只解析 Request、调用 service、包装统一响应。

`src/services/jx3/jjc_kungfu_meta.py` 是页面心法目录单一服务端来源；`public/jjc-matchups.html` 是无构建步骤的独立页面。`scripts/backfill_jjc_match_facts.py` 只负责安全回填与核验，`scripts/check_jjc_matchup_performance.py` 负责目标 Mongo explain 和容量外推。Mongo 索引仍统一在 `src/infra/mongo.py:_ensure_indexes()` 创建，集合契约同步到 `docs/design-docs/database-design.md`。

## Plan of Work

阶段一先把主详情写入改为可验证契约，并以一个持久化 service 收敛所有入口。该阶段不创建或写入新事实，便于用现有回归证明行为等价。阶段二以 TDD 实现纯事实构建与 repo CAS，再把事实 projector 作为第三个独立派生接入统一编排，开始对新写入进行双投影。

阶段三、四完成组合查询 service、Mongo pipeline 和 FastAPI 合同，但在历史回填与目标性能验证前不公开页面入口。阶段五实现静态页面和详情复用。阶段六默认 dry-run 地估算历史事实与索引成本，经人工核对后才显式 apply，并以 verify/explain 作为开放门禁。最后同步长期文档，运行新旧回归、子 agent review 和手工验收。

测试任务可以由子 agent 先行承担：事实纯函数、repo CAS、查询统计、router、前端静态合同和脚本 CLI 相互独立；保存入口重构、singletons 集成、Mongo 索引和最终回归由主 agent 串行整合，避免共享装配文件冲突。所有子 agent 只能修改分配的测试或独立新文件，主 agent 在合并前检查 diff 并重新运行完整验证。

## Concrete Steps

事实构建模块固定提供三个最小接口，后续任务不得自行改名导致测试和调用方漂移：`encode_combo_key(kungfu_ids: List[int]) -> str`、`build_source_hash(source_summary: Dict[str, Any]) -> str`、`build_match_fact(match_id: Any, payload: Dict[str, Any], schema_version: int) -> Dict[str, Any]`。

`build_match_fact()` 对可定位 `match_id` 总是返回可写文档：结构有效时 `active=True` 并包含队伍摘要；unavailable、非 3v3 或结构非法时 `active=False` 并包含 `invalid_reason/source_cached_at/source_hash/schema_version`。无法规范化正整数 `match_id` 时抛 `ValueError`，不得写无主键 tombstone。

repo 的稳定调用合同为 `JjcMatchFactRepo.apply_projection(document: Dict[str, Any]) -> str` 和 `JjcMatchFactRepo.search_matchups(filters: Dict[str, Any]) -> Dict[str, Any]`。编排 service 的稳定调用合同为 `MatchDetailPersistenceService.persist(match_id: Any, payload: Dict[str, Any], source: str, seen_doc: Optional[Dict[str, Any]] = None) -> PersistMatchDetailResult`。

API 请求示例固定为：

```json
{
  "start_time": 1786982400,
  "end_time": 1787587200,
  "score_min": 2400,
  "score_max": 2600,
  "team_a_kungfu_ids": [10080],
  "team_b_kungfu_ids": [10242],
  "page": 1,
  "page_size": 20
}
```

所有实现批次先运行目标测试确认失败，再做最小实现并重跑至通过；每次提交前执行 `git diff --check`，只 `git add` 当前任务明确列出的路径。不得使用 `git add .`，不得提交 `runtime_config.json`、Mongo URI、线上 explain 原始数据或用户已有无关改动。

回填操作顺序固定为：

```bash
python scripts/backfill_jjc_match_facts.py --help
python scripts/backfill_jjc_match_facts.py --batch-size 500
python scripts/backfill_jjc_match_facts.py --verify-only --batch-size 500
python scripts/backfill_jjc_match_facts.py --apply --yes --batch-size 500
python scripts/backfill_jjc_match_facts.py --verify-only --batch-size 500
```

第一次与第二次命令只读；只有同时出现 `--apply --yes` 才允许写库。真实 apply 必须由用户或运维明确授权，不能从“执行本计划”推断为已授权线上写入。

## Validation and Acceptance

自动化验收以 Progress 7.3 和 7.4 的完整命令退出码 0、`unittest` 无 failure/error 为准。Python 3.9 兼容性以所有新增/修改 router、service、repo、script 的 `python -m py_compile` 退出码 0 为准；插件装配以 `nb plugin list --json` 能列出既有插件且无导入异常为准；规格一致性以 `openspec validate jjc-matchup-statistics --strict` 通过为准。

数据验收要求 dry-run 先给出 active、tombstone、缺分、结构跳过、旧版本、冲突和预计索引体积；apply 后 verify 的缺失、孤儿、应失效、hash 不一致和 schema 过期必须为 0，或每条异常都有保留原因。目标 Mongo explain 必须证明常见 7 天查询不超过 2 秒，14 天或双方空查询不超过 5 秒；若出现阻塞 SORT、facet 内存或扫描量不可接受，页面不得开放，先回到查询实现增加拆分或预聚合。

业务验收至少复核奶秀 vs 明教确实只约束两边各包含指定心法、其余四个不限；策藏 vs 奶花和策藏 vs 气明歌支持不同组合数量；单边空、双方空、重复心法、A=B 和双向命中符合统计公式；双方三人平均分都处于左闭右开区间；分页一场只出现一次；URL 重放绝对时间；详情能显示既有装备与奇穴；页面和 API 均不产生优势结论。

回滚不删除主详情、玩家投影、装备或奇穴。出现问题时先隐藏 `/jx3/jjc-matchups.html` 和新 router，停止事实 projector 调用；`jjc_match_facts` 可保留供核验或重建。只有在另行确认备份、作用集合和恢复路径后才允许物理删除该可重建集合。
