# PLANS

本仓库把需求方案和执行计划当作一等产物。跨模块、跨阶段、需要多次验证或者存在显著风险的改动，都应先完成需求澄清和方案文档，再写执行计划，最后进入编码。

默认交付流程是“需求澄清 -> 方案文档 -> 执行计划 -> 开发实现 -> 测试验证 -> review -> 验收归档”。对于需要编写或补充测试的任务，执行计划里应明确哪些测试由子 agent 先行承担，哪些实现任务可以并行拆分，最终由主执行者整合、跑测和复核。

## 何时必须建立需求目录

- 改动涉及多个路由、service、storage、renderer 或前后端联动
- 改动会影响缓存语义、配置生命周期、数据正确性或兼容性
- 改动需要分阶段上线、双写、数据迁移或回滚方案
- 改动需要补多类测试，且无法在一次提交里直接证明正确性
- 需要先产出可确认的方案，再进入实现阶段的需求变更

纯问答、只读排查、运行验证命令、数据查询、git 操作，以及不改变仓库文件的临时诊断命令，可不建立需求目录。

## 需求文件放置规则

新需求默认放在 `docs/requirements/<yyyy-mm-dd>-<short-name>/`，从 `docs/requirements/_template/` 复制模板。目录名使用日期和短横线命名，短名应能表达业务目标。

推荐文件结构：

- `00-requirement.md`
  记录需求澄清结果，包括背景、目标、非目标、业务口径、上下游依赖、待确认项。
- `01-solution.md`
  方案文档。先讲业务问题和总体方案，再讲数据流、接口、存储、缓存、外部依赖、异常、监控和回滚。
- `02-execution-plan.md`
  执行计划。详细说明改哪些模块、文件、函数、模板、接口或存储，以及如何分阶段开发、测试和 review。
- `03-test-plan.md`
  测试和冒烟计划。覆盖自动化测试、手工验证、数据回归、线上观察点和异常场景。
- `04-review.md`
  review 记录。记录分层、代码、配置、外部依赖、监控、安全和文档一致性的核对结果。
- `05-acceptance.md`
  验收记录。记录最终实现内容、验证命令、冒烟结果、未覆盖风险、上线观察点和回滚方式。

`docs/requirements/index.md` 维护需求目录索引。新增需求目录时同步更新索引。

## 阶段门禁

1. 需求澄清后，先写 `00-requirement.md` 和 `01-solution.md`。
2. 方案经用户或项目 owner 确认后，再写 `02-execution-plan.md`。
3. 执行计划确认前，不开始业务代码实现。
4. 实现过程中按计划持续更新 `02-execution-plan.md` 的进度、决策和发现。
5. 测试、review、验收结果分别写入 `03-test-plan.md`、`04-review.md`、`05-acceptance.md`。
6. 需求完成后保留需求目录；如后续增加归档状态，需在 `docs/requirements/index.md` 标注状态。

## 旧执行计划兼容规则

历史计划仍保留在 `docs/exec-plans/`：

- 正在执行的历史计划放在 `docs/exec-plans/active/`
- 完成后的历史计划移到 `docs/exec-plans/completed/`
- 长期未排期但值得记录的问题继续放在现有 tech debt 或 active 文档体系中

新需求优先使用 `docs/requirements/` 目录结构。只有小范围修复、历史计划续做或项目 owner 明确要求时，才继续使用 `docs/exec-plans/active/` 单文件计划。

## 执行计划必须包含的结构

每个 `02-execution-plan.md` 都必须是自包含文档，默认读者只知道当前仓库和这一个需求目录。至少包含以下章节：

- `Purpose / Big Picture`
- `Progress`
- `Surprises & Discoveries`
- `Decision Log`
- `Outcomes & Retrospective`
- `Context and Orientation`
- `Plan of Work`
- `Concrete Steps`
- `Validation and Acceptance`

其中只有 `Progress` 可以使用复选框列表；其他章节优先使用简洁 prose，避免大段 checklist。

## 写法要求

- 默认使用中文撰写执行计划；只有在明确约定需要英文时才使用英文。
- 直接写明会改哪些文件、哪个模块、哪个函数、为什么改。
- 说明验证命令、期望现象和验收标准。
- 执行过程中持续更新 `Progress`、`Decision Log`、`Surprises & Discoveries`。
- 计划变更后要同步更新需求目录内相关文档，不能让方案、计划、测试记录失真。
- 用户或项目 owner 明确确认计划后，才开始编码或修改仓库文件。

## 当前仓库的计划粒度建议

- 小改动
  单个路由参数调整、单个 service 修复、单个模板交互修正，可不建立需求目录；如需记录，可使用简版单文件计划。
- 中等改动
  涉及 JJC 查询主链路、缓存策略、角色身份投影、前后端联动页面或多文件文档同步，建议建立需求目录；方案和执行计划可以保持简版。
- 大改动
  涉及同步 worker、数据库结构、外部接口协议变更、运行时配置体系或跨模块重构，必须建立完整需求目录，并维护方案、执行计划、测试、review 和验收记录。

## 执行计划最小模板

```md
# <短标题>

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

## Progress
- [ ] ...

## Surprises & Discoveries

## Decision Log

## Outcomes & Retrospective

## Context and Orientation

## Plan of Work

## Concrete Steps

## Validation and Acceptance
```
