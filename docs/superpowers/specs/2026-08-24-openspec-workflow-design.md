# OpenSpec 流程管理接入设计

## 目标

以 OpenSpec 取代 `docs/requirements/`，使其成为本仓库所有中大型需求变更的唯一流程入口；完整保留现有需求、方案、执行、测试、review 和验收的可追溯记录。Superpowers 继续提供 agent 执行方法，不再拥有独立的项目交付文档目录。

## 非目标

- 不改变 Python 代码、运行方式或生产部署。
- 不将小范围修复和历史续做强制转换为 OpenSpec；它们仍可使用 `docs/exec-plans/active/`。
- 不在本次设计阶段安装 CLI、初始化目录或移动历史文档。

## 目标结构

```text
openspec/
  specs/
    <capability>/
      spec.md
  changes/
    <change-id>/
      proposal.md
      design.md
      tasks.md
      specs/<capability>/spec.md
      test-plan.md
      review.md
      acceptance.md
    archive/
      <yyyy-mm-dd>-<change-id>/
```

`openspec/specs/` 是已生效能力的基线规格；每个未完成变更在 `openspec/changes/<change-id>/` 中维护 proposal、设计、任务和针对基线的规格 delta。完成且验收后，变更移入 `openspec/changes/archive/`。`test-plan.md`、`review.md` 和 `acceptance.md` 是本项目保留的扩展档案，用于维持既有质量门禁和人工回归记录。

## 流程与门禁

1. 需求澄清后创建 change，并完成 `proposal.md` 与 `design.md`。
2. 用户或项目 owner 确认设计后，完成 `tasks.md`、规格 delta 和 `test-plan.md`。
3. 在任务计划获确认前，不修改业务代码或运行配置。
4. 实现期间更新 `tasks.md` 的进度、决策和发现；测试、review、验收分别记录在专属文件。
5. 完成验证和验收后，把 delta 合并进 `openspec/specs/`，再归档 change。

每个 change 的 `tasks.md` 继续遵守 `docs/PLANS.md` 所要求的自包含结构和执行粒度，保证项目既有 DDD 边界、验证命令、风险和回滚要求不被 OpenSpec 的默认格式稀释。

## 现有文档迁移

`docs/requirements/` 中的五项历史需求全部迁移：

| 原目录状态 | 目标位置 | 文档映射 |
| --- | --- | --- |
| 四项 Completed | `openspec/changes/archive/<原目录名>/` | `00-requirement.md -> proposal.md`；`01-solution.md -> design.md`；`02-execution-plan.md -> tasks.md`；其余阶段文件改为语义化名称 |
| `2026-08-24-jjc-match-season` Active | `openspec/changes/jjc-match-season/` | 采用同一映射，移除日期前缀以符合 change-id 约定 |
| `_template/` 与 `index.md` | 删除 | 由 OpenSpec 的初始化模板、`openspec list` 和目录状态取代 |

迁移是 `git mv` 的重命名操作，保留文件内容与 Git 历史。原文中指向 `docs/requirements/` 的链接必须更新为新路径。对每个已归档变更，若其行为仍是项目当前能力，则在迁移时补建或合并对应 capability 的基线规格；无法从历史材料确定的行为不臆造规格，只在归档中保留事实记录。

## OpenSpec 与 Superpowers

OpenSpec 是仓库内可提交、可审计的变更规格和状态载体。Superpowers 是 agent 的执行纪律：需求探索、方案比较、计划细化、TDD、验证和 review。

为防止重复记录，所有 Superpowers 产生的设计和实施计划必须写入当前 OpenSpec change 的 `design.md`、`tasks.md` 或项目扩展阶段文件；不得在 `docs/superpowers/` 新建交付产物。本设计文件是过渡期唯一例外，接入完成后应迁入 `openspec/changes/openspec-workflow-management/design.md` 或在验收中引用。

## 配置与校验

接入实现将安装并初始化 OpenSpec CLI，保留其生成的仓库级指令文件，并在项目入口文档中规定 agent 先读取它。验证至少包括：CLI help/init/list/validate 的轻量检查、迁移前后文件计数核对、全仓库旧路径引用扫描，以及对 active change 的状态检查。

## 风险与回滚

主要风险是迁移中链接失效、将历史状态误判为当前规格、以及 agent 同时写入两个流程目录。通过 `git mv`、逐项清单核验、保留原始内容、明确唯一入口和全仓库引用扫描控制风险。

若接入后发现 OpenSpec 不满足团队使用方式，可在一个提交内回滚目录移动和流程文档更新，恢复 `docs/requirements/`；不会影响业务代码或运行数据。
