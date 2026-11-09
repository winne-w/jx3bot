# JJC 7 天历史最高分排名验收记录

## Acceptance Scope

待实现后记录最终交付内容、验证命令、数据样例、线上观察点和回滚方式。

## Result

已实现：

- `jjc_match_participants` 新增推栏分数、游戏分数和原始分数字段。
- 新增 `jjc_peak_score_rankings` 存储 repo 和最高分聚合 service。
- 新增每天 09:00 的 JJC 7 天历史最高分统计任务。
- 新增当前推栏排名扁平列表 API 与 7 天最高分排名 API。
- 现有 JJC 排名页面新增心法分布、当前排名列表、7 日推栏最高分、7 日游戏最高分视图。
- 新增 Mongo 索引和数据库设计文档说明。
- runbook 增加历史投影回填和最高分统计排查说明。

已验证：

- 单测和编译检查通过。
- `scripts/backfill_jjc_match_participants.py --limit 1` dry-run 可从历史对局详情重建 6 条参与者投影。

未执行全量历史回填 apply；上线后需按 runbook 先小批量 apply 验证，再全量回填。
