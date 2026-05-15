# 推栏接口按端点互斥计划

## 需求

当前 JJC 排名统计下钻相关推栏请求共用同一把查询锁，导致 `role_indicator` 与 `match_detail` 等不同接口互相阻塞。目标是改为同一接口串行，不同接口可并发，例如多个 `match_detail` 不能同时请求，但 `role_indicator` 和 `match_detail` 之间不互斥。

原有请求之间的 sleep 保留，不在本次改动中删除或绕过。

## 影响范围

- `src/services/jx3/jjc_ranking_inspect.py`
  - 将 `_get_tuilan_query_lock()` 改为按接口键获取锁。
  - `_run_serialized_tuilan_query()` 增加接口键参数。
  - 调整 `role_indicator`、`match_history`、`match_detail`、`live_ranking` 的锁键。
- `tests/test_jjc_ranking_inspect.py`
  - 增加并发锁行为单测，覆盖同接口串行、不同接口并发。

不改动推栏请求签名、URL、缓存策略、Mongo 存储结构、已有 sleep 调用位置。

## 实施步骤

1. 在 inspect service 内维护每个事件循环下的接口锁字典。
2. 为推栏查询包装函数传入 `endpoint_key`，日志同时输出接口键和业务 label。
3. 将直接使用全局锁的实时榜单查询改为 `live_ranking` 接口键。
4. 增加单测验证：
   - 相同 `endpoint_key` 的两个请求不会重叠。
   - 不同 `endpoint_key` 的请求可以并发进入。
5. 运行相关单测与 Python 3.9 编译检查。

## 验证

```bash
python -m unittest tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_ranking_inspect.py tests/test_jjc_ranking_inspect.py
```

## 回滚

如线上推栏接口仍要求全局串行，可将各调用点的 `endpoint_key` 统一回退为同一个固定值，或恢复单一 `_get_tuilan_query_lock()` 实现。

