# 测试与线上验收

用户 2026-11-09 确认按方案修复。主执行者整合，子 agent 先行补业务测试、前端测试及真实 Mongo 集成；生产操作由主执行者负责。

## 自动化

运行 `.venv/bin/python -m unittest tests.test_jjc_peak_score_ranking tests.test_jjc_ranking_stats_router tests.test_jjc_match_participant_repo tests.test_jjc_ranking_stats_frontend tests.test_jjc_data_center_navigation tests.test_rebuild_jjc_peak_score_rankings`。

隔离 Mongo 使用显式 `JJC_TEST_MONGO_URI=mongodb://127.0.0.1:27029/` 运行 `tests.test_jjc_peak_score_season_mongo`，只创建随机测试库，完成后清理。覆盖旧高新低角色、仅旧角色、新角色补位、边界前后一秒、未来/缺失时间、两分数与来源计数、BSON Int64、缓存投影、旧 done 重算、force 幂等、再切季读取历史。真实 explain 记录 keys/docs 与索引，不能以小样本证明生产吞吐。

业务测试覆盖无摘要/赛季冲突/未知历史边界、缓存元数据、应用与驱动 ExecutionTimeout、生成/写失败不假报成功与错误脱敏。CLI 测试验证 dry-run/verify 无写、全部锚点预校验、错误退出与参数选择。前端 Node 实际执行测试验证新/legacy/切换快照的窗口说明。

## 生产候选

候选只包含确认过基线的六个部署文件，不修改 config、runtime_config 或独立离线统计工作。使用生产 Python 3.9.9、复制的生产源码及选定测试在临时目录验证；不连接生产库运行自动化。若发现存量测试失败，必须用未改动生产文件重现并保存记录，不以删断言作为通过。

## 生产恢复

先保存原目标文档的 canonical Extended JSON、源码及哈希，再只读 dry-run。替换后重启 bot，核对就绪、4 worker、配置哈希和公网业务成功。优先重建最新及 03:00 结算快照，再处理全部当前赛季锚点；重新枚举并 verify。公网验证 game/tuilan 的四个范围、列表时间和心法分布/详情人数，抽样旧赛季结果仍可读，静态页含口径说明。原始比赛与队列不清库。
