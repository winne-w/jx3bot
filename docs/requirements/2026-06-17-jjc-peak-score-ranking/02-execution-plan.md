# JJC 7 天历史最高分排名执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

本计划完成后，系统会在每天 09:00 基于最近两个 JJC 排名快照的时间点，分别生成过去 7 天历史对局中的推栏分数最高分榜和游戏分数最高分榜。统计对象来自本地已同步对局参与者，而不是当前排行榜成员，因此可以覆盖洗车后掉出排行榜但历史对局已入库的玩家。

## Progress

- [x] 完成需求口径确认
- [x] 完成方案文档
- [x] 完成执行计划确认
- [x] 完成投影字段实现
- [x] 完成历史投影回填能力验证
- [x] 完成最高分排名存储与聚合实现
- [x] 完成 09:00 定时任务接入
- [x] 完成自动化验证
- [x] 完成手工冒烟验证
- [x] 完成 review
- [x] 完成验收记录

## Surprises & Discoveries

真实 Mongo 抽样显示 `jjc_match_detail` 原始对局详情中玩家节点有 `mmr`、`score`、`total_score`，但 `jjc_match_participants` 当前样例只保留合并后的 `total_mmr`。前端对局详情文案明确 `mmr` 展示为“推栏分数”，`total_score` 展示为“游戏分数”。

Claude 子 agent 执行被请求但不可用，两个 worker 均返回 `API Error: 402 Insufficient Balance`，本次实现改为主 agent 本地完成。

## Decision Log

2026-06-17：最高分排名不从排名快照成员出发，而是从历史对局参与者出发。原因是当前排行榜成员无法覆盖洗车后掉榜玩家。

2026-06-17：统计窗口使用排名快照 `timestamp` 作为锚点，窗口为向前 7 天。原因是用户希望 09:00 向前取最近两个统计结果，并按各自统计时间回看历史对局。

2026-06-17：分数字段按前端既有文案确定，`mmr` 为推栏分数，`total_score` 为游戏分数，`score` 仅作为游戏分数兜底。

2026-06-17：结果单独落库，不写回心法排名明细。原因是心法排名与历史最高分排名统计对象和排序口径不同。

## Outcomes & Retrospective

已完成参与者投影拆分分数字段、历史最高分聚合 service、`jjc_peak_score_rankings` 存储 repo、09:00 定时任务、Mongo 索引和文档联动。历史回填复用现有 `scripts/backfill_jjc_match_participants.py`，小批量 dry-run 已验证可从历史详情重建参与者投影。

本次未新增前端/API 展示入口，最高分结果先落 Mongo，后续如需页面查看可基于 `jjc_peak_score_rankings` 增加只读 API。

## Context and Orientation

相关入口和文件：

- `public/jjc-ranking-stats.html`：现有对局详情分数字段展示文案。
- `src/storage/mongo_repos/jjc_match_participant_repo.py`：构建 `jjc_match_participants` 参与者投影，需新增拆分分数字段和聚合查询。
- `scripts/backfill_jjc_match_participants.py`：历史投影回填入口，需在字段扩展后复用验证。
- `src/storage/mongo_repos/jjc_ranking_stats_repo.py`：读取最近两个排名快照时间点。
- `src/plugins/status_monitor/jobs.py`：新增 09:00 最高分统计定时任务；现有 09:00 日常推送 job 保持不变。
- `src/infra/mongo.py`：新增集合与索引。
- `docs/design-docs/database-design.md`：同步记录新增字段、集合和索引。

## Plan of Work

第一阶段扩展参与者投影。修改 `JjcMatchParticipantRepo.build_participants_from_match_detail()`，保存 `tuilan_score`、`game_score`、`game_score_source`、`raw_mmr`、`raw_score`、`raw_total_score`。补充单测，确认从对局详情构建出的参与者行保留拆分字段。

第二阶段验证历史回填。复用 `scripts/backfill_jjc_match_participants.py`，先 dry-run 小批量，再在手工环境执行 apply。脚本本身如果无需改动，则只补测试或文档；如需要只回填缺失字段模式，再新增参数并保持默认 dry-run。

第三阶段新增最高分排名存储。创建或扩展 repo，支持按最近两个排名快照时间取锚点、按锚点和分数类型 upsert 统计结果、查询是否已完成。新增 `jjc_peak_score_rankings` 集合设计和索引。

第四阶段新增聚合 service。按锚点窗口从 `jjc_match_participants` 查询 3v3 可用参与者，分别按推栏分数和游戏分数聚合角色最高分，保留最高分对应 `match_id`、`match_time` 和来源字段。

第五阶段接入 09:00 定时任务。新增独立 scheduler job，读取最近两个快照，跳过已完成结果，执行最高分聚合并记录日志。不改现有 `push_daily_gte()` 与 `push_daily_jjc_ranking()` 行为。

第六阶段同步文档、测试和回归。更新数据库设计、runbook，并运行单测、编译检查和小批量 dry-run。

## Concrete Steps

1. 修改 `src/storage/mongo_repos/jjc_match_participant_repo.py`：
   - 新增拆分分数字段提取。
   - 新增按窗口聚合最高分所需查询方法，或者为 service 提供窗口游标读取方法。
   - 保持现有 `total_mmr` 字段兼容。

2. 修改 `tests/test_jjc_match_participant_repo.py`：
   - 覆盖 `mmr`、`total_score`、`score` 的投影字段。
   - 覆盖 `total_score` 缺失时使用 `score` 兜底。
   - 覆盖 `match_time` 优先使用接口返回的对局时间，不使用入库时间。

3. 视实现需要修改 `scripts/backfill_jjc_match_participants.py`：
   - 确认现有整场重建能补齐新字段。
   - 必要时增加 `--missing-score-fields-only` 或类似参数，但不作为首选。

4. 新增 `src/storage/mongo_repos/jjc_peak_score_ranking_repo.py`：
   - 保存 `jjc_peak_score_rankings`。
   - 提供 `load_done_result()`、`mark_processing()`、`save_done()`、`mark_failed()` 等幂等方法。

5. 新增 `src/services/jx3/jjc_peak_score_ranking.py`：
   - 读取最近两个排名快照时间点。
   - 为每个锚点生成 `tuilan` 和 `game` 两套结果。
   - 聚合时记录最高分对应 `match_id`、`match_time`、`score_source`。

6. 修改 `src/plugins/status_monitor/jobs.py`：
   - 新增独立 `@scheduler.scheduled_job("cron", hour=9, minute=0)` job。
   - 与现有 09:00 日常推送并存，避免互相依赖。

7. 修改 `src/infra/mongo.py`：
   - 为 `jjc_match_participants` 增加窗口统计索引。
   - 为 `jjc_peak_score_rankings` 增加唯一索引和查询索引。

8. 修改 `docs/design-docs/database-design.md`：
   - 记录 `jjc_match_participants` 新增字段。
   - 新增 `jjc_peak_score_rankings` 集合设计。

9. 修改 `docs/references/runbook.md`：
   - 增加历史投影回填命令。
   - 增加 09:00 最高分统计观察和重跑说明。

## Validation and Acceptance

自动化验证：

```bash
python -m unittest tests.test_jjc_match_participant_repo
python -m py_compile src/storage/mongo_repos/jjc_match_participant_repo.py scripts/backfill_jjc_match_participants.py
```

已通过。

实现最高分 service 后补充对应单测和编译检查：

```bash
python -m unittest tests.test_jjc_peak_score_ranking
python -m py_compile src/services/jx3/jjc_peak_score_ranking.py src/storage/mongo_repos/jjc_peak_score_ranking_repo.py src/plugins/status_monitor/jobs.py src/infra/mongo.py
```

已通过，并额外执行 `python -m unittest tests.test_jjc_ranking_stats_repo tests.test_status_monitor_jobs_config`。

手工冒烟：

```bash
.venv/bin/python scripts/backfill_jjc_match_participants.py --limit 100
.venv/bin/python scripts/backfill_jjc_match_participants.py --apply --yes --limit 100
```

已执行 dry-run 小批量验证：

```bash
.venv/bin/python scripts/backfill_jjc_match_participants.py --limit 1
```

结果：处理 1 个对局详情，生成 6 条参与者投影，dry-run 未写库。

验收标准：

- `jjc_match_participants` 新写入和回填行包含推栏分数、游戏分数及原始分数字段。
- 09:00 任务以最近两个排名快照 timestamp 为锚点生成结果。
- 最高分结果不是从排名成员生成，而是从窗口内所有本地 3v3 对局参与者生成。
- 每条最高分排名项包含对应 `match_id` 和 `match_time`。
- 统计窗口不使用入库时间字段。
