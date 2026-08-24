# 需求目录索引

本目录用于沉淀需求级交付文档。新需求默认从 `_template/` 复制一份目录结构，按 `yyyy-mm-dd-short-name` 命名，并在本索引登记。

## 模板

- `_template/`: 需求澄清、方案、执行计划、测试、review、验收模板。

## Active

- `2026-08-24-jjc-match-season/`: 为 JJC 玩家对局投影持久化赛季归属，隔离新赛季查询并回填现有 Mongo 数据。
- `2026-07-27-jx3api-openapi-migration/`: 迁移已下线的 JX3API `/data` 路径，适配当前 OpenAPI 字段并明确降级无等价功能。
- `2026-07-03-jjc-peak-detail-consistency/`: 修复 JJC 统计页“14日游戏最高分排名”分布卡与展开详情口径不一致的问题。

## Completed

- `2026-06-17-jjc-sync-auto-dispatcher/`: 为 JJC 同步增加自动补队列 dispatcher，持续把到期角色补入 `queued`，提升现有 worker 利用率。
- `2026-06-17-jjc-peak-score-ranking/`: JJC 7 天历史最高分排名，基于最近两个排名快照时间点，从历史对局参与者生成推栏分数和游戏分数最高分榜。
