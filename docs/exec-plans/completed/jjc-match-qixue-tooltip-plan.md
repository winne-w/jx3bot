# JJC 对局详情奇穴展示优化计划

## 背景

对局详情弹窗（match-modal）中，每个玩家的奇穴区域当前使用 `renderIconGrid` 渲染，仅展示奇穴图标 + 浏览器原生 `title` 属性显示名称。对局接口实际返回了奇穴的 `name`（名称）和 `desc`（描述），当前均未有效利用。

## 目标

- 奇穴区域改为图标 + 名称的卡片式布局：图标在上，名称在下。
- 鼠标悬浮时浮窗展示奇穴描述（`desc` 字段）。
- 浮窗不溢出弹窗边界，四字名称不被截断。

## 涉及文件

- `public/jjc-ranking-stats.html`

## 实施步骤

1. 新增 CSS 样式 `.talent-grid`（flex 容器）、`.talent-chip`（纵向卡片）、`.talent-chip-icon`（36×36 图标）、`.talent-chip-name`（下方名称文字），通过 `data-desc` + `::after` 伪元素实现 hover 浮窗。
2. 新增 JS 函数 `renderTalentGrid(talents, emptyText)`，渲染图标 + 名称，`desc` 写入 `data-desc`。
3. `renderTeam` 中奇穴区块改用 `renderTalentGrid` 替代 `renderIconGrid`。
4. 浮窗定位从居中改为左对齐，避免左侧溢出；名称 `max-width` 放宽至 60px。

## 验证方式

- 浏览器打开对局详情弹窗，确认奇穴区域展示图标 + 名称。
- 鼠标悬浮奇穴，确认浮窗展示描述，且最左侧奇穴的描述仍在弹窗可见范围内。
- 确认四字奇穴名称完整显示不被截断。

## 执行状态

- 2026-05-16：已完成全部改动。

## 回滚

将 `renderTeam` 中奇穴区块恢复为 `renderIconGrid(player.talents || [], "无奇穴")`，移除 `.talent-grid`/`.talent-chip` 相关 CSS 和 `renderTalentGrid` 函数。
