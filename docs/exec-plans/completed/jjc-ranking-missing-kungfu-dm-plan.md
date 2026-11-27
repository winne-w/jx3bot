# JJC 排名定时任务缺失心法名单改私聊管理员计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

每日 03:00 / 21:00 定时任务 `push_daily_jjc_ranking` 完成战绩排名统计后，原本会向每个开启推送的群发送 3 类消息：1. 统计图片、2. 统计概括、3. 未查询到心法的角色名单。本次调整将第 3 类消息从群聊推送移除，改为仅私聊发送给 `config.ADMIN_QQ` 中的管理员，避免打扰普通群成员，同时保留管理员排查未识别角色的入口。

## Progress

- [x] 核查仓库 `origin/main` 基线与生产 `jobs.py` 哈希，建立独立干净工作树 `fix/jjc-ranking-missing-kungfu-dm`
- [x] 编写小改动执行计划并登记到 `docs/exec-plans/index.md`
- [x] 在 `src/plugins/status_monitor/jobs.py` 实现缺失心法名单私聊管理员逻辑并移除群聊发送
- [x] 在 `tests/test_status_monitor_jobs_admin_notification.py` 补充单元测试并通过 Python 3.9 编译与单测
- [x] 完成首轮独立 Code Review（发现 4 项 P1 + 4 项 P2）
- [x] 根据首轮 Review 意见完成代码与测试修正并通过 38 项定向单测与 Python 3.9 编译校验
- [x] 完成第二轮独立复评（8/8 闭环，Approve）
- [x] 归档计划至 `docs/exec-plans/completed/` 并更新索引
- [ ] 提交 Git commit、备份生产文件并发布到生产容器验收

## Surprises & Discoveries

- 原 `_worktrees/unify-visual-style` 工作树停留在较早提交且包含其他未提交改动；已还原误写片段并基于最新 `origin/main` (`9ef8203`) 新建干净工作树 `_worktrees/jjc-ranking-missing-kungfu-dm`。
- 生产环境 `/mnt/sata6-1/jx3bot/src/plugins/status_monitor/jobs.py` 与 `origin/main` 功能完全一致（仅两处行尾空格差异）。

## Decision Log

- 仅修改定时任务 `push_daily_jjc_ranking`，不改动手动命令 `竞技排名` 的既有回复行为。
- 新增 `_get_admin_qq_list()` 规范化并保序去重 `config.ADMIN_QQ`，统一供 `notify_jjc_ranking_failure` 与 `notify_jjc_ranking_missing_kungfu` 复用。
- 缺失心法名单私聊逻辑移出群推送循环，确保每轮任务每位管理员只收到一次（多群不重复），并在消息头增加 `【每日竞技排名定时任务（{week_info}）】` 上下文。
- 无开启推送群组或图片渲染失败时，只要本轮存在 `missing_kungfu_lines` 且 QQ 已连接，仍向管理员私聊缺失名单，避免排查信息静默丢失。
- 保留每 100 条分片，仅在仍有后续分片或后续管理员时 `asyncio.sleep(0.5)`，避免最后一条私聊后的多余等待；单个管理员失败记录分片序号 warning 并继续通知其他管理员。

## Outcomes & Retrospective

已完成实现、两轮独立 Code Review 与 38 项 Python 3.9 自动化验证。回滚仅需恢复 `src/plugins/status_monitor/jobs.py` 备份并重启 `jx3bot` 容器。

## Context and Orientation

- `src/plugins/status_monitor/jobs.py`：承载 `push_daily_jjc_ranking` 定时任务、`_get_admin_qq_list()`、`notify_jjc_ranking_failure` 与 `notify_jjc_ranking_missing_kungfu`。
- `tests/test_status_monitor_jobs_admin_notification.py`：通过 stub 隔离 NoneBot / Mongo / 渲染依赖，覆盖管理员通知与定时推送边界路径。
- `docs/exec-plans/index.md`：执行计划索引。

## Plan of Work

1. 在 `src/plugins/status_monitor/jobs.py` 新增 `_get_admin_qq_list()` 与 `notify_jjc_ranking_missing_kungfu(bot, missing_kungfu_lines, week_info=None)`。
2. 在 `push_daily_jjc_ranking` 中，群推送循环仅发送图片与统计概括两条消息；在循环结束后（以及无目标群或渲染失败返回前）若 `missing_kungfu_lines` 非空则私聊管理员。
3. 在 `tests/test_status_monitor_jobs_admin_notification.py` 补齐多群不重复、分片与单管理员失败容错、无订阅群/渲染失败/群发送失败、空/`None` 缺失名单、`bot=None` 与 `ADMIN_QQ` 边界单测。
4. 完成两轮独立 Review、归档计划、提交 Git、备份并发布至生产容器验收。

## Concrete Steps

1. 编辑 `src/plugins/status_monitor/jobs.py` 与 `tests/test_status_monitor_jobs_admin_notification.py`。
2. 运行 Python 3.9 校验与定向单测：
   ```bash
   python -m py_compile src/plugins/status_monitor/jobs.py tests/test_status_monitor_jobs_admin_notification.py
   python -m unittest -v tests.test_status_monitor_jobs_admin_notification tests.test_status_monitor_jobs_config tests.test_jjc_ranking_force_sync tests.test_jjc_ranking_equipment_generation
   ```
3. 执行 Round 1 Review -> 修正 -> Round 2 复评 -> 归档计划 -> `git diff --check` -> commit -> 生产备份与发布验收。

## Validation and Acceptance

### 验证记录

- `_envs/py39/bin/python -m py_compile src/plugins/status_monitor/jobs.py tests/test_status_monitor_jobs_admin_notification.py`：通过。
- `_envs/py39/bin/python -m unittest -v tests.test_status_monitor_jobs_admin_notification tests.test_status_monitor_jobs_config tests.test_jjc_ranking_force_sync tests.test_jjc_ranking_equipment_generation`：38 项全部通过（含新增 6 个边界测试方法）。

### Review 记录

- **Round 1 独立 Review**：无 P0；发现 4 项 P1（单测直接篡改全局 `asyncio.sleep`、渲染失败分支遗漏缺失心法私聊、`ADMIN_QQ` 边界配置缺少规范化去重、空名单/边界用例缺口）与 4 项 P2（私聊缺少周次来源前缀、尾部多余 `sleep(0.5)`、日志可观测性、计划进度同步）。已全部修复。
- **Round 2 独立复评**：结论 **Approve**，8/8 项全部闭环，未发现新的 P0/P1/P2 问题，Python 3.9 兼容性核对通过。
