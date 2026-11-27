# 验收清单：全站模板图片与 HTTP 页面视觉统一（unify-visual-style）

日期：2026-11-26
工作分支：`feat/unify-visual-style`（独立 worktree：`/mnt/d/document/codes/jx3bot-workspace/_worktrees/unify-visual-style`，基于 `origin/main` `8a21a2b`）

## 验收项核对

- [x] **清爽现代浅色设计系统统一**：全部 22 个活跃 QQ 模板与 5 个 JJC HTTP 页面均采用 `#F3F6FB` 云白画布、`#FFFFFF` 纯白圆角卡片、`#4F6EF7` 靛蓝主色、统一鎏金/紫武/胜败语义色、`tabular-nums` 数字对齐与 `【夏鸥】bot` 页脚；旧版高饱和天蓝、深紫底、糖果绿与本地背景图死链全部清除。
- [x] **移动端竖卡画布规格统一**：全部 QQ 渲染入口统一为 `width=760, height="ck"`（物理输出 `1520px` 高清竖卡），`src/infra/screenshot.py` 窄视口高度测量时序已修正，万宝楼超长订阅已由裸 `<pre>` 切换为 `订阅列表.html`。
- [x] **Web 双入口与隐藏入口强约束**：`public/index.html` 与 `public/jjc-ranking-stats.html` 字节完全一致；公开 4 页顶栏导航严格仅含 `心法排名 / 对局查询 / 心法对阵` 3 项，绝不暴露 `jjc-sync-queue.html`；`jjc-sync-queue.html` 自身完整接入 `jjc-site.css` 浅色顶栏与标题区并保留全部 15 个业务 DOM `id`。
- [x] **安全、兼容性与双版本回归**：22 个 QQ 模板全量开启 `{% autoescape true %}` 并通过边界容错测试；Python 3.9 与 Python 3.13 编译及单测全绿；Playwright 离线渲染 22 张竖卡 + 10 个网页视口零横向溢出；原 `/home/songjingjing/codes/jx3bot` 工作区保持未改动。

## 回滚说明

本变更仅涉及表现层模板、静态网页与截图画布参数，无数据库或 API 契约变更。上线后如需回滚，切回上一提交并重启进程即可零成本恢复。
