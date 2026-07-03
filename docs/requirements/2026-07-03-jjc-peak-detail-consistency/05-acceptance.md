# JJC 14 日最高分详情口径一致性验收记录

## Delivered Changes

- 新增 `GET /api/jjc/ranking-stats/peak-score/details`，从 14 日最高分聚合结果按心法返回详情成员。
- `public/jjc-ranking-stats.html` 在 `peak-game` 分布详情下改用新接口，并按 source 区分详情缓存 key。
- 新增路由单测与前端静态断言测试。

## Verification

- 自动化验证：`python -m unittest tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend`；`python -m py_compile src/api/routers/jjc_ranking_stats.py`
- 手工冒烟：未执行，需要在真实页面环境补充
- review：已完成自检，未发现阻塞问题

## Residual Risks

- 尚未在浏览器真实页面中验证 `peak-game` 详情展开后的视觉呈现和人数一致性。

## Rollback

回滚时撤销新增 `peak-score/details` 路由与前端 `peak-game` 详情分流逻辑，恢复原有详情读取路径。

## Acceptance

2026-07-03：实现已完成，等待用户在真实页面环境验收。
