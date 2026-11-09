# JJC 14 日最高分详情口径一致性执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

本计划完成后，JJC 统计页中的“14日游戏最高分排名”分布卡和展开详情将严格来自同一份最高分聚合结果，不再出现“分布显示 9 人、详情只列 6 人”的口径冲突。同时，当前推栏排名快照的 `all` / `purple` 视图不受影响。

## Progress

- [x] 完成方案确认
- [x] 完成代码设计
- [x] 完成开发实现
- [x] 完成自动化验证
- [ ] 完成冒烟验证
- [x] 完成 review
- [x] 完成验收记录

## Surprises & Discoveries

- 当前前端 `ensureDetailLoaded()` 不区分外层 tab，所有分布详情都走 `/ranking-stats/details`。
- 14 日最高分分布并没有独立明细接口，但其列表与分布都已可从 `jjc_peak_score_rankings.items` 推导出来，因此无需新增存储层。

## Decision Log

2026-07-03：新增 `peak-score/details` 而不是复用 `/ranking-stats/details`。原因是两者数据源不同，强行复用只会继续混口径。

2026-07-03：14 日详情接口直接读取最高分聚合文档并按心法过滤，不新增持久化明细。原因是聚合结果已经具备渲染所需字段，本次应最小化改动。

2026-07-03：前端详情缓存 key 增加 source 维度。原因是相同 `timestamp/range/kungfu` 在不同 tab 下可能代表不同成员集。

## Outcomes & Retrospective

已新增 `/api/jjc/ranking-stats/peak-score/details`，前端 `peak-game` 分布详情已切到新接口，并把详情缓存 key 按 source 分离。自动化测试覆盖了新路由成功/未命中场景，以及前端静态分流断言。

本次没有做浏览器手工冒烟，因为当前会话未启动页面服务；残余风险主要在真实页面上需要再确认一次 `peak-game` 详情按钮和图标渲染是否与现有字段完全兼容。

## Context and Orientation

相关文件与职责：

- `src/api/routers/jjc_ranking_stats.py`：JJC 统计只读接口，新增 14 日详情路由。
- `src/storage/mongo_repos/jjc_peak_score_ranking_repo.py`：读取最高分聚合结果，复用现有 `load_result()`。
- `public/jjc-ranking-stats.html`：详情展开逻辑、详情缓存 key、接口 URL 选择。
- `tests/test_jjc_ranking_stats_router.py`：新增路由级单测。
- `tests/test_jjc_ranking_stats_frontend.py`：新增前端静态断言，锁定 `peak-game` 详情分流。

## Plan of Work

第一阶段先补失败测试。为路由新增 14 日详情成功/未命中测试，并为前端新增静态断言，要求出现新的 `buildPeakDetailsUrl()` 和 `peak-game` 条件分流。

第二阶段实现后端路由。复用 `JjcPeakScoreRankingRepo.load_result()` 读取文档，验证 `timestamp`、`score_type`、`range`、`version`，按 `kungfu` 过滤 `items` 并返回兼容旧详情结构的 payload。

第三阶段实现前端分流。新增 14 日详情 URL 构建函数，调整详情缓存 key，`ensureDetailLoaded()` 根据 `currentOuterTab` 选择数据源。

第四阶段执行自动化验证，并补充测试、review、验收文档结果。

## Concrete Steps

1. 修改 `tests/test_jjc_ranking_stats_router.py`
   - 新增 `peak-score/details` 成功返回明细测试。
   - 新增 `peak-score/details` 在 repo 未命中时返回 `not_found` 测试。
   - 覆盖服务端按 `kungfu` 过滤成员、透传 `score_type/version` 的行为。

2. 修改 `tests/test_jjc_ranking_stats_frontend.py`
   - 断言页面存在 `buildPeakDetailsUrl`。
   - 断言 `peak-game` 详情逻辑会命中新接口或相关 source 分流标识。

3. 修改 `src/api/routers/jjc_ranking_stats.py`
   - 新增 `get_jjc_peak_score_details()` 路由函数。
   - 复用现有 `_RANGE_LIMITS` 与 `JjcPeakScoreRankingRepo`。
   - 将 `items` 过滤为 `members` 后返回兼容前端的数据结构。

4. 修改 `public/jjc-ranking-stats.html`
   - 新增 `buildPeakDetailsUrl()`。
   - 调整 `buildDetailsCacheKey()`，纳入 source 或 tab。
   - 更新 `ensureDetailLoaded()`，在 `peak-game` 下请求新接口。

5. 修改 `docs/requirements/2026-07-03-jjc-peak-detail-consistency/03-test-plan.md`
   - 回填实际执行命令与结果。

6. 修改 `docs/requirements/2026-07-03-jjc-peak-detail-consistency/04-review.md`
   - 记录本次 review 结论。

7. 修改 `docs/requirements/2026-07-03-jjc-peak-detail-consistency/05-acceptance.md`
   - 记录最终交付、验证与残余风险。

## Validation and Acceptance

自动化验证命令：

```bash
python -m unittest tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend
python -m py_compile src/api/routers/jjc_ranking_stats.py
```

手工冒烟：

1. 打开 JJC 排名页，切到“14日游戏最高分排名”分布视图。
2. 选择一个人数大于 0 的心法，记录卡片人数。
3. 展开详情，确认成员数与卡片人数一致。
4. 切回 `all` / `purple`，确认详情仍能正常加载当前快照成员。

验收标准：

- `peak-game` 分布卡人数与展开详情人数一致。
- `all` / `purple` 详情行为不变。
- 自动化测试覆盖新增路由与前端分流行为。
