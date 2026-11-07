# 实现、测试与发布验收记录

日期：2026-11-07。业务方案已确认，按用户要求执行 TDD。已完成生产发布与验收（见 deployment.md）；三路子 agent 独立初评与两路定向复评已完成，本次范围 PASS。

Red：核心 8 个行为用例在新增请求接口、队首排序及重排行为上失败；统计 unknown/同轮上下文 2 项失败；QQ 与定时入口上下文 2 项失败；人工优先级并发保持 2 项失败。相关 Green 均已通过。

真实 Mongo 首轮 6 项有 1 项失败：64 并发竞争相等旧值 CAS，最新请求耗尽 16 次重试。改为 Mongo 原子单调条件后通过，追加 public identity syncing 路径验证后共 7 项通过。隔离服务 MongoDB 8.0.16，loopback:27029，随机 jjc_sync_front_test_ 库逐测清理；没有生产访问。

Python 3.13.2 与 Python 3.9.25 各运行以下 388 项，全部通过（含 7 项真实 Mongo 测试）。Python 3.9 使用已有 `/tmp/jjc-kungfu-python39/bin/python` 环境。首次误选未安装依赖的另一个空 venv 导致导入失败，环境修正后完成真实双版本回归。

```sh
JJC_TEST_MONGO_URI=mongodb://127.0.0.1:27029/ .venv/bin/python -m unittest tests.test_jjc_ranking_force_sync tests.test_jjc_ranking_force_sync_mongo tests.test_jjc_sync_worker_queue tests.test_jjc_match_data_sync tests.test_jjc_ranking_stats_repo tests.test_jjc_ranking_history_win_kungfu tests.test_jjc_ranking_kungfu_cache tests.test_jjc_ranking_inspect tests.test_jjc_ranking_command_tag tests.test_status_monitor_jobs_offline_statistics tests.test_status_monitor_jobs_admin_notification tests.test_status_monitor_jobs_config tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_explicit_tag
```

来源日志：`/tmp/jjc-front-final313.log`、`/tmp/jjc-front-final39.log`；Red 日志 `/tmp/jjc-front-red.log`、`/tmp/jjc-front-service-red.log`、`/tmp/jjc-front-entry-red.log`、`/tmp/jjc-front-priority-red.log`。现有无关工作区改动未回滚或提交。

独立评审提出两个 P3，均已闭环；详见 review.md 和 CODE_REVIEW_REPORT.md。生产源码复评期间未变，相关 py_compile 与 git diff --check 通过，隔离 Mongo 服务已关闭，日志保留。未验证生产吞吐、时钟偏差、实际上游请求延时；上线要求统一 bot/worker 版本，具体回滚前转换见 runbook。

## 评审后定向补测

计划方法名及传参文案已修正，不改变业务实现。补充以下3项用例，在Python 3.13.2与3.9.25分别通过，初次运行即Green（对已实现行为补直接证据）：

```sh
JJC_TEST_MONGO_URI=mongodb://127.0.0.1:27029/ .venv/bin/python -m unittest tests.test_jjc_ranking_force_sync.TestRankingForceSync.test_request_retries_if_worker_claims_between_read_and_update tests.test_jjc_ranking_force_sync_mongo.TestRankingForceSyncMongo.test_new_request_competes_with_worker_claim tests.test_jjc_ranking_force_sync_mongo.TestRankingForceSyncMongo.test_new_client_and_repo_restore_persisted_pending_after_consumer_restart
```

日志 `/tmp/jjc-front-review-followup313.log`、`/tmp/jjc-front-review-followup39.log`。累计每版本388+3=391项通过，其中9项真实Mongo；并未在复评后重新整跑391项。真实并发用例允许两种合法线性化顺序，不要求随机调度实际同时命中两分支；确定性注入补齐“读取后被领取”的关键顺序。重启恢复通过关闭旧连接后新连接与仓储实例验证，未模拟完整进程启动或真实推栏同步。review_queue、review_plan已只读确认补测证据闭环，无新增问题。

## 提交独立性与发布前补验

提交前发现定时入口用例借用了未跟踪的其他任务测试，已改用 HEAD 中已有的 admin_notification 夹具，业务源码不变。review_ranking 定向只读复评 PASS，确认 Git 基线入口与保留线上离线统计修复的生产入口均正确传递 `_sync_request`。

从选择性暂存树导出独立快照（不含其他任务未提交文件）：Python 3.13 372 项通过；Python 3.9 381 项通过（含 9 项真实隔离 Mongo）。日志 `/tmp/jjc-front-clean-snapshot.log`、`/tmp/jjc-front-clean-snapshot39.log`。

生产私有回滚转换脚本已在 loopback:27029 随机测试库演练两队列 pending 物化、最新参数、更高人工 priority、审计/水位保留、disabled 不复活、普通在途租约保持及重复执行；全部通过。该转换尚未在生产执行。

## 生产验收

实现提交e1ee55e已推送并发布，生产候选382项通过，启动/API/QQ/新索引/4worker及实际角色重新同步验证通过。完整对照测试、上线观察与回滚证据见 [deployment.md](deployment.md)。
