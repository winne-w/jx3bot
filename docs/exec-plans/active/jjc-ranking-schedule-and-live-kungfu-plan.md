# JJC 排名统计时间与实时心法查询计划

## 状态

- 2026-05-28：已实现并完成验证，待提交。

## 需求

1. 保留现有上周总结判断逻辑：仍由推栏 `defaultWeek` 和 `calculate_season_week_info()` 判断是否显示 `结算`。
2. 自动竞技排名统计从每天 08:00 改为每天 04:00 和 21:00，使用一个 cron 配置 `hour="4,21"`。
3. 排名统计查询心法和队友配置时，旧 `role_jjc_cache` 不能直接决定本次统计结果。
4. 如果实时接口查不到用户心法，仍允许从缓存的 `match_detail` 胜场心法做证据兜底。
5. 本次实时查询或兜底得到的结果仍写回心法缓存，保留缓存刷新能力。

## 影响范围

- `src/plugins/status_monitor/jobs.py`
  - 修改竞技排名定时任务 cron 小时字段。
  - 同步调整推送文案中的时间描述。
- `src/services/jx3/jjc_ranking.py`
  - `get_user_kungfu()` 不再通过 `load_kungfu_cache()` 命中直接返回。
  - 本次统计结果不再合并旧 `role_jjc_cache` 中的武器和队友字段。
  - 保留 `get_kungfu_from_cached_match_detail_win_history()` 作为实时接口无心法时的兜底。
- `tests/test_jjc_ranking_history_win_kungfu.py`
  - 调整测试，覆盖旧心法缓存不会提前返回、cached `match_detail` 仍可兜底。

## 非目标

- 不新增周一 12:00 专门任务。
- 不改变排行榜数据缓存策略。
- 不删除缓存集合或历史数据。
- 不改变手动命令入口。

## 验证

```bash
python -m unittest tests.test_jjc_ranking_history_win_kungfu
python -m py_compile src/plugins/status_monitor/jobs.py src/services/jx3/jjc_ranking.py
```

## 回滚

- 将定时任务 cron 恢复为 `hour=8`。
- 恢复 `get_user_kungfu()` 对 `load_kungfu_cache()` 的直接命中和旧缓存字段合并逻辑。
