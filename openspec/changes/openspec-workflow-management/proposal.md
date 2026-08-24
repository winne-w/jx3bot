# 引入 OpenSpec 流程管理

## Why

现有 `docs/requirements/` 缺少统一规格基线和 OpenSpec CLI 校验入口。

## What Changes

- 以 `openspec/` 替代 `docs/requirements/`。
- 迁移五项需求，并保留测试、review、验收档案。
- Superpowers 的项目产物写入当前 OpenSpec change。

## Impact

- Affected documentation: `PROJECT_CONTEXT.md`, `docs/PLANS.md`, `README.md`, `docs/exec-plans/index.md`, `docs/design-docs/development-guide.md`, `project-history.md`.
- No runtime code, configuration, database, or deployment behavior changes.
