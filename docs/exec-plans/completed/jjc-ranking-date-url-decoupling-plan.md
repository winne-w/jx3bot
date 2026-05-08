# JJC 排行榜日期选择与 URL 解耦计划

状态：已实现，待提交
更新时间：2026-05-08

## 执行状态

- 2026-05-08：已实现前端日期选择与 URL 解耦。页面初始化忽略 URL `timestamp`，始终选中可用日期中的最新快照；切换日期不再写入浏览器 URL；`read/details` 内部请求仍使用当前页面状态中的 timestamp。
- 2026-05-08：验证已执行：前端内嵌脚本 `new Function` 语法检查通过；搜索确认 `initialTimestamp`、`updateUrlTimestamp`、`history.pushState` 无残留。
- 2026-05-08：根据用户反馈，不做主动删除 URL `timestamp` 的防御性清理，避免改写地址栏引入后续边界问题；行为保持为“不读取、不写入”。

## 背景

`public/jjc-ranking-stats.html` 当前支持通过 URL 查询参数 `timestamp` 指定初始展示的统计快照，并且在用户切换“可用日期”时调用 `history.replaceState()` 把新的 `timestamp` 写回浏览器地址。这样分享或刷新旧链接时，会继续打开历史日期数据。

用户希望前端页面切换历史日期时不要把时间戳带到 URL 里，也不要由 `timestamp` 参数决定展示哪天的数据；打开链接时直接显示最新一天的数据。

## 目标

- 页面初始化时始终从 `action=list` 返回的可用日期中选择最新一天数据。
- 用户切换“可用日期”只改变页面内存状态和下拉选中项，不修改浏览器 URL。
- 即使 URL 中存在历史遗留的 `timestamp` 参数，也不使用它决定展示日期。
- `timestamp` 仍作为前端调用后端 `action=read` 和 `details` 接口的内部请求参数，因为后端读取指定快照仍需要它。

## 非目标

- 不改变后端 `/api/jjc/ranking-stats?action=read&timestamp=...` 和 `/details?timestamp=...` 的接口签名。
- 不删除 README 中 API 层面的 `timestamp` 参数说明。
- 不改变统计快照文件或 Mongo 迁移计划中的 `timestamp` 结构。
- 不增加“分享当前历史日期”的深链接能力。

## 涉及文件

- `public/jjc-ranking-stats.html`
  - 删除或停用 `initialTimestamp = params.get("timestamp")` 对首屏日期的影响。
  - `renderDateList()` 默认选中排序后的第一项，即最新快照。
  - 删除 `updateUrlTimestamp()`，或保留为空操作但不再调用。
  - `loadStats(timestamp)` 只更新 `currentStatsTimestamp` 和页面内容，不写 URL。
  - 页面底部初始化逻辑只调用 `loadDateList()`，不再因 URL `timestamp` 额外调用 `loadStats(initialTimestamp)`。
  - 日期下拉切换仍调用 `loadStats(value)`。
- `docs/references/runbook.md`
  - 如果现有手工回归清单提到通过 URL `timestamp` 打开历史数据，需要更新为通过页面下拉切换历史日期。

## 行为设计

页面加载流程：

1. 请求 `GET /api/jjc/ranking-stats?action=list`。
2. 对返回的 timestamp 数组倒序排序。
3. 选择第一项作为当前展示日期。
4. 调用 `GET /api/jjc/ranking-stats?action=read&timestamp=<latest>` 加载最新快照。
5. 地址栏保持原链接，不新增、不更新 `timestamp`。

用户切换日期：

1. 用户在“可用日期”下拉中选择历史日期。
2. 前端调用 `loadStats(selectedTimestamp)`。
3. 页面渲染对应历史快照。
4. 地址栏不变化；刷新或重新打开链接后仍回到最新快照。

URL 参数兼容：

- 保留 `list_api`、`api`、`details_api`、`role_recent_api`、`match_detail_api` 等调试参数。
- 忽略 `timestamp` 参数。即使链接中存在 `?timestamp=旧值`，页面也按最新快照初始化。
- 不主动清理已有 `timestamp` 参数；关键是它不参与展示逻辑，也不会在用户切换日期时被新增或更新。

## 实施步骤

1. 修改 `public/jjc-ranking-stats.html`，移除 `initialTimestamp` 对 `currentStatsTimestamp`、`renderDateList()` 和初始化加载的影响。
2. 移除 `loadStats()` 中写 URL 的逻辑，确保日期切换不会产生 `timestamp` 查询参数。
3. 检查详情懒加载逻辑，确认 `buildDetailsUrl(currentStatsTimestamp, ...)` 仍使用当前页面状态，不依赖浏览器 URL。
4. 搜索 runbook/文档中的 URL 历史日期说明，如存在则同步更新。
5. 执行前端脚本语法检查和手工回归。

## 验证

自动化/静态检查：

```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('public/jjc-ranking-stats.html','utf8'); const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]); scripts.forEach((s)=>new Function(s)); console.log('scripts ok', scripts.length)"
```

手工：

- 打开 `public/jjc-ranking-stats.html`，确认默认加载可用日期中的最新一天。
- 打开 `public/jjc-ranking-stats.html?timestamp=<旧时间戳>`，确认仍加载最新一天，不使用 URL 中旧时间戳。
- 在“可用日期”中切换历史日期，确认页面显示对应历史快照，但地址栏不新增或更新 `timestamp`。
- 切换历史日期后刷新页面，确认重新显示最新一天。
- 展开某个心法详情，确认详情接口仍使用当前下拉选中的快照 timestamp。

## 风险与回滚

- 风险：失去通过 URL 直接分享历史日期的能力。该行为符合本次需求。
- 风险：调试时无法靠 `timestamp` 参数直达历史快照。仍可通过日期下拉切换。
- 回滚：恢复读取 `params.get("timestamp")` 作为初始值，并恢复 `loadStats()` 中的 URL 写入逻辑。
