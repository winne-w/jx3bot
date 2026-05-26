# JJC 同步移除 person-history 补 SK01 计划

## 背景

`/mine/match/person-history` 会按 `person_id` 返回同一推栏账号下的多角色历史，当前同步逻辑用它补 `global_role_id` 时存在误匹配风险。后续规则调整为：`indicator` 接口查不到 SK01 `global_role_id` 时，不再通过 `person-history` 兜底补全。

## 范围

- 修改 `src/services/jx3/jjc_match_data_sync.py`：
  - 队列角色缺少 `global_role_id` 时，不再先调用 `person-history`，直接走现有 inspect/indicator 身份解析路径。
  - 对局详情玩家本地身份库未命中时，不再调用 `person-history` 补 `global_role_id`。
- 修改 `tests/test_jjc_match_data_sync.py` 中相关单测，验证不会再调用 `person-history` fallback。

## 非目标

- 不删除 `PersonMatchHistoryClient` 封装和配置项，避免影响后续手工诊断或其他潜在调用。
- 不做数据库迁移；已有历史身份数据本次不清理。

## 验证

- 运行 `python -m unittest tests.test_jjc_match_data_sync`。
- 运行 `python -m py_compile src/services/jx3/jjc_match_data_sync.py`。

## 执行状态

- 已实现：同步角色缺少 `global_role_id` 时直接走 inspect/indicator 身份解析，不再先查 `person-history`。
- 已实现：对局详情玩家本地身份库未命中时不再查 `person-history`，缺少 SK01 时只写身份投影并跳过可执行同步队列。
- 已验证：`python -m unittest tests.test_jjc_match_data_sync` 通过。
- 已验证：`python -m py_compile src/services/jx3/jjc_match_data_sync.py` 通过。

## 风险与回滚

- 风险：部分只有 `person_id` 且 indicator 查不到 SK01 的玩家不会再自动补全 SK01，也不会进入依赖 SK01 的历史同步。
- 回滚：恢复本计划对应代码 diff 和单测即可。
