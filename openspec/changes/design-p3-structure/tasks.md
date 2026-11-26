# P3 结构拆分与基础设施统一执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

统一后台监督与 HTTP 连接池基础设施，剥离路由层业务逻辑，合并重复持久化阶段与插件推送开关，收敛运行时配置注册表并清理 `print()`。

## Progress
- [x] 完成 P3 方案设计（2026-11-26）
- [x] 子任务 P3-A：`ManagedBackgroundTask`、`TuilanAuthError`、`HttpClient` 连接池与 `bot.py` 关闭钩子
- [x] 子任务 P3-B：`jjc_ranking_stats_query.py` 路由业务下沉、`match_detail_persistence` 循环化与 `scripts/rebuild_jjc_projections.py`
- [x] 子任务 P3-C：`src/infra/runtime_config.py`、`config_manager` 优雅重启、`status_monitor` 开关去重与 `wanbaolou/alias.py` 日志化
- [x] 双版本测试验证、审查与本地提交

## Surprises & Discoveries
待实现后补充。

## Decision Log
- 2026-11-26：避开在途 `feat/unify-visual-style` 修改的所有模板、前端、截图与 `wanbaolou/__init__.py` 文件，留至 P5 处理。

## Outcomes & Retrospective
待完成后回填。

## Context and Orientation
分支 `refactor/design-p3-structure` 基于 `refactor/design-p2-data` (`29d9dd0`)。

## Plan of Work
拆分为 P3-A、P3-B、P3-C 三个文件集合严格互斥的并行子任务。

## Concrete Steps
见 `design.md`。

## Validation and Acceptance
Python 3.9 与 Python 3.13 双版本编译及测试通过。
