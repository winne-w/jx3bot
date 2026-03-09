# Task: Refactor Plan

状态：进行中
更新时间：2026-03-09

## 目标

- 继续收敛仓库分层边界
- 清理高频遗留 `print()`
- 减少 `src.utils.defget` 兼容导入面

## 当前关联执行文档

- `docs/exec-plans/active/refactor-plan.md`

## 当前重点

- `status_monitor` 链路
- `config_manager` 链路
- `jjc_ranking` 链路

## 完成标准

- 上述链路中的主要调试式输出被结构化日志替换
- 新增代码不再扩大 `defget` 依赖面
- 相关回归路径同步更新到 `docs/references/runbook.md`
