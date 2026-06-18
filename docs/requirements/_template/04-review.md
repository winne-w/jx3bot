# <需求标题> Review 记录

## Review Checklist

- [ ] 分层边界符合 `PROJECT_CONTEXT.md` 和相关架构文档
- [ ] 外部依赖通过 `infra` / `storage` / `renderers` 等边界接入
- [ ] 配置项、密钥和内网地址没有硬编码
- [ ] Mongo、缓存 key、TTL、迁移和兼容策略清楚
- [ ] HTTP 调用具备超时、失败处理和降级策略
- [ ] 日志、监控、trace 和告警覆盖关键路径
- [ ] 自动化测试和冒烟计划覆盖核心风险
- [ ] 方案、执行计划、测试记录和代码行为一致

## Findings

记录 review 发现、严重级别、文件位置和处理结论。

## Follow-ups

记录不阻塞本次上线但需要后续处理的事项。

## Approval

记录确认人、确认时间和确认结论。
