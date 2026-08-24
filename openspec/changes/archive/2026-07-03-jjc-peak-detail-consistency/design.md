# JJC 14 日最高分详情口径一致性方案文档

## Problem

当前 14 日最高分分布卡和其展开详情不共用同一数据源。分布卡读 `peak-score` 聚合结果，展开详情却读当前推栏排名快照详情，因此会在同一个心法上展示两套不同人数，直接破坏页面口径可信度。

## Goals

- 修复 14 日最高分分布与详情的口径错位。
- 尽量复用现有前端详情渲染代码，降低改动面。
- 通过自动化测试锁定后续回归。

## Non-Goals

- 不重构前端整体视图切换逻辑。
- 不把 14 日详情写回 `jjc_ranking_stat_details`。
- 不改变角色近期战绩、对局详情等下钻接口。

## Current State

`GET /api/jjc/ranking-stats/peak-score` 会返回 14 日最高分榜列表，并基于返回的 `items` 现场构建心法分布；页面在 `peak-game` 分布视图上展示的心法人数就是这份 `items` 的分组结果。

`GET /api/jjc/ranking-stats/details` 读取的是 `jjc_ranking_stat_details` 中保存的当前推栏排名快照成员列表，前端 `ensureDetailLoaded()` 当前不区分 tab，统一命中这个接口。

因此在 `peak-game` 视图下：

- 卡片人数：来自 14 日最高分聚合
- 展开明细：来自当前推栏快照

## Proposed Solution

新增只读接口 `GET /api/jjc/ranking-stats/peak-score/details`。该接口直接读取 `JjcPeakScoreRankingRepo.load_result()` 返回的最高分聚合文档，复用现有 `range`、`score_type`、`version` 参数约束，在服务端对 `items` 按心法过滤并返回 `members` 数组。

前端新增 `buildPeakDetailsUrl()`，在 `currentOuterTab === "peak-game"` 时改用新接口；其他 tab 保持旧接口不变。详情缓存 key 增加数据源维度，避免同一个 `timestamp/range/kungfu` 在不同 tab 下命中错误缓存。

14 日详情接口返回结构尽量对齐当前 `/ranking-stats/details`：

- `timestamp`
- `range`
- `lane`
- `kungfu`
- `score_type`
- `version`
- `members`

其中 `members` 直接取最高分榜项的字段子集，并透传已有的身份字段和可能存在的 `cached_detail_summary`，从而兼容前端现有列表按钮和图标渲染。

## Data and Storage Impact

本次不新增集合、不改索引、不迁移数据。

读取来源：

- 14 日最高分详情：Mongo `jjc_peak_score_rankings`
- 当前排名快照详情：Mongo `jjc_ranking_stat_details`

## API and UI Impact

新增 API：

- `GET /api/jjc/ranking-stats/peak-score/details?timestamp=<ts>&score_type=game&range=<range>&kungfu=<name>&version=<n>`

兼容策略：

- 页面 `peak-game` 分布详情切换到新接口。
- 页面 `all` / `purple` 分布详情仍读取 `/ranking-stats/details`。
- 如果 14 日详情接口未命中，返回 `not_found`，前端沿用现有错误展示。

## Risks and Rollback

主要风险：

- 新接口返回字段若与旧详情渲染不兼容，可能导致详情项缺按钮或缺图标。
- 前端缓存如果没有正确区分 source，可能仍会串数据。

回滚方式：

- 回退 `public/jjc-ranking-stats.html` 的详情分流逻辑。
- 删除或停用新增 `peak-score/details` 路由。

观察点：

- 同一快照时间下，14 日分布卡人数是否等于展开后的成员数。
- 切回 `all` / `purple` 后详情是否仍与当前快照一致。

## Confirmation

2026-07-03：用户确认按“新增 14 日详情接口 + 前端按 tab 分流”实现。
