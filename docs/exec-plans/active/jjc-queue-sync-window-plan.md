# JJC 队列一次性同步窗口计划

## 背景

当前 JJC 同步模式主要通过 `queue_mode` / worker `mode` 表达 `incremental_or_full`、`incremental`、`full`。这容易把“本次入队要同步多久的数据”误解成 worker 属性或角色长期属性。

目标语义需要收敛为：同步窗口只属于一次入队任务。入队时指定这次任务要从最新战绩往前同步到哪里；以后重新入队时重新指定，和上一次入队无关；worker 只负责消费队列，不携带同步范围配置。

## 目标

1. 去掉对外可选的 `incremental` 同步模式，默认行为改为 full。
2. 增加一次性同步窗口：入队时可指定同步最近 N 天或同步到某个截止时间。
3. 竞技排名自动加入同步队列的角色，只同步最近 7 天。
4. 已同步对局页面加入同步队列的角色，仍执行 full。
5. 同步窗口与 worker 属性解耦，worker 启动参数不包含同步范围。

## 非目标

- 不改变 `full_synced_until_time` 的现有水位字段含义。
- 不迁移历史队列记录。
- 不把同步窗口做成角色长期配置。
- 不改变 worker 并发、租约、优先级排序和全局暂停机制。
- 不重构 JJC 同步整体状态机。

## 核心语义

新增队列字段 `queue_sync_until_time`：

- 类型：`int/null`，Unix 秒。
- 归属：`jjc_sync_identity_queue` 当前队列记录的一次性任务参数。
- `null`：本次入队执行 full，向前同步到赛季开始、接口无更多数据或安全页数上限。
- 非空：本次入队从最新战绩向前同步，遇到 `match_time <= queue_sync_until_time` 时停止。
- 每次入队都必须显式写入该字段：
  - 页面 full 入队写 `null`，清空旧窗口。
  - 排名入队写 `now - 7天`。
  - 手工指定窗口写指定值。
- 同一次任务因租约中断释放回 `queued` 时保留该字段，继续同一入队任务。
- 下次重新入队时覆盖该字段，旧值不影响新任务。

## 业务规则

### 入队来源

| 来源 | 行为 |
|---|---|
| QQ `/jjc同步开始` | 默认 full；支持 `days=N` 或 `until=YYYY-MM-DD` 指定本次窗口 |
| CLI `scripts/jjc_sync.py enqueue` | 默认 full；支持 `--days=N` 或 `--until=YYYY-MM-DD` |
| 排名统计 `ranking_stats` | 固定最近 7 天，写入 `queue_sync_until_time = 当前入队时间 - 7*86400` |
| 已同步对局页面 `synced_match_page` | 固定 full，写入 `queue_sync_until_time = null` |
| 手动添加并立即排队 | 默认 full；后续可复用同一解析逻辑支持窗口参数 |

### 模式处理

- 对外命令只接受 `default` / `full`，`default` 归一为 `full`。
- `incremental` 不再作为对外可选参数。
- 历史队列中已有 `queue_mode=incremental` 或 `incremental_or_full` 不迁移；worker 可兼容处理，避免中断现有队列。
- 新写入的 `queue_mode` 统一为 `full`，真正的同步范围由 `queue_sync_until_time` 决定。

### worker 处理

- worker 启动继续只配置 worker 身份、运行时长、最大处理角色数、idle sleep 等调度参数。
- worker 领取 queued 角色后读取角色队列记录中的 `queue_sync_until_time`。
- `_resolve_stop_time(role, mode)` 优先使用 `queue_sync_until_time`；为空时按 full。
- worker 不从自身参数接收 days/until，也不把窗口写到 worker 心跳。

## 涉及模块

### 存储层

`src/storage/mongo_repos/jjc_sync_repo.py`

- `enqueue_next_roles(...)` 增加参数 `queue_sync_until_time: Optional[int]`。
- `enqueue_identity(...)` 增加参数 `queue_sync_until_time: Optional[int]`。
- `enqueue_role(...)` 增加参数 `queue_sync_until_time: Optional[int]`。
- `enqueue_existing_identity(...)` 增加参数 `queue_sync_until_time: Optional[int]`。
- `enqueue_ranking_member(...)` 增加参数 `queue_sync_until_time: Optional[int]`，默认不在 repo 内部计算具体窗口，由调用方传入。
- 所有入队写操作都 `$set queue_sync_until_time`，即使值为 `None` 也必须写入以清空旧窗口。
- 中断重新排队和租约恢复不改该字段。

### 业务编排层

`src/services/jx3/jjc_match_data_sync.py`

- 新增轻量解析函数：
  - `parse_queue_sync_until_time(value)`：支持 Unix 秒、`YYYY-MM-DD`、`YYYY-MM-DD HH:MM:SS`。
  - `resolve_queue_sync_until_time(days=None, until=None, now=None)`：统一处理 `days` 与 `until`，两者不能同时指定。
- `enqueue_roles(...)` 增加 `queue_sync_until_time` 参数并透传 repo。
- `add_role(..., queue=True)` 增加 `queue_sync_until_time` 参数并透传 repo。
- `run_worker(...)` 默认 mode 改为 `full`，但兼容历史 mode。
- `_resolve_stop_time(...)` 优先读取 `queue_sync_until_time`，否则 full 返回 `None`。
- `sync_single_role(...)` 保持直接 full，不引入窗口，除非后续明确需要。

`src/services/jx3/jjc_ranking.py`

- 排名统计保存后触发入队时计算一次性窗口：
  - `queue_sync_until_time = int(time.time()) - 7 * 86400`
- 调用 `enqueue_ranking_member(..., mode="full", queue_sync_until_time=...)`。

`src/services/jx3/jjc_ranking_inspect.py`

- 页面入队调用 `enqueue_existing_identity(..., mode="full", queue_sync_until_time=None)`。
- 返回给前端的 `sync_status` 可包含 `queue_sync_until_time`，用于诊断展示；页面文案是否展示另行判断。

### 入口层

`src/plugins/jx3bot_handlers/jjc_match_data_sync.py`

- `/jjc同步开始 [default|full] [limit=10] [days=N|until=YYYY-MM-DD]`
- `incremental` 返回参数错误。
- 响应中展示：
  - `模式: full`
  - 有窗口时展示 `同步截止: <timestamp>` 或格式化时间。

`scripts/jjc_sync.py`

- `enqueue --mode=default|full --limit=N [--days=N|--until=YYYY-MM-DD]`
- `worker/start` 不暴露同步模式和窗口参数。
- 保持 worker 只处理队列，不决定同步窗口。

`src/services/jx3/jjc_sync_worker_runtime.py`

- bot 内置 worker 以 `mode="full"` 启动。
- 不新增窗口相关配置。

`src/plugins/config_manager.py`

- 管理帮助移除 `/jjc同步开始 incremental`。
- 增加 `/jjc同步开始 full days=7` 或 `/jjc同步开始 full until=2026-06-08` 示例。

### HTTP API 与页面

`src/api/routers/jjc_ranking_stats.py`

- `POST /api/jjc/ranking-stats/synced-role-sync` 仍不暴露窗口参数，页面入口固定 full。

`src/api/routers/jjc_sync.py`

- 队列列表可继续按 `mode` 过滤；新任务主要显示 `full`。
- 可考虑返回 `queue_sync_until_time` 供队列页面诊断。

`public/jjc-sync-queue.html`

- 若当前页面已有同步类型列，补充展示同步窗口：
  - 空：`full`
  - 非空：`至 <本地时间>`
- 本计划可先只更新 API 返回，不强制改页面展示；若改页面，同步 runbook 回归。

## 数据库与文档

更新 `docs/design-docs/database-design.md`：

- 在 `jjc_sync_identity_queue` 字段表中新增：
  - `queue_sync_until_time`：`int/null`，本次入队同步窗口截止时间；为空表示 full；每次入队覆盖。
  - `queue_window_migrated_at` / `queue_window_migrated_by`：历史队列窗口迁移脚本诊断字段。
- 更新 `queue_mode` 说明：
  - 新写入统一为 `full`，历史值 `incremental_or_full` / `incremental` 仅兼容读取。

新增脚本 `scripts/limit_existing_jjc_queue_to_7d.py`：

- 默认 dry-run，`--apply` 才写入。
- 默认处理 `pending,cooldown,exhausted,failed,queued`。
- 明确拒绝 `syncing` 与 `disabled`。
- 写入 `queue_mode="full"`、`queue_sync_until_time=now-7天`、`queue_window_migrated_at`、`queue_window_migrated_by`。
- 保留 `queued_at`、`queue_batch_id`、`queue_source`、`priority`、租约字段以外的现有调度信息。

更新 `README.md` / `README-Docker.md` / `docs/references/runbook.md`：

- worker 启动示例改为 `python scripts/jjc_sync.py worker`。
- QQ/CLI 入队示例补充 `days=7` / `until=YYYY-MM-DD`。
- 说明 worker 不决定同步窗口。

## 测试计划

### 单测

- `tests/test_jjc_match_data_sync.py`
  - `enqueue_roles()` 透传 `queue_sync_until_time`。
  - `_resolve_stop_time()` 优先使用 `queue_sync_until_time`。
  - `incremental` 对外入队参数被拒绝；历史 queued role 的旧 mode 仍可兼容。
  - 中断重排不清空 `queue_sync_until_time`。

- `tests/test_jjc_sync_worker_queue.py`
  - `enqueue_next_roles()` 写入窗口。
  - `enqueue_role()` / `enqueue_identity()` 传 `None` 时会清空旧窗口。
  - `enqueue_existing_identity()` 页面入队写 `None`。
  - `enqueue_ranking_member()` 透传最近 7 天窗口。

- `tests/test_jjc_ranking_stats_repo.py` 或 `tests/test_jjc_ranking.py`
  - 排名统计触发入队时传 `queue_sync_until_time`，值约为入队时刻减 7 天。

- `tests/test_jjc_ranking_inspect.py`
  - 页面入队传 `mode="full"` 与 `queue_sync_until_time=None`。

- `tests/test_jjc_match_data_sync_handler.py`
  - `/jjc同步开始` 默认 full。
  - `/jjc同步开始 full days=7` 解析窗口。
  - `/jjc同步开始 incremental` 报错。

- `tests/test_jjc_sync_cli.py`
  - `enqueue --days 7` 透传窗口。
  - `worker/start` 不暴露 `--mode` 参数。

- `tests/test_limit_existing_jjc_queue_to_7d.py`
  - 覆盖脚本查询、更新和状态保护。

### 编译

```bash
python -m py_compile \
  src/services/jx3/jjc_match_data_sync.py \
  src/storage/mongo_repos/jjc_sync_repo.py \
  src/services/jx3/jjc_ranking.py \
  src/services/jx3/jjc_ranking_inspect.py \
  src/plugins/jx3bot_handlers/jjc_match_data_sync.py \
  src/services/jx3/jjc_sync_worker_runtime.py \
  scripts/jjc_sync.py
```

### 回归命令

```bash
python -m unittest \
  tests.test_jjc_match_data_sync \
  tests.test_jjc_sync_worker_queue \
  tests.test_jjc_sync_repo \
  tests.test_jjc_ranking_inspect \
  tests.test_jjc_ranking_stats_repo \
  tests.test_jjc_match_data_sync_handler \
  tests.test_jjc_sync_cli \
  tests.test_jjc_sync_worker_runtime \
  tests.test_limit_existing_jjc_queue_to_7d
```

## 手工验证

1. 启动 worker：`python scripts/jjc_sync.py worker`。
2. 手动入队 full：`/jjc同步开始 full limit=1`，确认队列记录 `queue_sync_until_time=null`。
3. 手动入队最近 7 天：`/jjc同步开始 full days=7 limit=1`，确认队列记录有截止时间，worker 遇到边界停止。
4. 排名统计后检查 `queue_source=ranking_stats` 的队列记录，确认窗口为最近 7 天。
5. 页面点击加入同步队列，确认 `queue_source=synced_match_page` 且 `queue_sync_until_time=null`，不会沿用旧窗口。
6. 执行历史队列 dry-run：`python scripts/limit_existing_jjc_queue_to_7d.py`，确认目标状态不含 `syncing/disabled`。
7. 确认样例无误后执行：`python scripts/limit_existing_jjc_queue_to_7d.py --apply`。

## 风险与回滚

### 风险

- 如果某条队列记录历史残留了窗口，页面或手动 full 入队必须能清空，否则会误同步短窗口。
- 旧队列中 `queue_mode=incremental` 仍存在，worker 需要兼容处理，避免部署后已有 queued 任务失败。
- 排名统计使用入队时刻计算 7 天，和统计快照 timestamp 可能存在轻微差异；建议使用 `time.time()`，表达“从当前同步队列入队时回看 7 天”。

### 回滚

- 回滚业务代码后，`queue_sync_until_time` 字段不再被读取；字段可留在 Mongo 中。
- 若需要快速止血，仅将 worker `_resolve_stop_time()` 中读取 `queue_sync_until_time` 的逻辑回滚，即可恢复旧 full/incremental 行为。
- 文档回滚包括 README/runbook/database-design 中新增字段和命令示例。

## 执行状态

- 2026-06-15：已完成阶段 1 计划。
- 2026-06-15：已新增历史队列 7 天窗口脚本、脚本单测和数据库字段说明。
- 2026-06-15：已实现一次性队列窗口业务代码：新入队默认 full，QQ/CLI 支持 `days` / `until`，排名入队固定最近 7 天，页面入队清空窗口，worker 只读取队列记录。
- 2026-06-15：已验证目标单测、py_compile 和队列页面内联 JS 语法检查；待提交前最终 review。
- 2026-06-15：已完成自查 review，重点确认新入队路径显式写入/清空 `queue_sync_until_time`、worker 不携带窗口参数、历史 `incremental` 队列仍兼容读取。
