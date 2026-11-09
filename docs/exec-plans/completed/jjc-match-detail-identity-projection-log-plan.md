# JJC 对局详情身份投影耗时日志计划

状态：执行中
更新时间：2026-06-04

## 背景

线上对局详情查询日志显示 `project_identity_ms` 可达到 18 秒以上，但当前只记录身份投影总耗时，无法判断慢在 `role_identities` 写入还是 `jjc_sync_identity_queue` 写入。

## 目标

- 在对局详情身份投影中按玩家记录耗时。
- 拆分 `identity_repo.upsert_from_match_detail_with_id()` 和 `sync_repo.upsert_identity_queue_candidate()` 两段耗时。
- 日志不输出敏感凭证，仅输出 match_id、角色基础标识、是否入队和耗时。

## 实施

- 修改 `src/services/jx3/match_detail_identity_projection.py`：
  - 对每个有效玩家记录 `identity_ms`、`queue_ms`、`queued`。
  - 保留现有汇总日志。
- 验证：
  - `python -m py_compile src/services/jx3/match_detail_identity_projection.py`
  - `python -m unittest tests.test_jjc_ranking_inspect`

## 回滚

回滚本计划对应日志改动即可，不影响同步数据写入。
