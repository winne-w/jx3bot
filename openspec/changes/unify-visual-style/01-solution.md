# 全站清爽现代浅色视觉统一方案

日期：2026-11-26
状态：用户已确认方案与隐藏 `jjc-sync-queue.html` 入口约束；已在独立 worktree 完成实现与验证。

## 1. 统一 Design Tokens（JX3Bot Light Modern Design System）

| 语义角色 | CSS 变量 | 色值 | 用途说明 |
|---|---|---|---|
| 画布背景 | `--jx3-bg` | `#F3F6FB` | QQ 竖卡外层底色、HTTP 页面全局底色（移除旧斜纹遮罩与高饱和亮蓝渐变） |
| 一级卡片表面 | `--jx3-surface` | `#FFFFFF` | 主卡片、统计面板、顶栏背景 |
| 二级内嵌表面 | `--jx3-surface-alt` | `#F8FAFC` | 指标小格、列表项底、柱状图轨道底、筛选框底 |
| 卡片描边/分割线 | `--jx3-border` | `rgba(148, 163, 184, 0.22)` | 卡片外框与弱分割线 |
| 主文本 | `--jx3-ink` | `#1E293B` | 标题、角色名、核心数值、装备/奇遇名 |
| 次级文本 | `--jx3-muted` | `#64748B` | 区服、副标题、属性词条、时间戳、表头文字 |
| 品牌主色 | `--jx3-primary` | `#4F6EF7` | 主按钮、激活态导航、常规胶囊高亮 |
| 输出柱条渐变 | `--jx3-bar-dps` | `linear-gradient(90deg, #5B7CFA 0%, #89B4FA 100%)` | DPS 心法条、主进度条 |
| 治疗柱条渐变 | `--jx3-bar-healer` | `linear-gradient(90deg, #38BDF8 0%, #818CF8 100%)` | 治疗心法条 |
| 橙武/绝世鎏金 | `--jx3-gold` | `#B45309` / `#F59E0B -> #FBBF24` | 大橙武占比段、橙武名、绝世奇遇、精炼满星 |
| 史诗紫武色 | `--jx3-purple` | `#6D28D9` | 常规紫品装备名称、宠物奇遇等 |
| 正/负向语义 | `--jx3-success` / `--jx3-danger` | `#15803D` / `#B91C1C` | 胜负、开服/离线、在售/未通、价格高亮 |

## 2. QQ 模板图片统一架构（`760px` 移动端双倍网格竖卡）

1. **共享内联片段（`templates/_partials/`）**：
   - `base_card_style.html`：统一定义 `--jx3-*` 设计变量、`760px` 布局容器、字阶、胶囊、指标格、进度条与 `tabular-nums`。
   - `card_header.html` / `card_footer.html`：统一页眉与 `【夏鸥】bot` 页脚，显式包裹 `{% autoescape true %}`。
   - `ranking_lane_card.html`：统一竞技排名合图与 8 张拆分图的心法分布条渲染宏（含零除保护与金色橙武叠加段）。
2. **截图高度测量修正（`src/infra/screenshot.py`）**：
   - `jietu()` 先创建目标 `width` 视口并执行 `page.set_content(html_content)`，等待页面内 `<img>` 加载或报错返回（带 3000ms 超时兜底），最后在目标窄宽度下读取 `scrollHeight` 并调整视口高度截图。
   - `jx3web()` 动态页脚对齐 `#F3F6FB` 与 `【夏鸥】bot`。
3. **22 个活跃模板全量覆盖**：
   - 竞技排名合图 + 8 拆分图、竞技查询（含 `jjc.html`）、装备查询（由深紫切换为浅色，保留全部移动端单测契约与内嵌图标）、奇遇查询、万宝楼查询、新增 `订阅列表.html`（替代裸 `<pre>`）、交易行查询（含内网货币图标断链自动降级为 `砖/金/银` 文字徽章及铜币兜底）、烟花查询（修复硬编码区服 bug）、资历查询（移除 `225*len` 横向拉宽）、百战角色查询、百战查询、副本查询、群帮助 `qun.html`。
   - 全部 22 个模板显式启用 `{% autoescape true %}`。

## 3. HTTP 页面统一架构（5 个静态页面 + 隐藏队列入口）

1. **`public/jjc-site.css`**：写入 `--jx3-*` 变量，移除 `.page::before` 斜纹遮罩，保留 `.page { max-width: 1920px }` 与窄屏导航堆叠规则。
2. **公开 4 页（`index.html`、`jjc-ranking-stats.html`、`jjc-synced-matches.html`、`jjc-matchups.html`）**：统一面板圆角（`18px`）、控件焦点态、柱条配色与主按钮，保持 `index.html == jjc-ranking-stats.html` 字节一致，且顶栏导航严格仅含 3 个公开入口，不出现 `jjc-sync-queue.html`。
3. **隐藏监控页（`public/jjc-sync-queue.html`）**：接入 `.page`、`.site-header`（提供返回 3 个公开页的导航，无 `aria-current="page"`）、`.page-title-region` 与 `jjc-site.css`，完整保留全部 15 个业务 DOM `id` 与 10 秒自动轮询脚本。
