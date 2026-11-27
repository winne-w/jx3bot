# 执行计划入口：统一全站模板图片与 HTTP 页面视觉风格

唯一详细执行计划事实源见 [02-execution-plan.md](02-execution-plan.md)。当前状态：已完成开发实现、双版本回归、Playwright 全量渲染审计与独立代码审查修复，待用户审阅验收。

## Purpose / Big Picture

将 JX3Bot 全部 22 个活跃 QQ 模板图片与全部 5 个 JJC HTTP 页面统一为 **清爽现代浅色风**（`#F3F6FB` 云白底 + `#FFFFFF` 纯白圆角卡 + `#4F6EF7` 澄澈靛蓝主色）；QQ 图片全面统一为 `width=760, height="ck"` 移动端单列竖卡并开启 `autoescape`，JJC 5 个页面统一接入 `public/jjc-site.css` 浅色壳层并保持 `jjc-sync-queue.html` 公开导航入口隐藏。

## Progress

- [x] 完成需求澄清、4 套风格交互打样与 `00-requirement.md` / `01-solution.md` 方案确认。
- [x] 只读核查 `origin/main`（`8a21a2b`）源码与测试契约，形成 `02-execution-plan.md` 与 `tasks.md` 并获用户确认。
- [x] T1：基于 `origin/main` 创建独立 worktree，测试子 agent 先行补齐视觉契约与隐藏入口单测并验证 RED。
- [x] T2：实现 `templates/_partials/` 共享浅色竖卡组件，修正 `src/infra/screenshot.py` 窄视口高度测量与 `jx3web` 页脚样式。
- [x] T3：分三组改造全部 22 个 QQ 模板与渲染宽度参数，并补齐 `{% autoescape true %}` 与空值边界守卫。
- [x] T4：升级 `public/jjc-site.css` 并统一全部 5 个 JJC 静态页（同步 `index.html`，隐藏 `jjc-sync-queue.html` 外部入口）。
- [x] T5：双版本 Python 回归、Playwright 全量离线渲染巡检、独立子 agent review 修复与验收文档同步。

## Outcomes & Retrospective

双 Python 版本（3.9 / 3.13）单测、22 张 QQ 竖卡与 10 个 Web 视口离线渲染巡检（0 溢出）、独立代码审查与修复均已完成，详见 [03-test-plan.md](03-test-plan.md)、[04-review.md](04-review.md) 与 [05-acceptance.md](05-acceptance.md)。
