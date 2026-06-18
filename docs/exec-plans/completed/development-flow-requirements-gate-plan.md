# 开发流程迁移到需求目录体系计划

## 背景

当前仓库的开发流程主要记录在 `PROJECT_CONTEXT.md`，默认采用“二阶段开发流程”，以 `docs/exec-plans/active/*.md` 单文件计划作为变更门禁。

上游 `prompt2data-service` 已经升级到更完整的需求级交付流程：`需求澄清 -> 方案文档 -> 执行计划 -> 开发实现 -> 测试验证 -> review -> 验收归档`，并以 `docs/PLANS.md` 和 `docs/requirements/` 目录承载方案、测试、review、验收等文档。

## 目标

- 将本仓库默认开发流程升级为“需求目录 + 分阶段交付文档”。
- 保留 `docs/exec-plans/` 作为历史计划、小范围修复和技术债的兼容入口。
- 让 `PROJECT_CONTEXT.md`、入口文档和索引文档对新的流程口径一致。

## 变更范围

- 新增 `docs/PLANS.md`
- 新增 `docs/requirements/index.md` 和 `_template/` 模板目录
- 更新 `PROJECT_CONTEXT.md`
- 视需要微调 `AGENTS.md`、`CLAUDE.md`、`docs/exec-plans/index.md`

## 验证

- 文档路径全部存在且索引可导航
- `PROJECT_CONTEXT.md` 与 `docs/PLANS.md` 口径一致
- `docs/exec-plans/index.md` 明确新旧流程边界

## 回滚

- 删除新增的 `docs/PLANS.md`、`docs/requirements/`
- 回退 `PROJECT_CONTEXT.md` 和入口文档中的流程描述
