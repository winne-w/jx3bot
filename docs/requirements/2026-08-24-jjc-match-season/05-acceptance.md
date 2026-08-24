# JJC 对局赛季归属与查询隔离 验收记录

## Delivered Changes

- 已完成本地代码、索引定义、回填工具和文档改动；Mongo 数据回填尚未执行。

## Verification

- 自动化验证：`python -m unittest tests.test_jjc_match_participant_repo tests.test_jjc_match_participant_projection tests.test_jjc_ranking_inspect tests.test_backfill_jjc_match_participant_season` 通过；相关模块 `py_compile` 通过。
- 手工冒烟：待可用 Mongo 和运行中的 bot 环境完成。
- review：已完成，发现的列表防线和批量失败可观测性问题均已修复。

## Residual Risks

- Mongo 已确认可连通且有 8,381,308 条 3v3 投影；但本工具的单次 30 秒窗口不足以等待全量 dry-run 完成，因此不能证明现有投影已写入 `season_id`。
- 目标部署需重启 bot 以创建新索引并加载最新 `CURRENT_SEASON` 配置。

## Rollback

恢复上一版应用代码可恢复跨赛季读取；新增 `season_id` 字段不会改变完整对局详情。没有完成数据回填时无需执行数据回滚。

## Acceptance

待 Mongo 回填、核验和页面冒烟完成后确认。
