# 流程管理规格增量

## ADDED Requirements

### Requirement: OpenSpec 作为中大型需求的唯一入口

仓库 MUST 使用 `openspec/changes/<change-id>/` 管理新的中大型需求变更，并将 proposal、design、tasks、规格 delta、测试、review 与验收记录保存在该 change 中。

#### Scenario: 创建中大型需求

- **WHEN** 维护者开始跨模块、跨阶段或高风险的需求
- **THEN** 维护者在 `openspec/changes/` 创建 change，而不在 `docs/requirements/` 创建平行需求目录

### Requirement: Superpowers 产物不建立平行交付目录

仓库 MUST 将 Superpowers 驱动的设计、计划、测试和 review 项目产物写入当前 OpenSpec change。

#### Scenario: agent 产出设计或执行计划

- **WHEN** agent 使用 Superpowers 的设计、计划或验证方法
- **THEN** 产物位于当前 change，且不创建 `docs/superpowers/specs/` 或 `docs/superpowers/plans/` 作为交付档案
