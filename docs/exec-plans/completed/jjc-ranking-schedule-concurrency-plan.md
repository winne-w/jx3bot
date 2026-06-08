# JJC 自动排名统计允许并发计划

## 背景

当前自动竞技排名统计使用 APScheduler cron 在每天 04:00 和 21:00 触发，但未显式设置 `max_instances`。APScheduler 默认同一 job 只允许 1 个实例运行，如果 21:00 任务到次日 04:00 仍未结束，04:00 触发可能被跳过。用户要求改成允许并发。

## 目标

- 自动竞技排名统计 `push_daily_jjc_ranking` 允许最多 2 个实例并发运行。
- 不改变触发时间，仍为每天 04:00 和 21:00。
- 不改变群开关、统计流程、图片渲染和推送逻辑。

## 涉及文件

- `src/plugins/status_monitor/jobs.py`
  - 为 `@scheduler.scheduled_job("cron", hour="4,21", minute=0)` 增加 `max_instances=2`。
- `tests/test_status_monitor_jobs_config.py`
  - 用 AST 检查定时任务装饰器配置，避免引入 NoneBot 运行依赖。
- `docs/exec-plans/index.md`
  - 登记本执行计划。

## 验证

- `python -m unittest tests.test_status_monitor_jobs_config`
- `python -m py_compile src/plugins/status_monitor/jobs.py tests/test_status_monitor_jobs_config.py`

## 风险与回滚

- 风险：如果两次统计重叠，会并发访问外部接口、渲染图片并写入统计快照，资源占用和接口压力会增加。
- 回滚：移除 `max_instances=2` 即恢复 APScheduler 默认同一 job 单实例行为。

## 执行状态

- [x] 计划创建
- [x] 代码实现
- [x] 自动化验证
