# JJC 对阵统计测试计划

## 自动化

- 事实构建、CAS、tombstone 与索引：`tests/test_jjc_match_fact*.py`、`tests/test_jjc_match_detail_persistence.py`。
- 组合筛选、双向统计、空边、分数边界与分页：`tests/test_jjc_matchup_service.py`、`tests/test_jjc_match_fact_repo.py`。
- API 错误包装：`tests/test_jjc_matchups_router.py`。
- 页面静态合同与详情复用：`tests/test_jjc_matchups_frontend.py`。
- 回填与性能脚本：`tests/test_backfill_jjc_match_facts.py`、`tests/test_check_jjc_matchup_performance.py`。

## 目标 Mongo 门禁

已在目标库完成回填、增量补齐与核验：missing/hash/schema/should_be_inactive/build_failed 均为 0；全局 orphan 已完成一次完整核验为 0。真实性能脚本覆盖单心法、双心法、完整组合、单边空、双方空的 7/14 天查询，需以最新运行输出确认索引、扫描量、SORT/facet 和耗时。

## 手工页面冒烟

使用 Playwright Chromium 在桌面与移动 viewport 验证最近 7 天奶秀 vs 明教、策藏 vs 奶花、策藏 vs 气明歌、空边、重复心法、交换、分页、绝对时间 URL 和 match-detail 奇穴弹窗。浏览器插件不可用时，以 Playwright 记录为准；外部 Mongo/API 依赖需在验收记录中注明。
