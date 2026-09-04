# 手工验收记录

日期：2026-09-04

- 页面 Playwright Chromium 验收（桌面 1440×1000、移动 390×844）：最近 7 天默认值、奶秀 vs 明教、策藏 vs 奶花、策藏 vs 气明歌、单边空、双方空、重复心法、交换、20/50/100 分页、绝对时间 URL 重放、双向列表去重、分数未填禁用均通过。
- 点击 `match_id` 调用既有 match-detail，六名玩家装备与奇穴展示、Escape 关闭、焦点恢复和移动端弹窗滚动通过。
- 页面无横向溢出、console/page error 为空；Browser plugin 不可用，使用 Playwright Chromium 1.51。
- 目标 Mongo 性能脚本 7/14 天十种形态全部命中预期索引，无 blocking SORT/facet 错误；7 天单心法 21ms，14 天双方空 162ms。

未覆盖：生产站点反向代理与真实用户权限；这些依赖部署环境，需上线后按 runbook 复核。
