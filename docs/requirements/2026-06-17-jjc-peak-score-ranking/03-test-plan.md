# JJC 7 天历史最高分排名测试计划

## Test Scope

测试覆盖参与者投影字段、历史回填、最高分聚合、09:00 定时任务入口和数据库索引文档一致性。不覆盖真实推栏在线同步完整性；09:00 统计只验证本地已入库数据口径。

## Automated Checks

- `tests.test_jjc_match_participant_repo`
  - 对局详情玩家 `mmr` 投影为 `tuilan_score`。
  - 对局详情玩家 `total_score` 投影为 `game_score`。
  - `total_score` 缺失时 `score` 可作为 `game_score` 兜底，并记录 `game_score_source`。
  - 投影 `match_time` 来自接口返回的对局发生时间，不来自入库时间。

- `tests.test_jjc_peak_score_ranking`
  - 最近两个排名快照只提供统计锚点，不提供统计对象。
  - 推栏分数榜按 `tuilan_score` 聚合最高分。
  - 游戏分数榜按 `game_score` 聚合最高分。
  - 同一角色多场对局只保留最高分，并记录对应 `match_id` 和 `match_time`。
  - 已完成同一 `anchor_timestamp + score_type + version` 时跳过重复统计。
  - 失败时记录 failed 状态和错误信息。

## Manual Smoke Tests

- 小批量 dry-run 回填：
  ```bash
  .venv/bin/python scripts/backfill_jjc_match_participants.py --limit 100
  ```

- 小批量 apply 回填：
  ```bash
  .venv/bin/python scripts/backfill_jjc_match_participants.py --apply --yes --limit 100
  ```

- 查询回填样例，确认存在 `tuilan_score`、`game_score`、`raw_mmr`、`raw_total_score`。

- 手动触发最高分聚合 service，确认生成两个锚点的 `tuilan` 和 `game` 结果。

## Data Regression

抽样选择一个已知 `jjc_match_detail`，核对：

- `data.detail.match_time` 与投影 `match_time` 一致。
- 玩家节点 `mmr` 与投影 `tuilan_score` 一致。
- 玩家节点 `total_score` 与投影 `game_score` 一致。
- 最高分结果里的 `match_id` 可以回查到对应对局详情。

## Observability

09:00 任务日志需要记录：

- 最近两个锚点 timestamp。
- 每个锚点窗口起止时间。
- 每种分数口径参与统计的对局数、参与者数、生成排名项数。
- 跳过已完成统计的原因。
- 失败异常和状态写入结果。

## Result

已执行：

```bash
python -m unittest tests.test_jjc_match_participant_repo tests.test_jjc_peak_score_ranking
python -m py_compile src/storage/mongo_repos/jjc_match_participant_repo.py src/storage/mongo_repos/jjc_peak_score_ranking_repo.py src/services/jx3/jjc_peak_score_ranking.py src/plugins/status_monitor/jobs.py src/infra/mongo.py scripts/backfill_jjc_match_participants.py
python -m unittest tests.test_status_monitor_jobs_config
python -m unittest tests.test_jjc_ranking_stats_repo tests.test_status_monitor_jobs_config
python -m unittest tests.test_jjc_ranking_stats_repo tests.test_status_monitor_jobs_config tests.test_jjc_peak_score_ranking
python -m py_compile tests/test_jjc_match_participant_repo.py tests/test_jjc_peak_score_ranking.py
python -m py_compile src/api/routers/jjc_ranking_stats.py src/storage/mongo_repos/jjc_ranking_stats_repo.py tests/test_jjc_ranking_stats_repo.py
node -e "const fs=require('fs');const html=fs.readFileSync('public/jjc-ranking-stats.html','utf8');const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]).filter(s=>s.trim());for(const s of scripts){new Function(s)};console.log('ok')"
.venv/bin/python scripts/backfill_jjc_match_participants.py --limit 1
```

结果均通过。dry-run 回填处理 1 个历史对局详情，生成 6 条参与者投影，未写库。
