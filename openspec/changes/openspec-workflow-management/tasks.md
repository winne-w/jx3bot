# OpenSpec Workflow Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 OpenSpec 初始化为仓库唯一的中大型需求流程，并完整迁移五项现有需求档案。

**Architecture:** `openspec/specs/` 保存当前能力的基线规格，`openspec/changes/` 保存 active change，`openspec/changes/archive/` 保存完成 change。每项 change 保留原生 proposal、design、tasks、spec delta，以及本项目的测试、review、验收档案。

**Tech Stack:** OpenSpec CLI、Markdown、Git。

---

## 文件结构

| 路径 | 责任 |
| --- | --- |
| `openspec/` | CLI 初始化文件、规格基线和所有需求变更 |
| `openspec/changes/openspec-workflow-management/` | 本流程变更的交付记录 |
| `PROJECT_CONTEXT.md`、`docs/PLANS.md` | 唯一流程规则和阶段门禁 |
| `README.md`、`docs/exec-plans/index.md`、`docs/design-docs/development-guide.md`、`project-history.md` | 入口、兼容说明、开发指引和历史记录 |

### Task 1: 初始化 OpenSpec 并建立本 change

**Files:**
- Create: `openspec/config.yaml`（由 CLI 当前版本生成，如适用）
- Create: `openspec/specs/`
- Create: `openspec/changes/archive/`
- Create: `openspec/changes/openspec-workflow-management/proposal.md`
- Move: `docs/superpowers/specs/2026-08-24-openspec-workflow-design.md` to `openspec/changes/openspec-workflow-management/design.md`
- Modify: `openspec/changes/openspec-workflow-management/tasks.md`

- [x] **Step 1: 验证 CLI 包入口**

```bash
node --version
npm --version
npx --yes @fission-ai/openspec@latest --help
```

Expected: 三条命令均退出码为 0，最后一条输出 OpenSpec 帮助。

- [x] **Step 2: 初始化目录并写入 proposal**

```bash
npx --yes @fission-ai/openspec@latest init
mkdir -p openspec/changes/archive
find openspec -maxdepth 2 -type d | sort
```

Create `openspec/changes/openspec-workflow-management/proposal.md`:

```md
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
```

- [x] **Step 3: 归位设计并提交 bootstrap**

```bash
git mv docs/superpowers/specs/2026-08-24-openspec-workflow-design.md openspec/changes/openspec-workflow-management/design.md
git add openspec docs/superpowers/specs/2026-08-24-openspec-workflow-design.md
git commit -m "docs: initialize OpenSpec workflow"
```

Expected: 本次设计成为 change 的 `design.md`，不再存在独立 Superpowers 设计产物。

**验证记录（2026-08-24）：** `timeout 30s npx --yes @fission-ai/openspec@latest list` 在 30 秒内未返回，退出码为 `124`；CLI 的 `--help` 与 `init` 已分别成功验证。本次 bootstrap 未将 list 成功作为前提，后续迁移任务应在可用环境中复核 list。`openspec/specs/.gitkeep` 与 `openspec/changes/archive/.gitkeep` 确保 CLI 初始化的两个空目录在 clone 后可复现。

**规格补充（2026-08-24）：** 增加 `specs/workflow-management/spec.md`，使本 change 具备严格校验所需的流程管理 delta；该规格与 proposal/design 的唯一入口和非平行产物决策一致。

### Task 2: 迁移需求档案和创建基线规格

**Files:**
- Move: `docs/requirements/2026-06-17-jjc-peak-score-ranking/` to `openspec/changes/archive/2026-06-17-jjc-peak-score-ranking/`
- Move: `docs/requirements/2026-06-17-jjc-sync-auto-dispatcher/` to `openspec/changes/archive/2026-06-17-jjc-sync-auto-dispatcher/`
- Move: `docs/requirements/2026-07-03-jjc-peak-detail-consistency/` to `openspec/changes/archive/2026-07-03-jjc-peak-detail-consistency/`
- Move: `docs/requirements/2026-07-27-jx3api-openapi-migration/` to `openspec/changes/archive/2026-07-27-jx3api-openapi-migration/`
- Move: `docs/requirements/2026-08-24-jjc-match-season/` to `openspec/changes/jjc-match-season/`
- Create: `openspec/specs/jjc-ranking/spec.md`, `openspec/specs/jjc-sync-dispatcher/spec.md`, `openspec/specs/jx3api-openapi/spec.md`

- [x] **Step 1: 记录清单并执行 Git 重命名**

```bash
find docs/requirements -type f | sort > /tmp/jx3bot-requirements-before.txt
git mv docs/requirements/2026-06-17-jjc-peak-score-ranking openspec/changes/archive/2026-06-17-jjc-peak-score-ranking
git mv docs/requirements/2026-06-17-jjc-sync-auto-dispatcher openspec/changes/archive/2026-06-17-jjc-sync-auto-dispatcher
git mv docs/requirements/2026-07-03-jjc-peak-detail-consistency openspec/changes/archive/2026-07-03-jjc-peak-detail-consistency
git mv docs/requirements/2026-07-27-jx3api-openapi-migration openspec/changes/archive/2026-07-27-jx3api-openapi-migration
git mv docs/requirements/2026-08-24-jjc-match-season openspec/changes/jjc-match-season
```

Expected: 四项 completed change 归档，`jjc-match-season` 保持 active。

- [x] **Step 2: 重命名每个已存在阶段文件**

For each migrated directory, use `git mv` with this exact mapping; do not补造历史缺失的阶段文件：

```text
00-requirement.md -> proposal.md
01-solution.md -> design.md
02-execution-plan.md -> tasks.md
03-test-plan.md -> test-plan.md
04-review.md -> review.md
05-acceptance.md -> acceptance.md
```

- [x] **Step 3: 编写规格基线和 active delta**

Each baseline spec and `openspec/changes/jjc-match-season/specs/jjc-ranking/spec.md` use:

```md
## Requirements

### Requirement: <可验证行为>

系统 MUST <行为>。

#### Scenario: <场景名称>
- **WHEN** <触发条件>
- **THEN** <可观察结果>
```

Only record implemented, currently effective behavior from the archived records; do not infer missing historic deltas.

- [x] **Step 4: 删除旧入口并提交**

```bash
git rm -r docs/requirements/_template docs/requirements/index.md
rmdir docs/requirements
git add openspec
git commit -m "docs: migrate requirements to OpenSpec"
```

Expected: 每个迁移前阶段文件都有一个映射后的 OpenSpec 文件，且 `docs/requirements/` 不存在。

### Task 3: 更新流程规则和入口文档

**Files:**
- Modify: `PROJECT_CONTEXT.md`, `docs/PLANS.md`, `README.md`, `docs/exec-plans/index.md`, `docs/design-docs/development-guide.md`, `project-history.md`

- [x] **Step 1: 写入唯一入口和阶段门禁**

Replace future-facing `docs/requirements/` rules with this text in `PROJECT_CONTEXT.md` and `docs/PLANS.md`:

```md
中大型需求必须在 `openspec/changes/<change-id>/` 建立 change，并以 `proposal.md`、`design.md`、`tasks.md`、`specs/` delta、`test-plan.md`、`review.md`、`acceptance.md` 记录交付过程。用户或项目 owner 确认 `design.md` 后才能形成 `tasks.md`；确认计划前不得修改业务代码或运行配置。完成验收后，先将已生效行为合并进 `openspec/specs/`，再归档 change。
```

Also add `openspec/AGENTS.md`（若 CLI 生成）、相关 specs 和 active change 到任务开始前的必读顺序；保留 `docs/exec-plans/` 的小修复和历史续做规则。

- [x] **Step 2: 写明 Superpowers 边界和历史变更**

Replace future-facing old-path references in the four remaining files. Add this to `docs/PLANS.md` and append an OpenSpec 迁移记录到 `project-history.md`:

```md
Superpowers 用于 agent 的设计、计划、测试、验证和 review 方法；其项目产物必须写入当前 OpenSpec change，不得创建 `docs/superpowers/specs/` 或 `docs/superpowers/plans/` 的平行交付档案。
```

- [x] **Step 3: 提交文档规则切换**

```bash
git add PROJECT_CONTEXT.md docs/PLANS.md README.md docs/exec-plans/index.md docs/design-docs/development-guide.md project-history.md
git commit -m "docs: make OpenSpec the requirement workflow"
```

Expected: 新需求只从 OpenSpec 开始，既有 `docs/exec-plans/` 兼容入口不受影响。

### Task 4: 验证、记录并验收流程迁移

**Files:**
- Create: `openspec/changes/openspec-workflow-management/test-plan.md`, `review.md`, `acceptance.md`
- Modify: `openspec/changes/openspec-workflow-management/tasks.md`

- [x] **Step 1: 执行流程和引用扫描**

```bash
npx --yes @fission-ai/openspec@latest list
npx --yes @fission-ai/openspec@latest validate openspec/changes/jjc-match-season --strict
rg -n "docs/requirements|docs/superpowers/(specs|plans)" PROJECT_CONTEXT.md docs/PLANS.md README.md docs/exec-plans/index.md docs/design-docs/development-guide.md project-history.md
git diff --check
```

Expected: list 列出 active changes；strict validation 通过；`rg` 和 `git diff --check` 无输出。

- [x] **Step 2: 核对迁移数量并记录真实结果**

```bash
wc -l /tmp/jx3bot-requirements-before.txt
find openspec/changes -type f \( -name proposal.md -o -name design.md -o -name tasks.md -o -name test-plan.md -o -name review.md -o -name acceptance.md \) | wc -l
```

Write command output, known limitations and the tested rollback command below into test/review/acceptance records:

```bash
git revert <migration-commit-sha>
```

- [x] **Step 3: 提交验证记录**

```bash
git add openspec/changes/openspec-workflow-management
git commit -m "docs: verify OpenSpec workflow migration"
git status --short
```

Expected: 只记录实际运行结果；流程 change 保持 active，直到团队使用 OpenSpec 创建下一项需求后再归档。

## 验收标准

- OpenSpec CLI 可帮助、初始化、列出并严格校验 active change。
- 五项 `docs/requirements/` 档案均迁入 OpenSpec，四项归档、一项 active。
- 新需求规则不再引用 `docs/requirements/`，Superpowers 不会建立平行交付目录。
