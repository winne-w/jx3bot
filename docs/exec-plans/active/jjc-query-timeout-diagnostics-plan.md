# JJC 对局查询超时诊断日志计划

## 背景

JJC 对局查询接口仍存在超时，需要先补充阶段耗时日志，定位慢在本地身份解析、Mongo 对局扫描、seen 状态读取、行构建、推栏对局详情、replay 补全或投影写入中的哪一步。

## 范围

- `src/api/routers/jjc_ranking_stats.py`
  - 为 `/api/jjc/ranking-stats/synced-role-matches` 和 `/api/jjc/ranking-stats/match-detail` 增加入口到出口总耗时日志。
- `src/services/jx3/jjc_ranking_inspect.py`
  - 为 `get_synced_role_matches`、`get_match_detail`、推栏串行查询锁和 replay 补全增加阶段耗时日志。
  - `jjc_match_participants` 投影查询异常时返回标准错误结果，不 fallback 到详情集合扫描。
- `src/storage/mongo_repos/jjc_inspect_repo.py`
  - 固定从 `jjc_match_participants` 读取本地已同步 3v3 对局。
  - 保留详情集合直读方法的阶段耗时日志，供测试和代码回滚时验证旧路径。
- `src/storage/mongo_repos/jjc_match_participant_repo.py`
  - 为 `jjc_match_participants` 投影集合查询增加 count 与 find 分阶段耗时日志。
- `config.py` / `runtime_config.json`
  - 移除 `JJC_MATCH_PARTICIPANTS_READ_MODE` 运行时开关，代码固定读取 `jjc_match_participants` 投影表。

## 非目标

- 不调整缓存策略、索引或接口成功响应结构。
- 不在投影异常时 fallback 回扫 `jjc_match_detail`。

## 验证

- 执行 `python -m py_compile config.py src/api/routers/jjc_ranking_stats.py src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py src/storage/mongo_repos/jjc_match_participant_repo.py tests/test_jjc_ranking_inspect.py`。
- 执行 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_match_participant_repo`。
- 线上或本地调用慢接口后，通过日志中的 `elapsed_ms`、`phase_ms`、`wait_ms`、`query_ms` 判断瓶颈阶段。

## 回滚

- 代码回滚到详情集合直读路径，或修复/回填 `jjc_match_participants` 投影数据；本次不保留运行时开关。

## 执行状态

- 已实现：路由、service、repo 三层阶段耗时日志，补充 `jjc_match_participants` 投影集合查询耗时日志，并移除读取模式开关，固定读取参与者投影表。
- 已验证：
  - `python -m py_compile config.py src/api/routers/jjc_ranking_stats.py src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py src/storage/mongo_repos/jjc_match_participant_repo.py tests/test_jjc_ranking_inspect.py`
  - `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_match_participant_repo`
