# JJC 14 日最高分详情口径一致性需求澄清

## Background

`public/jjc-ranking-stats.html` 的“14日游戏最高分排名”分布卡显示某心法人数时，数据来自 `/api/jjc/ranking-stats/peak-score` 返回的 14 日最高分聚合结果；但用户展开某个心法明细时，前端仍然请求 `/api/jjc/ranking-stats/details`，读取的是当前推栏排名快照成员列表。两者统计对象不同，导致“卡片人数”和“展开详情人数”不一致。

本次用户反馈的具体现象是：14 日竞技排名里丐帮显示 9 人，但点开详情只有 6 人。

## Goals

- 让 14 日最高分分布卡与展开详情使用同一数据源和同一成员集。
- 保持当前推栏排名 `all` / `purple` 两个视图的详情行为不变。
- 为 14 日最高分视图提供独立、可测试的只读详情接口。

## Non-Goals

- 不修改 14 日最高分聚合逻辑、窗口定义或排名规则。
- 不调整当前推栏排名快照的统计和详情存储结构。
- 不新增同步任务、数据库集合或迁移脚本。

## Scope

影响范围仅限 JJC 统计只读链路：

- HTTP API：`src/api/routers/jjc_ranking_stats.py`
- 静态页面：`public/jjc-ranking-stats.html`
- 路由测试与前端静态断言测试
- 需求文档索引与本需求目录

## Business Rules

- `peak-game` 视图下，心法分布卡人数与展开详情人数必须一致。
- 14 日详情的成员列表必须来自 `jjc_peak_score_rankings.items` 同一份聚合结果，按 `range` 和 `kungfu` 过滤得到。
- 14 日详情接口的响应结构尽量对齐现有 `/ranking-stats/details`，复用前端已有渲染结构。
- `all` / `purple` 视图下仍继续读取 `/ranking-stats/details`。
- 前端详情缓存必须区分数据源，避免普通榜单与 14 日榜单串缓存。

## Dependencies

- Mongo `jjc_peak_score_rankings` 读路径，已有 `JjcPeakScoreRankingRepo`
- 现有 `JjcRankingStatsRepo` 快照详情读路径
- 静态页面 `public/jjc-ranking-stats.html`
- FastAPI 路由统一响应封装 `src/api/response.py`

## Open Questions

- 无。用户已确认修复方向为“新增 14 日详情接口 + 前端按 tab 分流”。

## Confirmation

2026-07-03：用户确认采用“新增 `peak-score` 明细接口，前端在 `peak-game` tab 下改用该接口”的修复方案。
