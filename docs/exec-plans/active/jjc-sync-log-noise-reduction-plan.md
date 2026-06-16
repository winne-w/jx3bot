# JJC 同步高频日志降噪计划

## 背景

`jjc_sync` 当前同步过程中会在每个角色和每个对局详情上输出 INFO 级进度日志。worker 长时间运行或处理大量对局时日志量过大，影响查看真正异常。

## 目标

- 不新增运行时配置项。
- 删除 JJC 同步中的高频 INFO 进度日志。
- 保留 CLI 汇总输出、worker 启停信息、warning/error/exception 异常日志。

## 改动范围

- `src/services/jx3/jjc_match_data_sync.py`
  - 删除 `JJC 开始同步角色` INFO 日志。
  - 删除 `JJC 同步对局详情` INFO 日志。
- `docs/exec-plans/index.md`
  - 登记本计划。

## 非目标

- 不调整全局日志体系。
- 不新增 debug 开关。
- 不修改数据库、API、队列语义或同步行为。

## 验证

- 执行 `python -m py_compile src/services/jx3/jjc_match_data_sync.py`。
- 通过代码 review 确认只删除高频 INFO 输出，异常日志仍保留。

## 回滚

- 如后续需要恢复详细过程日志，可重新添加为 `logger.debug`，并另行设计项目级或 JJC 专属日志开关。

## 状态

- 已实现：删除角色开始同步、对局详情同步两个高频 INFO 日志。
- 已验证：`python -m py_compile src/services/jx3/jjc_match_data_sync.py` 通过。
- 已 review：确认 warning/error/exception 和 CLI 汇总输出未调整。
