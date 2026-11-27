# 定时任务去重缓存、配置生效与断线漏推修复计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

继开服通知延迟修复（PR #19）后，对全仓全部 12 个 APScheduler 定时任务进行同类漏洞审计，修复发现的 4 类问题：
1. `push_daily_gte` 在群推送循环内对绑定同一区服的多个群重复请求日常接口，且 `hour=9` 硬编码导致 `calendar_time` 配置项未生效。
2. `check_price_alerts` 在订阅循环内对同一外观名重复请求万宝楼接口，且缺少 `id` / `replace_existing` / `max_instances=1`。
3. `check_records` / `check_news` / `check_event_codes` 在 QQ 断线（`get_driver().bots` 为空）时跳过群推送，但仍推进并持久化 ID 水位，导致重连后漏推。
4. 部分定时任务未显式声明 `max_instances=1`。

## Progress

- [x] 全仓定时任务审计与方案确认
- [x] 基于 `origin/main`（`3e5597f`）建立独立 worktree 与分支 `fix/scheduled-jobs-hardening`
- [x] 修改 `src/plugins/status_monitor/jobs.py`、`src/plugins/wanbaolou/__init__.py`、`src/plugins/wanbaolou/alias.py`
- [x] 补充并运行单元测试与 Python 3.9 `py_compile` 校验
- [x] 独立子 Agent 静态代码 Review（结论 PASS）并闭环全部 4 条 Low 级优化建议
- [x] 归档本计划至 `docs/exec-plans/completed/` 并更新索引

## Surprises & Discoveries

- `check_event_codes` 中会过滤 `status == 0` 的无效活动码；若当次新增条目全部为无效活动码，即使 QQ 断线也无需补推，可直接推进缓存水位，仅当存在有效待推送活动码且 QQ 断线时才暂缓推进。
- 独立 Review 发现 `_resolve_daily_gte_hour` 应额外排除 `float` 类型防止如 `9.5` 被静默截断，已补充拒绝 `float` 与单测断言。

## Decision Log

- **单文件执行计划**：本次仅改动 3 个插件文件及单元测试，不涉及数据库集合/字段、API 路由或前端页面，按 `PROJECT_CONTEXT.md` 与 `docs/PLANS.md` 使用 `docs/exec-plans/` 单文件计划。
- **QQ 在线但个别群发送失败的语义**：保持原语义仍推进 ID 水位，避免因单个无效群导致所有其他正常群在后续轮询中被反复刷屏。
- **`calendar_time` 校验**：对 `calendar_time` 做 `0 <= int(val) <= 23`（排除 `bool` 与 `float`）校验，非法值记录 warning 并回退默认 `9`。

## Outcomes & Retrospective

- 3 个生产插件文件及 3 个测试文件均通过 Python 3.9 `py_compile` 校验。
- 6 组单元测试（`test_status_monitor_jobs_config`、`test_status_monitor_check_status`、`test_status_monitor_scheduled_jobs`、`test_status_monitor_jobs_admin_notification`、`test_wanbaolou_price_alerts`、`test_p5_browser_pool_and_wanbaolou`）全部 33 项通过。
- 独立只读静态代码复审结论 **PASS**（0 Critical / 0 High / 0 Medium），4 条 Low 级建议已全部整改并复测通过。

## Context and Orientation

- `src/plugins/status_monitor/jobs.py`：包含 `check_records`、`check_news`、`check_event_codes`、`push_daily_gte` 等定时任务。
- `src/plugins/wanbaolou/__init__.py`：包含 `check_price_alerts` 及其 `init_subscription_system` 注册逻辑。
- `src/plugins/wanbaolou/alias.py`：包含 `setup_alias_refresh_job` 定时刷新别名缓存任务。

## Validation and Acceptance

```bash
cd /mnt/d/document/codes/jx3bot-workspace/_worktrees/scheduled-jobs-hardening
/mnt/d/document/codes/jx3bot-workspace/_envs/py39/bin/python -m py_compile \
  src/plugins/status_monitor/jobs.py \
  src/plugins/wanbaolou/__init__.py \
  src/plugins/wanbaolou/alias.py \
  tests/test_status_monitor_jobs_config.py \
  tests/test_status_monitor_scheduled_jobs.py \
  tests/test_wanbaolou_price_alerts.py
/mnt/d/document/codes/jx3bot-workspace/_envs/py39/bin/python -m unittest \
  tests.test_status_monitor_jobs_config \
  tests.test_status_monitor_check_status \
  tests.test_status_monitor_scheduled_jobs \
  tests.test_status_monitor_jobs_admin_notification \
  tests.test_wanbaolou_price_alerts \
  tests.test_p5_browser_pool_and_wanbaolou
```
