# All Tasks

更新时间：2026-05-06

这里维护当前任务索引，而不是把所有细节塞进一个大计划文档。

## In Progress

- `in-progress/refactor-plan.md`
  - 主题：主线分层重构、日志口径收口、`defget` 兼容面缩减
  - 详细说明：`docs/exec-plans/active/refactor-plan.md`

- `in-progress/jjc-ranking-role-inspect.md`
  - 主题：竞技场统计页角色下钻、最近 33 战绩与对局详情按需缓存

- `in-progress/jjc-match-data-sync.md`
  - 主题：JJC 官方接口对局数据同步、QQ 管理入口、时间水位续拉与重启恢复
  - 详细说明：`docs/exec-plans/active/jjc-match-data-sync-plan.md`

## Completed

- `completed/doc-system-rebuild.md`
  - 主题：按 agent-first 方式重建文档体系

- `completed/jjc-ranking-stats-split.md`
  - 主题：JJC 统计页 summary/details 拆分、明细懒加载与历史数据迁移
  - 详细说明：`docs/exec-plans/completed/jjc-ranking-stats-split-plan.md`

## 维护规则

- 新的跨文件、多阶段开发，先写计划文档，再开始编码
- 新的跨文件、多阶段工作，优先在 `docs/tasks/in-progress/` 增加任务文档
- 任务完成后移动到 `docs/tasks/completed/`
- 长期不变的设计不要写进 task，放到 `project-architecture.md` 或 `docs/design-docs/`
- 阶段性方案不要写进 task 目录索引正文，放到 `docs/exec-plans/`
