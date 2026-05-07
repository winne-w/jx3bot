# Task: JJC Ranking Role Inspect

状态：进行中
更新时间：2026-04-27

执行计划：`docs/exec-plans/active/jjc-ranking-role-inspect-plan.md`

## 目标

- 为竞技场统计页增加角色级下钻能力
- 点击角色时按需查看最近一段时间 33 胜负和最近对局列表
- 点击对局时按需查看单局详情
- 不在生成排名时预热这些数据，统一改为点击时被动缓存

## 范围

- `src/api/routers/jjc_ranking_stats.py`
- `src/services/jx3/`
- `src/storage/`
- `public/jjc-ranking-stats.html`
- `README.md`
- `docs/references/runbook.md`

## 约束

- 排名统计落盘结构不增加角色战绩或对局详情预热
- 角色最近战绩按 `server + name` 被动缓存 60 秒
- 对局详情按 `match_id` 被动缓存
- 新增 HTTP API 只做参数校验和 service 转发

## 完成标准

- 角色明细行可点击弹出最近 33 战绩卡片
- 最近对局列表可继续点击查看单局详情
- 首屏加载仍只依赖统计 summary/details
- 回归说明和 API 文档同步更新
