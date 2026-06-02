# JJC 排名心法查询 sleep 调整计划

## 状态

- 2026-05-28：已实现并完成验证。
- 2026-05-29：已随提交 `99b01e6` 落地并归档到 `completed/`。

## 需求

- 将竞技排名逐个角色查询心法前的随机等待从 3-5 秒调整为 1-3 秒。

## 影响范围

- `src/services/jx3/jjc_ranking.py`
  - `get_user_kungfu()` 中 `random_sleep(3, 5)` 改为 `random_sleep(1, 3)`。

## 验证

```bash
python -m py_compile src/services/jx3/jjc_ranking.py
```

## 回滚

- 将 `random_sleep(1, 3)` 恢复为 `random_sleep(3, 5)`。
