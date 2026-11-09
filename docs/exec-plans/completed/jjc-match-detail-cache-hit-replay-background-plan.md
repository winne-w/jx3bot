# JJC match_detail cache hit replay 后台补全计划

状态：已实现/已验证，待提交
更新时间：2026-06-04

## 背景

线上日志显示身份投影并发后，`match-detail` cache hit 请求仍可能被 replay 补全拖慢：`match_replay` 请求排队约 0.9 秒，请求本身约 22.8 秒，最终 `enrich_ms=23778`，接口总耗时约 28.9 秒。cache hit 场景已经有可展示的详情缓存，replay 缺失不应无限阻塞页面响应。

## 目标

- cache hit 场景下 replay 补全只等待短时间预算。
- 超过预算后先返回已有缓存详情，并标记 replay 补全仍在后台进行。
- 后台补全完成后仍保存 `data.replay`，并继续触发身份投影和参与者投影。
- replay 已缓存或补全很快时，保留现有同步返回带 replay 数据的行为。

## 非目标

- 不改变 cache miss 首次详情查询流程。
- 不修改推栏 HTTP 客户端全局超时和重试策略。
- 不新增数据库字段或索引。

## 涉及文件

- `src/services/jx3/jjc_ranking_inspect.py`
  - 抽出 cache hit replay 补全、保存和投影 helper。
  - 使用 `asyncio.wait_for(asyncio.shield(...))` 设置短等待预算，超时后后台继续执行。
- `tests/test_jjc_ranking_inspect.py`
  - 补充 cache hit replay 补全超时先返回、后台保存的单测。

## 验证

```bash
python -m py_compile src/services/jx3/jjc_ranking_inspect.py
python -m unittest tests.test_jjc_ranking_inspect
```

验证结果（2026-06-04）：

- `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/services/jx3/match_detail_identity_projection.py` 通过。
- `python -m unittest tests.test_jjc_ranking_inspect` 通过，76 个用例。

## 回滚

回滚 `jjc_ranking_inspect.py` 中 cache hit replay 后台补全逻辑和对应测试即可；缓存格式不变。
