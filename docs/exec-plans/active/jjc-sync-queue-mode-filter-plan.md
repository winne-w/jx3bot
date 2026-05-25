# JJC 同步队列页面增加同步模式筛选计划

## 背景

`/public/jjc-sync-queue.html` 当前支持按队列状态、服务器、角色名和分页大小筛选。队列数据中已有 `queue_mode` 字段，表示入队时的同步模式：`incremental_or_full`、`incremental`、`full`。页面缺少按该同步模式查看队列的入口。

## 目标

- 在 JJC 同步队列页面筛选区新增“同步类型”筛选项。
- 队列 API `/api/jjc/sync/queue` 新增可选 query 参数 `mode`，过滤 `jjc_sync_role_queue.queue_mode`。
- 页面请求队列数据时带上 `mode`，表格展示同步类型，便于确认每条队列记录的同步策略。

## 非目标

- 不修改同步执行逻辑、worker 领取逻辑和入队策略。
- 不新增 MongoDB 字段、集合、索引或迁移脚本。
- 不改变现有 `status` 队列状态筛选语义。

## 涉及文件

- `public/jjc-sync-queue.html`
  - 新增同步类型下拉框。
  - 前端状态新增 `mode`，拼接到队列 API URL。
  - 表格增加同步类型列，并对 `queue_mode` 展示中文标签。
- `src/api/routers/jjc_sync.py`
  - `/queue` 增加 `mode: Optional[str]` query 参数并传给 service。
- `src/services/jx3/jjc_match_data_sync.py`
  - `list_queue()` 增加 `mode` 参数并传给 repo。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - `list_queue()` 增加 `mode` 参数，存在时查询 `queue_mode`。
- `tests/test_jjc_sync_router.py`
  - 覆盖 mode 参数 trim 和透传。
- `README.md`
  - 同步接口说明中的 queue 示例补充 `mode`。
- `docs/exec-plans/index.md`
  - 登记本执行计划。

## 验证

- `python -m unittest tests.test_jjc_sync_router`
- `python -m py_compile src/api/routers/jjc_sync.py src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py`
- 手工回归：打开 `/public/jjc-sync-queue.html`，选择“同步类型”，确认请求 URL 包含 `mode` 且列表按 `queue_mode` 过滤。

## 风险与回滚

- 风险：历史记录 `queue_mode` 为空时，选择具体同步类型不会展示这类记录；“全部”仍展示全部记录。
- 回滚：移除页面下拉框、API/service/repo 的 `mode` 参数和 README 说明即可恢复原行为。

## 执行状态

- 2026-05-25：计划创建。
- 2026-05-25：已实现 API/service/repo 的 `mode` 参数透传和 `queue_mode` 查询；已实现页面筛选项与表格同步类型列；已同步 README。
- 2026-05-25：已通过 `python -m unittest tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router` 和相关 `py_compile` 验证。
- 2026-05-25：已完成两轮子 agent review/fix 闭环；第一轮仅提出测试职责隔离建议并已修复，第二轮 review 返回 `NO FINDINGS`。
