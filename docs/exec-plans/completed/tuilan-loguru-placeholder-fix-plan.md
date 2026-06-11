# 推栏请求日志占位符修复计划

## 背景

运行日志出现：

```text
推栏角色 indicator 请求失败: %s
```

实际错误内容没有输出。该链路使用 `nonebot.logger`，底层是 loguru 风格格式化，`logger.warning("... %s", value)` 不会按标准 logging 的 `%s` 规则展开参数。

## 目标

- 修复推栏 `role/indicator` 请求失败和异常日志，确保输出真实错误内容。
- 顺手修正同一 `src/services/jx3/` 下已检出的同类 `%s` 日志，避免其他推栏请求继续丢失变量。
- 不改变业务返回结构、请求参数、缓存策略和外部接口调用行为。

## 涉及文件

- `src/services/jx3/role_indicator.py`
- `src/services/jx3/match_history.py`
- `src/services/jx3/match_detail.py`
- `src/services/jx3/match_replay.py`
- `src/services/jx3/kungfu.py`
- `src/services/jx3/jjc_cache_repo.py`
- `src/services/jx3/jjc_ranking.py`
- `src/services/jx3/match_detail_participant_projection.py`
- `src/services/jx3/jjc_sync_worker_runtime.py`

## 实施步骤

1. 将 `logger.*("... %s", value)` 改为 loguru 兼容的 `logger.*("... {}", value)`。
2. 对 `role_indicator.py` 的异常日志使用 `{}` 占位符，确保捕获异常时也能看到具体错误。
3. 搜索确认 `src/services/jx3/` 中不再保留同类 `%s` 日志占位符。

## 验证

- 执行 `rg -n "logger\\.(warning|error|info|debug)\\([^\\n]*%s" src/services/jx3`，确认没有残留。
- 执行 `python -m py_compile` 检查被修改 Python 文件。

## 执行记录

- 2026-06-11：已将 `src/services/jx3/` 下检出的 `%s` 日志占位符改为 loguru 兼容的 `{}`。
- 2026-06-11：已验证 `src/services/jx3/` 不再存在同类 `%s` 占位符残留。
- 2026-06-11：已对本次修改过的 Python 文件执行 `python -m py_compile`，通过。

## 风险与回滚

- 风险：仅改日志格式，运行行为风险低。
- 回滚：将日志占位符从 `{}` 恢复为原字符串即可。
