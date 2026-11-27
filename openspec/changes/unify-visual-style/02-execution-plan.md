# 全站模板图片与 HTTP 页面视觉统一执行计划

本执行计划依据 `docs/PLANS.md` 维护，记录从需求确认到完成验证与独立审查的完整过程。

## Purpose / Big Picture

将 JX3Bot 全部 22 个活跃 QQ 模板图片（含超长订阅列表截图）与全部 5 个 JJC HTTP 页面收敛到同一套 **清爽现代浅色设计系统（`#F3F6FB` 云白底 + `#FFFFFF` 纯白圆角卡片 + `#4F6EF7` 澄澈靛蓝主色 + 统一鎏金/紫武/胜败语义色 + 等宽数字排版）**。所有 QQ 图片统一采用 `width=760, height="ck"`（等效 `380px @2x` 移动端单列紧凑竖卡，物理输出 `1520px` 宽）；5 个 HTTP 页面统一接入升级后的 `public/jjc-site.css` 浅色壳层，同时保持 `jjc-sync-queue.html` 入口不在公开页面导航栏暴露。

## Progress

- [x] 完成全量模板与静态页盘点、4 套候选风格交互式打样对比及需求澄清。
- [x] 输出 `00-requirement.md`、`01-solution.md`、`proposal.md`、`design.md`，并获用户确认（含隐藏 `jjc-sync-queue.html` 导航入口约束）。
- [x] 只读核查 `origin/main`（`8a21a2b`）最新源码与单测契约，输出详细执行计划 `02-execution-plan.md` 与 `tasks.md`，并获用户审核确认。
- [x] T1：基于 `origin/main` 建立独立 git worktree `/mnt/d/document/codes/jx3bot-workspace/_worktrees/unify-visual-style`（分支 `feat/unify-visual-style`），测试子 agent 先行编写视觉统一与隐藏导航契约测试并验证 RED（62 项子断言预期失败）。
- [x] T2：实现 `templates/_partials/` 共享浅色竖卡组件，修正 `src/infra/screenshot.py` 窄视口高度测量顺序与 `jx3web` 页脚样式。
- [x] T3：分三组无重叠改造全部 22 个 QQ 模板图片与对应渲染宽度参数（`width=760, height="ck"`），并全量开启 `{% autoescape true %}`。
- [x] T4：升级 `public/jjc-site.css` 并统一全部 5 个 JJC HTTP 页面（保持 `index.html` 与 `jjc-ranking-stats.html` 字节完全一致，保持 `jjc-sync-queue.html` 入口隐藏）。
- [x] T5：完成 Python 3.9/3.13 双版本回归、Playwright 离线全量渲染与零横向溢出校验、独立只读子 agent 代码审查及 P1/P2 问题闭环修复，同步 `PROJECT_CONTEXT.md` 与 OpenSpec 验收文档。

## Surprises & Discoveries

1. **基线隔离必要性**：`/home/songjingjing/codes/jx3bot` 检出在旧 dirty 分支，而最新移动端装备查询位于 `origin/main`（`8a21a2b`）。在独立 worktree 基于 `origin/main` 开发确保了最新基线且对原工作区零触碰。
2. **`760px`（`380px × 2`）移动端双倍网格统一**：`origin/main` 的 `装备查询.html` 与单测断言 `width=760`、`repeat(4`、`32px`/`34px` 字阶。全站 22 个 QQ 模板对齐 `width=760` 后，所有生成图片共享一致的 `1520px` 物理宽度与手机缩略可读性，且与既有单测零冲突。
3. **审查捕获的 Jinja 自动转义与上游空值边界**：独立只读审查发现存量 `singletons.py` 的 Jinja `Environment` 默认未开 `autoescape`，仅 `装备查询.html` 含 `{% autoescape true %}`；以及上游返回部分 `None` 价格、缺失对局起止时间或整型百战加成时可能触发 `TypeError`。已在全部 22 个活跃模板及 `_partials/` 补齐 `{% autoescape true %}` 与数值类型守卫，并补充回归单测验证。

## Decision Log

- **2026-11-25**：用户选定「风格一：全站清爽现代浅色风」，并明确要求保持 `jjc-sync-queue.html` 公开导航入口隐藏。
- **2026-11-26**：用户审核通过执行计划；在 `/mnt/d/document/codes/jx3bot-workspace/_worktrees/unify-visual-style` 完成全部实现、测试、离线渲染审计与独立审查修复。

## Outcomes & Retrospective

- **变更文件规模**：共涉及表现层/静态页/单测/文档，未触碰任何 `src/api/`、`src/storage/`、MongoDB 集合或外部请求协议。
- **验证结果**：
  - Python 3.9.25 与 Python 3.13.2 双版本 `py_compile` 及定向单测套件全部通过（`git diff --check` 零告警）。
  - Playwright Headless Chromium 离线全量渲染全部 22 个 QQ 竖卡模板（`760px @2x` -> `1520px`）与 5 个 HTTP 页面（桌面 `1440×900` + 移动 `390×844` 共 10 个视图），`overflow_count = 0`、`pageerror = []`。
  - 独立代码审查发现的 1 项 P1（模板 `autoescape`）与 3 项 P2（空值/异构类型守卫）已全部修复并通过回归测试验证。

## Context and Orientation

详见 `01-solution.md` 与 `04-review.md`。

## Plan of Work

按 T1 -> T2 -> T3（T3a/T3b/T3c 并行）-> T4 -> T5 顺序全部完成。

## Concrete Steps

见 `03-test-plan.md` 中实际执行的验证命令与输出摘要。

## Validation and Acceptance

全部验收项达成，详见 `05-acceptance.md`。
