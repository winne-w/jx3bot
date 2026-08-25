## Why

竞技排名页面固定读取跨赛季最新 100 条快照。当前数据库有 288 条记录，第一页最早仅到本赛季第 9 周，导致仍在 Mongo 中的早期赛季周数据无法在按赛季的页面中访问。

## What Changes

- 新增赛季列表读取能力，供页面赛季下拉框展示全部可用赛季。
- 将排名快照元数据列表限制为指定赛季，且返回该赛季的全部快照，不再被跨赛季的全局分页窗口截断。
- 页面初始加载最新排名快照所属赛季；切换赛季后仅请求和展示该赛季的历史快照。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `jjc-ranking`: 竞技排名历史快照的赛季选择与列表读取改为按赛季完整返回。

## Impact

- `src/api/routers/jjc_ranking_stats.py`
- `src/storage/mongo_repos/jjc_ranking_stats_repo.py`
- `public/jjc-ranking-stats.html`
- 竞技排名 API 路由与前端静态行为测试
