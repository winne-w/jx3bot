# P5 展示层、浏览器池与插件收尾（design-p5-presentation）

日期：2026-11-27  
分支：`refactor/design-p5-presentation`（基于 `origin/main` `e7fe850` + P0~P3）  
关联评审：`design_review.md` 阶段 5

## 背景与目标

`feat/unify-visual-style` 已合入 `main`，现推进原避让的展示层与插件收尾：
1. **`BrowserPool` 浏览器池复用**（`src/infra/screenshot.py` + `bot.py`）：避免每次 `jietu` / `jx3web` 重新拉起 Chromium，常驻 browser 实例、每次仅新建/关闭 page，并在 `bot.py` shutdown 时优雅关闭。
2. **分段排名模板参数化**（`templates/竞技场心法排名_分段.html` + `src/renderers/jx3/jjc_ranking.py`）：用单表驱动 + 单参数化模板替代 8 份重复的 `send_split_ranking_images` 配置（保留原 8 份文件名兼容 `test_visual_style_unification.py`）。
3. **前端公共工具抽离**（`public/jjc-common.js`）：统一 `escapeHtml` / `formatTime` / `fetchJson` 并在 4 个 JJC 页面引入，保持 `public/index.html` 与 `public/jjc-ranking-stats.html` 严格一致。
4. **万宝楼插件去重**（`src/plugins/wanbaolou/__init__.py`）：修复重复定义的 `handle_my_subscriptions` 并复用 `singletons.jinja_env`。
