# 验收记录

## 已验收

- OpenSpec 已成为中大型新需求的唯一流程入口。
- `docs/requirements/` 模板、索引和五项需求档案已移除或迁移到 `openspec/`。
- Superpowers 被定位为执行方法，项目交付产物必须写入当前 OpenSpec change。
- `docs/exec-plans/` 保留为小修复、技术债与历史续做兼容入口。

## 风险与回滚

如需回滚，可依次 revert `9acde0a`、`c941d75`、`1d5c840`、`51e0795`。本次没有业务代码、数据库或运行配置改动。

## 遗留验证

严格 OpenSpec CLI 验证需在 CLI 可响应的环境复跑；当前超时记录见 `test-plan.md`。
