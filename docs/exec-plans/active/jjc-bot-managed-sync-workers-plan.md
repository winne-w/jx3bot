# JJC bot 启动托管同步 worker 计划

状态：方案待确认
更新时间：2026-05-29

## 背景

当前 JJC 对局同步已经拆成“入队”和“worker 领取处理”两部分。QQ 命令 `/jjc同步开始` 只负责把角色放入 `queued` 队列，实际处理依赖单独执行 `python scripts/jjc_sync.py worker --mode=incremental_or_full` 或兼容命令 `python scripts/jjc_sync.py start ...`。

这种方式适合独立扩容和排障，但部署时需要额外维护 worker 进程。希望支持 bot 启动时根据配置自动拉起固定数量的 JJC 同步 worker，让单容器或单进程部署可以只启动 `python bot.py`，由 bot 进程内托管同步 worker。

## 目标

- 新增可配置的 bot 内置 JJC 同步 worker，默认关闭，保持当前部署行为不变。
- bot 启动并完成 Mongo 初始化后，按配置数量创建后台 worker task。
- bot 关闭时取消这些 worker task，并让现有 `run_worker()` 走停止心跳逻辑。
- 保留 `scripts/jjc_sync.py worker/start` 独立 worker 模式，用于单独扩容、临时排障和不希望与 bot 共进程的部署。
- 状态页、QQ `/jjc同步状态`、HTTP `/api/jjc/sync/workers` 继续通过 `jjc_sync_workers` 心跳识别 worker，不区分内置或外置也能展示。
- 保持 Python 3.9 类型注解兼容。

## 非目标

- 不修改 JJC 队列领取、租约、暂停、鉴权自动暂停、对局详情同步和水位推进规则。
- 不引入新的进程管理器、消息队列或调度系统。
- 不把内置 worker 作为唯一启动方式；独立 CLI worker 继续可用。
- 不新增 HTTP 启动/停止 worker 的写接口，避免远程接口误触发同步执行。
- 不在首版做动态调整 worker 数量；配置变更通过重启 bot 生效。

## 配置设计

新增配置项放在 `config.py`，默认关闭。配置来源按现有项目习惯分三层：

1. `config.py` 默认值。
2. 环境变量覆盖，方便容器部署。
3. `runtime_config.json` 覆盖，支持管理员通过 `/修改配置 配置项=值` 写入并自动重启后生效。

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `JJC_SYNC_WORKER_COUNT` | `0` | bot 启动时内置 worker 数量，`0` 表示不启动 |
| `JJC_SYNC_WORKER_MODE` | `incremental_or_full` | worker 默认同步模式，只允许 `incremental_or_full`、`full`、`incremental` |
| `JJC_SYNC_WORKER_IDLE_SLEEP` | `10` | 空闲或暂停时 sleep 秒数，最小建议 `1` |
| `JJC_SYNC_WORKER_MAX_SECONDS` | `0` | 单个 worker 最长运行秒数，`0` 表示不限时；生产默认不限时 |
| `JJC_SYNC_WORKER_MAX_ROLES` | `0` | 单个 worker 最多处理角色数，`0` 表示不限数量；生产默认不限数量 |

`config.py` 中的默认写法：

```python
JJC_SYNC_WORKER_COUNT = 0
JJC_SYNC_WORKER_MODE = "incremental_or_full"
JJC_SYNC_WORKER_IDLE_SLEEP = 10
JJC_SYNC_WORKER_MAX_SECONDS = 0
JJC_SYNC_WORKER_MAX_ROLES = 0
```

为了保留容器和线上部署的灵活性，实现时可以先用环境变量覆盖这些默认值，例如：

```python
JJC_SYNC_WORKER_COUNT = int(os.getenv("JJC_SYNC_WORKER_COUNT", JJC_SYNC_WORKER_COUNT))
JJC_SYNC_WORKER_MODE = os.getenv("JJC_SYNC_WORKER_MODE", JJC_SYNC_WORKER_MODE)
JJC_SYNC_WORKER_IDLE_SLEEP = int(os.getenv("JJC_SYNC_WORKER_IDLE_SLEEP", JJC_SYNC_WORKER_IDLE_SLEEP))
JJC_SYNC_WORKER_MAX_SECONDS = int(os.getenv("JJC_SYNC_WORKER_MAX_SECONDS", JJC_SYNC_WORKER_MAX_SECONDS))
JJC_SYNC_WORKER_MAX_ROLES = int(os.getenv("JJC_SYNC_WORKER_MAX_ROLES", JJC_SYNC_WORKER_MAX_ROLES))
```

随后把 worker 配置项加入 `RUNTIME_CONFIG_KEYS`，让 `runtime_config.json` 可以覆盖最终值：

```python
RUNTIME_CONFIG_KEYS = {
    ...
    "JJC_SYNC_WORKER_COUNT": int,
    "JJC_SYNC_WORKER_MODE": str,
    "JJC_SYNC_WORKER_IDLE_SLEEP": int,
    "JJC_SYNC_WORKER_MAX_SECONDS": int,
    "JJC_SYNC_WORKER_MAX_ROLES": int,
}
```

`/修改配置` 写入后现有逻辑会自动重启 bot，因此这些启动期配置不需要热更新。需要在回复文案和 runbook 中明确：worker 数量和运行参数修改后通过自动重启生效，不在当前进程中动态增减 task。

启动一个内置 worker 的配置方式：

```python
JJC_SYNC_WORKER_COUNT = 1
```

或管理员命令：

```text
/修改配置 JJC_SYNC_WORKER_COUNT=1
```

## 启停设计

新增一个轻量生命周期模块，例如 `src/services/jx3/jjc_sync_worker_runtime.py`，职责只管理 bot 进程内 task：

- 读取已解析配置。
- 校验配置合法性。
- 在 startup 中创建 N 个 `asyncio.Task`。
- 为每个 task 生成稳定可识别的 `worker_id`，建议格式：
  - `bot:{host}:{pid}:{index}`
  - 如担心同一进程重复 startup，可追加短 uuid：`bot:{host}:{pid}:{index}:{suffix}`
- task 内调用现有 `jjc_match_data_sync_service.run_worker(...)`。
- shutdown 时取消所有未完成 task，`await asyncio.gather(..., return_exceptions=True)` 等待收尾。
- 记录启动失败和 worker 异常日志，不让单个 worker 异常直接终止 bot 主进程。

`bot.py` 的 startup 顺序需要保证：

1. 先 `init_mongo(MONGO_URI)`，确保索引和 Mongo 客户端可用。
2. 再启动内置 JJC worker。

shutdown 顺序：

1. 先取消内置 JJC worker。
2. 让 `run_worker()` 的 `CancelledError` 分支写入 `stopped/cancelled`。
3. 不额外清理 Mongo 队列租约；异常退出仍依赖既有 lease 过期恢复。

## 模块与文件落位

- `config.py`
  - 新增上述 5 个配置项。
  - 默认值保持内置 worker 关闭；使用者可以直接改 `config.py`，环境变量覆盖仅作为部署可选能力。
  - 将 5 个配置项加入 `RUNTIME_CONFIG_KEYS`，支持 `runtime_config.json` 覆盖。
- `src/plugins/config_manager.py`
  - `/修改配置` 的 `allowed_keys` 增加 5 个 worker 配置项。
  - `/查看配置` 展示这 5 个 worker 配置项，便于确认当前运行时配置文件中的值。
  - 整数项按 int 校验；`JJC_SYNC_WORKER_MODE` 按枚举校验，只允许 `incremental_or_full`、`full`、`incremental`。
  - 修改成功后沿用现有自动重启流程，使启动期配置在重启后生效。
- `bot.py`
  - 在现有 `_startup_mongo()` 中完成 Mongo 初始化后调用 worker runtime 的启动函数。
  - 新增 `driver.on_shutdown` 回调调用停止函数。
  - 不在 `bot.py` 中直接写 worker 管理细节，避免入口文件继续膨胀。
- `src/services/jx3/jjc_sync_worker_runtime.py`
  - 新增内置 worker 生命周期管理。
  - 只依赖 `config.py`、`jjc_match_data_sync_service` 和标准库 `asyncio/socket/os/uuid`。
  - 不写 JJC 同步业务规则。
- `src/services/jx3/jjc_match_data_sync.py`
  - 原则上不改业务逻辑。
  - 仅当发现 `run_worker()` 对取消/停止结果不满足 bot 托管场景时，做小范围兼容修正。
- `README.md`
  - 增加内置 worker 配置说明、默认关闭说明和 `/修改配置 JJC_SYNC_WORKER_COUNT=1` 示例。
- `README-Docker.md`
  - 说明同一容器可以通过 `config.py`、`runtime_config.json` 或环境变量配置 `JJC_SYNC_WORKER_COUNT=1` 随 bot 启动 worker；如使用环境变量覆盖，再补充 compose 示例。
- `docs/references/runbook.md`
  - 更新 JJC 同步运维说明：独立 worker 和 bot 内置 worker 两种模式。
  - 增加 `/修改配置` 设置 worker 数量、重启、扩容、修改 ticket、观察状态的注意事项。
- `docs/exec-plans/index.md`
  - 将本计划加入 Active。

## 行为规则

- `JJC_SYNC_WORKER_COUNT <= 0`：不启动任何内置 worker，完全维持当前行为。
- `JJC_SYNC_WORKER_COUNT > 0`：
  - 每个 bot 进程启动对应数量 worker。
  - 多 bot 实例部署时，总 worker 数等于所有实例配置数量之和。
  - 多 worker 并发安全继续依赖 Mongo `lease_owner/lease_expires_at`。
- 配置非法时：
  - `mode` 非法：记录错误并不启动内置 worker，避免启动后立即失败循环。
  - `idle_sleep < 1`：记录错误并不启动，或规范化为 `1`；首选不启动并暴露日志，避免静默纠正造成误解。
  - `max_seconds/max_roles < 0`：记录错误并不启动。
- `/修改配置` 层尽量提前拦截非法值，避免把无效配置写入 `runtime_config.json`；启动期 runtime 仍保留二次校验，防止手工编辑配置文件导致异常启动。
- bot 托管 worker 与 CLI worker 可以同时存在；只要 worker 总量控制合理，Mongo 租约能避免重复领取。
- QQ `/jjc同步暂停` 仍是软暂停，内置 worker 和外置 worker 都会在下一个 tick 进入 paused。

## 风险与约束

- 内置 worker 与 QQ 消息处理、HTTP API 共享同一个 Python 进程和事件循环。worker 数量过大时，推栏请求、详情保存和日志输出可能影响 bot 响应。
- 如果容器/进程被强杀，shutdown 回调不会执行；旧心跳会在现有 5 分钟在线判定后失效，角色租约按已有过期恢复机制处理。
- 如果线上同时保留 systemd/supervisor/手工 CLI worker，又配置了内置 worker，总 worker 数可能超过预期，需要在 runbook 中明确统计口径。
- 默认关闭是必要兼容要求，避免部署升级后无意开始同步。

## 验证方案

自动化验证：

```bash
python -m py_compile bot.py config.py src/services/jx3/jjc_sync_worker_runtime.py
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_worker_queue
```

建议新增测试：

- `tests/test_jjc_sync_worker_runtime.py`
  - `JJC_SYNC_WORKER_COUNT=0` 时不创建 task。
  - `JJC_SYNC_WORKER_COUNT=2` 时创建两个 task，并传入不同 `worker_id`。
  - shutdown 会 cancel task 并等待收尾。
  - 非法 mode/idle/max 参数不启动 worker。
- `tests/test_config_manager.py` 或现有配置命令测试：
  - `/修改配置 JJC_SYNC_WORKER_COUNT=1` 能写入 `runtime_config.json` 并触发重启流程。
  - `/修改配置 JJC_SYNC_WORKER_MODE=bad` 会被拒绝。
  - `/查看配置` 会展示 worker 配置项。

手工回归：

1. 默认配置启动 `python bot.py`，确认 `/jjc同步状态` 显示无活跃 worker。
2. 设置 `JJC_SYNC_WORKER_COUNT=1` 启动 `python bot.py`，或执行 `/修改配置 JJC_SYNC_WORKER_COUNT=1` 等待自动重启，确认 `/api/jjc/sync/workers` 和 `/jjc同步状态` 能看到 `bot:` 前缀 worker。
3. 执行 `/jjc同步开始 limit=1`，确认角色进入 queued 后被内置 worker 领取。
4. 执行 `/jjc同步暂停 测试`，确认 worker 进入 paused；再 `/jjc同步恢复`，确认继续领取。
5. 停止 bot，确认 worker 心跳写入 stopped 或在 5 分钟内自然失效，未完成角色可由下一次启动恢复。

## 回滚方案

- 将 `JJC_SYNC_WORKER_COUNT` 设置为 `0` 并重启 bot，即可关闭内置 worker；如果通过管理员命令操作，执行 `/修改配置 JJC_SYNC_WORKER_COUNT=0`。
- 如需代码级回滚，删除 `config.py` 新增配置、`bot.py` lifecycle 调用、新增 runtime 模块，并回滚 README/runbook 说明。
- 独立 CLI worker 模式不受影响，回滚后继续使用：

```bash
python scripts/jjc_sync.py worker --mode=incremental_or_full
```

## 实施步骤

1. 新增配置项，默认关闭，并加入 `RUNTIME_CONFIG_KEYS`。
2. 新增 `jjc_sync_worker_runtime`，实现 startup/shutdown task 管理。
3. 在 `bot.py` Mongo 初始化后接入 startup，在 shutdown 接入停止。
4. 扩展 `/修改配置`、`/查看配置` 支持 worker 配置项和参数校验。
5. 补单元测试和 py_compile 验证。
6. 更新 README、README-Docker、runbook。
7. 完成后在本计划记录执行结果；代码未提交前计划留在 active。
