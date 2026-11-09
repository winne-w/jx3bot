# 只读代码 Review

日期：2026-09-04

由独立子 agent 对照 proposal/design/spec/tasks 与当前 diff 审查。专项 153 项测试通过。

结论：未发现凭据硬编码、Python 3.9 注解、Mongo CAS/tombstone、统计恒等式、URL 时区或错误包装方面的 Blocker/High 问题。

已处理：修正 `invalid_reason` 字段与 partial 索引文档、移除未实现的 `projected_at` 承诺、将服务测试命名更新为 14 天，并为非 singleton 的事实投影降级路径增加结构化告警。生产 singleton 始终注入 fact projector；该降级仅用于兼容测试/手工构造入口。

保留观察：时间字段冲突目前按优先级确定值，不单独持久化冲突来源；不影响当前查询合同，后续如需审计可扩展事实 schema。
