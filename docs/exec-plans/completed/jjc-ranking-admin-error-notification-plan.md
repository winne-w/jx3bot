# JJC 排名定时任务管理员错误通知计划

## 目标

竞技排名定时任务的统计失败要私聊通知 `config.ADMIN_QQ` 中的管理员，携带失败阶段与原始错误信息。

## 涉及文件

- `src/plugins/status_monitor/jobs.py`：集中管理员私聊容错逻辑，并在统计失败出口调用它。
- `tests/test_status_monitor_jobs_admin_notification.py`：使用动态模块加载和 NoneBot 依赖 stub，覆盖通知行为、失败出口和免通知前置条件。
- `docs/exec-plans/index.md`：登记并在完成时归档本计划。

## 实施步骤

1. 新增异步测试夹具和失败测试，证明管理员通知会逐人发送、单人失败不中断，并验证每个统计失败出口会通知。
2. 运行新增测试，确认它因通知逻辑尚不存在而失败。
3. 在 `jobs.py` 添加最小通知辅助函数；将任务的可识别统计失败出口统一经由该函数退出，保留现有日志与正常路径。
4. 运行新增测试和现有调度配置测试，执行 `py_compile`。
5. 复核 diff、运行 `git diff --check`，将计划补充测试与 review 结果后归档至 `docs/exec-plans/completed/` 并更新索引。

## 验证

```bash
python -m unittest tests.test_status_monitor_jobs_admin_notification tests.test_status_monitor_jobs_config
python -m py_compile src/plugins/status_monitor/jobs.py tests/test_status_monitor_jobs_admin_notification.py tests/test_status_monitor_jobs_config.py
```

预期：测试覆盖所有已知统计失败出口、两个免通知前置条件与通知容错，命令退出码为 0。

## 风险与回滚

管理员 QQ 不可达时通知函数只记录 warning，不影响任务清理或其他管理员。回滚时移除本次通知辅助函数和失败出口调用即可恢复仅日志行为。

## 执行状态

- [x] 计划创建
- [x] 失败测试
- [x] 最小实现
- [x] 自动化验证
- [x] Review 与归档

## 验证记录

- `python -m unittest tests.test_status_monitor_jobs_admin_notification tests.test_status_monitor_jobs_config`：6 项通过。覆盖管理员逐人通知、单个私聊失败继续、7 个统计失败出口、顶层异常以及无 Bot/无目标群免通知。
- `python -m py_compile src/plugins/status_monitor/jobs.py tests/test_status_monitor_jobs_admin_notification.py tests/test_status_monitor_jobs_config.py`：通过。
- `git diff --check`：通过；工作区输出的 LF/CRLF 提示来自仓库现有换行策略，未报告空白错误。

## Review 记录

主执行者逐行复核 `jobs.py` 的失败出口与新增测试：通知函数在管理员私聊失败时捕获异常并继续循环；排行榜空结果、业务错误、错误码、心法数据空/错误、空统计、渲染失败和顶层异常均调用通知；没有 Bot、没有目标群的返回路径没有调用通知。没有发现需修改的问题。
