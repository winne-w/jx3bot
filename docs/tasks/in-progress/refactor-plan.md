# Task: Refactor Plan

状态：进行中
更新时间：2026-05-23

## 目标

- 继续收敛仓库分层边界
- 清理高频遗留 `print()`
- 减少 `src.utils.defget` 兼容导入面

## 当前关联执行文档

- `docs/exec-plans/active/refactor-plan.md`

## 当前重点

- 2026-05-22 执行批次：`config_manager`、`jjc_ranking`、`infra/image_fetch`、`services/jx3/kungfu` 日志收口已完成
- `status_monitor` 链路已无当前批次命中的 `print()`，后续继续关注缓存与通知边界
- `defget` 兼容导入面后续按独立切片收敛

## 完成标准

- 上述链路中的主要调试式输出被结构化日志替换
- 新增代码不再扩大 `defget` 依赖面
- 相关回归路径同步更新到 `docs/references/runbook.md`
