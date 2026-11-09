## Why

JJC 数据中心原有对局列表只读取本地数据库，点击刷新不能检查刚结束的战绩，而完整历史同步需要完成更多数据补齐。为正在查看的已知角色增加独立的最新摘要任务，让基础战绩先显示，同时保留历史分页和统计口径。

## What Changes

- 列表与刷新状态 GET 始终只读取本地数据；新增 POST 为本地已知角色提交最新战绩刷新，由独立 worker 执行。
- 按角色身份、赛季及比赛类型合并任务，保留固定任务槽、角色冷却、任务有效期和失败退避，旧执行者不能覆盖新一代任务。
- 每次任务最多调用两页历史列表，缺少有效 SK01 时最多调用一次 indicator 并核对身份。本赛季 3v3 基础战绩与已有摘要合并去重，最多保存和展示 40 条；第一页先发布，不等待详情。
- 最新摘要独立展示，失败保留已发布摘要和上一成功检查时间，不推进完整历史同步水位，不生成完整统计事实。
- POST 按可信来源限频；功能默认关闭，无可用 worker 或配置不完整时返回明确状态，新功能初始化失败不得阻断 bot 启动。
- 前端保留“近期战绩”和“已同步历史”两区，刷新后最多轮询本地列表 10 次，切换角色后丢弃旧响应。
- 2026-10-09 用户取消共享推栏预算桶，官方调用沿用直连实现。本 change 不再包含全出口预算、并发许可、小时/日配额、共享暂停或新增的公开详情回源限制。通用 HTTP client 保留内部重试，两页限制属于业务逻辑调用上限，不承诺底层网络最多四次。

## Capabilities

### New Capabilities

- `jjc-safe-live-refresh`: 数据库优先的最新战绩摘要、受控任务提交、来源限频、旧数据保留与前端有界轮询。

### Modified Capabilities

无。`jjc-sync-dispatcher` 仍只为完整历史同步补队列，最新摘要任务不改变其规格。

## Impact

涉及 `src/services/jx3/jjc_live_refresh.py`、`jjc_public_refresh.py`、`jjc_live_refresh_runtime.py`、`src/storage/mongo_repos/jjc_live_refresh_repo.py`、实例装配、bot 生命周期、`config.py`、JJC HTTP 路由及 `public/jjc-synced-matches.html`。新增 `POST /api/jjc/ranking-stats/synced-role-refresh`，在既有本地列表响应中增加 `latest_matches` 和 `refresh`，保留统一响应封装与原历史分页字段。

复用 MongoDB，新增刷新状态、固定槽位、不可变摘要快照、来源窗口与 worker 心跳集合，不新增 Redis 依赖。同步数据库设计、项目上下文、API 说明和部署/回归文档。预算设计、验证及回退过程保留在 `budget-brief.md`、`budget-report.md`、`budget-rollback.md`，作为历史档案。

2026-10-20 用户授权按整理结果拆分提交，并完成刷新功能收尾。当前 change 保持 active，验证、review 和验收以本轮实际证据为准；提交不等于生产启用或归档。
