# JJC match_detail 身份投影并发化计划

状态：已实现/已验证，待提交
更新时间：2026-06-04

## 背景

线上日志显示 `match-detail` cache hit 后 replay 补全约 1.9 秒，但身份投影 6 个玩家串行耗时约 16.2 秒，接口总耗时被 `project_identity_ms` 主导。单个玩家 upsert 互相独立，当前串行循环会把每个玩家的 Mongo 查询和写入耗时累加到 HTTP 响应。

## 目标

- 同一场对局的玩家身份投影并发执行，降低 `match-detail` 接口在 replay 补全后触发投影时的响应等待。
- 保留每个玩家内部顺序：先写 `role_identities`，再写 identity 同步队列候选。
- 保留现有跳过规则、日志字段、返回计数和异常向上抛出的行为。

## 非目标

- 不调整 `role_identities` 身份匹配规则、画像覆盖规则或索引。
- 不改变 replay 补全、match_detail 缓存保存、参与者投影流程。
- 不做线上索引创建或历史数据迁移。

## 涉及文件

- `src/services/jx3/match_detail_identity_projection.py`
  - 将单玩家投影逻辑抽为内部协程。
  - 对有效玩家使用 `asyncio.gather` 并发执行。
- `tests/test_jjc_ranking_inspect.py`
  - 补充并发投影单测，验证多个玩家 upsert 会重叠执行。

## 验证

```bash
python -m py_compile src/services/jx3/match_detail_identity_projection.py
python -m unittest tests.test_jjc_ranking_inspect.TestMatchDetailIdentityProjection
python -m unittest tests.test_jjc_ranking_inspect
```

验证结果（2026-06-04）：

- `python -m py_compile src/services/jx3/match_detail_identity_projection.py` 通过。
- `python -m unittest tests.test_jjc_ranking_inspect.TestMatchDetailIdentityProjection` 通过，4 个用例。
- `python -m unittest tests.test_jjc_ranking_inspect` 通过，75 个用例。

## 回滚

回滚 `match_detail_identity_projection.py` 的并发化改动和对应测试即可；数据结构和缓存内容不变。
