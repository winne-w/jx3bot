# JJC 14 日最高分详情口径一致性测试计划

## Test Scope

覆盖 14 日详情新路由、前端详情分流、未命中返回以及现有详情结构兼容性。角色近期战绩、对局详情弹窗和最高分聚合算法本身不在本次测试范围内。

## Automated Checks

- `python -m unittest tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend`
- `python -m py_compile src/api/routers/jjc_ranking_stats.py`

## Manual Smoke Tests

- 打开统计页，在 `peak-game` 分布视图展开某个心法详情，确认人数一致。
- 打开 `all` / `purple` 分布视图展开详情，确认仍显示当前快照成员。

## Data Regression

重点关注同一 `timestamp`、`range`、`kungfu` 在 `peak-game` 与 `all/purple` 下成员集不同的场景，确认缓存未串。

## Observability

关注新增 `peak-score/details` 路由的命中/未命中日志，以及前端页面是否出现“加载明细失败”。

## Result

已执行：

- `python -m unittest tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend`
- `python -m py_compile src/api/routers/jjc_ranking_stats.py`

结果：

- 单测 21 项全部通过。
- `py_compile` 通过。
- 未执行浏览器手工冒烟，需在真实页面环境补一轮展开详情验证。
