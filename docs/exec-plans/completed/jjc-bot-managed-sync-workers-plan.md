# JJC bot 启动托管同步 worker 计划

状态：已实现并通过本地自动验证，待提交
更新时间：2026-06-04

## 背景

当前 JJC 对局同步已经拆成“入队”和“worker 领取处理”两部分。QQ 命令 `/jjc同步开始` 只负责把角色放入 `queued` 队列，实际处理依赖单独执行 `python scripts/jjc_sync.py worker --mode=incremental_or_full` 或兼容命令 `python scripts/jjc_sync.py start ...`。

这种方式适合独立扩容和排障，但部署时需要额外维护 worker 进程。希望支持 bot 启动时根据配置自动拉起固定数量的 JJC 同步 worker，让单容器或单进程部署可以只启动 `python bot.py`，由 bot 进程内托管同步 worker。

## 目标

- 新增可配置的 bot 内置 JJC 同步 worker，默认关闭，保持当前部署行为不变。
- bot 启动并完成 Mongo 初始化后，按配置数量创建后台 worker task。
- bot 正常关闭时取消这些 worker task，并让现有 `run_worker()` 走停止心跳逻辑。
- 保留 `scripts/jjc_sync.py worker/start` 独立 worker 模式，用于单独扩容、临时排障和不希望与 bot 共进程的部署。
- 状态页、QQ `/jjc同步状态`、HTTP `/api/jjc/sync/workers` 继续通过 `jjc_sync_workers` 心跳识别 worker，不区分内置或外置也能展示。
- 内置 worker 使用稳定槽位 ID，避免 bot 每次重启都新增一批离线历史 worker。
- 明确运行时配置文件的敏感信息保护边界，避免为启用 worker 扩大 `runtime_config.json` 的误提交风险。
- 保持 Python 3.9 类型注解兼容。

## 非目标

- 不修改 JJC 队列领取、租约、暂停、鉴权自动暂停、对局详情同步和水位推进规则。
- 不引入新的进程管理器、消息队列或调度系统。
- 不把内置 worker 作为唯一启动方式；独立 CLI worker 继续可用。
- 不新增 HTTP 启动/停止 worker 的写接口，避免远程接口误触发同步执行。
- 不在首版做动态调整 worker 数量；配置变更通过重启 bot 生效。
- 不在本计划中重构整个 `/修改配置` 重启机制；但需要识别当前 `os._exit(0)` 重启路径无法保证 shutdown 回调执行，并在实现与 runbook 中如实说明。

## 前置安全要求

在实现 worker 数量配置前，必须先处理 `runtime_config.json` 的提交风险：

- `runtime_config.json` 会存放 `TOKEN`、`TICKET`、`MONGO_URI` 以及后续 worker 启动配置，不应提交到 Git。
- 当前 `runtime_config.json` 已被 Git 跟踪时，只补 `.gitignore` 不会生效；实现前必须先执行 `git rm --cached runtime_config.json`，保留本地文件但从索引移除。
- 将 `runtime_config.json` 加入 `.gitignore`，或建立等价的提交前保护策略，防止后续真实凭证和运行态配置再次进入提交范围。
- 验证必须包含 `git ls-files runtime_config.json`，期望无输出；如果项目采用等价保护机制，也必须在验证记录中说明原因和结果。
- 必须新增不含敏感值的模板文件 `runtime_config.example.json`（确定交付物），不要把真实 token、ticket、线上 Mongo URI 写入文档或模板。README 和 runbook 中需要说明从模板复制创建 `runtime_config.json` 的步骤。
- `/查看配置` 不得明文展示敏感字段值。当前及未来敏感字段包括 `TOKEN`、`TICKET`、`MONGO_URI` 等，只展示「已配置」或脱敏形式（如 `MON***`、`TOK***`），不展示完整值。非敏感字段（如 `JJC_SYNC_WORKER_COUNT`）可以展示完整值。脱敏规则以字段是否标记为敏感为准，不依赖字段名正则匹配。

## 配置设计

新增配置项放在 `config.py`，默认关闭。配置来源按现有项目习惯分三层：

1. `config.py` 默认值。
2. 环境变量覆盖，方便容器部署。
3. `runtime_config.json` 覆盖，支持管理员通过 `/修改配置 配置项=值` 写入并自动重启后生效。

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `JJC_SYNC_WORKER_COUNT` | `0` | bot 启动时内置 worker 数量，`0` 表示不启动 |

`config.py` 中的默认写法：

```python
JJC_SYNC_WORKER_COUNT = 0
```

首版不暴露 worker mode、idle sleep、max seconds、max roles 配置。内置 worker 固定调用 `run_worker(mode="incremental_or_full")`，理由：该 mode 逻辑为无历史记录时走 full 拉取，有历史记录时走 incremental 增量更新，覆盖首次启动和日常同步两种场景，无需在首版暴露 mode 选择。其余参数沿用 `run_worker()` 默认值：

- `idle_sleep=10`
- `max_seconds=0` —— 内置 worker 是长期驻留后台任务，不应按运行时长上限退出
- `max_roles=None`
- `stop_when_idle=False` —— 内置 worker 作为长期驻留后台任务，队列空闲时应继续轮询等待新角色入队，不应自动退出

这样 `/修改配置` 只需要控制是否启用以及启动几个 worker，避免首版配置面过大。独立 CLI worker 仍可通过命令行参数指定 mode、max seconds、max roles，用于临时排障或一次性同步。

为了保留容器和线上部署的灵活性，实现时可以用环境变量覆盖 `JJC_SYNC_WORKER_COUNT`。环境变量解析必须容错，不能因为非法字符串导致 `config.py` import 失败；建议新增小工具函数：

```python
def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


JJC_SYNC_WORKER_COUNT = _env_int("JJC_SYNC_WORKER_COUNT", 0)
```

随后把 worker 数量配置加入 `RUNTIME_CONFIG_KEYS`，让 `runtime_config.json` 可以覆盖最终值：

```python
RUNTIME_CONFIG_KEYS = {
    ...
    "JJC_SYNC_WORKER_COUNT": int,
}
```

`/修改配置` 写入后现有逻辑会调用 `os._exit(0)` 退出 bot 进程。**自动重启依赖外部进程守护**（如 Docker 的 `restart: unless-stopped`/`always`、systemd 的 `Restart=always`、supervisor 的 `autorestart=true` 等）；如果没有外部守护，进程只会退出不会自动拉起。需要在回复文案和 runbook 中明确：worker 数量修改后通过退出 + 外部守护重启生效，不在当前进程中动态增减 task。

`MONGO_URI` 的配置管理边界保持收敛：首版不允许通过 QQ `/修改配置` 修改 `MONGO_URI`。`MONGO_URI` 仅允许通过环境变量、部署配置或手工维护 `runtime_config.json` 设置；`/查看配置` 可以脱敏展示是否已配置，但不得显示完整连接串。

注意：当前 `/修改配置` 的重启实现会调用 `os._exit(0)`，不能保证 `driver.on_shutdown` 回调执行。因此通过 QQ 管理命令修改 worker 数量配置时，旧内置 worker 可能不会立刻写入 `stopped/cancelled`，而是依赖 `jjc_sync_workers` 心跳 TTL 自然失效、角色租约过期恢复。首版实现必须在 runbook 中说明这一行为；如要求配置修改时优雅停止，则需先单独改造重启机制。

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
- 暴露 `start_jjc_sync_workers()` / `stop_jjc_sync_workers()`；runtime 模块自身不注册 NoneBot startup/shutdown 回调，避免回调顺序不确定。
- 在 `start_jjc_sync_workers()` 中创建 N 个 `asyncio.Task`。
- 为每个 task 生成稳定可识别的 `worker_id`，建议格式：
  - 默认：`bot:{host}:{index}`。
  - `index` 是本 bot 进程内的 worker 槽位，从 `0` 开始。
  - 不把 `pid`、启动时间戳或随机 uuid 放进内置 worker 主标识，否则线上每次重启都会新增一批离线历史 worker。
  - 如果后续出现同一 host 上多 bot 实例并发托管 worker 的部署，需要单独新增实例名配置或部署级 hostname 区分，避免不同实例的 `bot:{host}:{index}` 冲突。
- task 内调用现有 `jjc_match_data_sync_service.run_worker(...)`。
  - `mode` 固定传入 `"incremental_or_full"`。
  - 不传 `idle_sleep`、`max_seconds`、`max_roles`，使用 `run_worker()` 默认值。
- shutdown 时取消所有未完成 task，`await asyncio.gather(..., return_exceptions=True)` 等待收尾。
- 记录启动失败和 worker 异常日志，不让单个 worker 异常直接终止 bot 主进程。内置 worker wrapper 对 `run_worker()` 的非取消异常策略：捕获 `Exception`（不含 `asyncio.CancelledError`），记录 exception 级别日志，task 退出，不影响 bot 主进程和其他 worker；`asyncio.CancelledError` 按正常取消路径处理。

`bot.py` 的 startup 顺序必须由同一个回调显式保证：

1. 先 `init_mongo(MONGO_URI)`，确保索引和 Mongo 客户端可用。
2. 再启动内置 JJC worker。

不要在 runtime 模块中额外使用 `@driver.on_startup` 注册启动逻辑，否则可能和 `bot.py` 的 Mongo 初始化、`config_manager` 的启动通知回调产生隐式顺序依赖。

其他 `@driver.on_startup` 回调（如插件注册、HTTP 路由挂载、config_manager 启动通知等）不要依赖内置 worker 已启动。worker 启动只保证发生在 Mongo 初始化之后，不承诺早于或晚于任何其他 startup 回调。需要感知 worker 运行状态的逻辑应通过 `jjc_sync_workers` 心跳查询，而非依赖启动顺序。

shutdown 分两条路径说明：

**路径 A — 优雅停止（Ctrl+C、SIGTERM、docker stop 等触发 `driver.on_shutdown` 回调的路径）：**

1. 先取消内置 JJC worker（`stop_jjc_sync_workers()`）。
2. Mongo 客户端在 worker 停止期间必须仍可用，让 `run_worker()` 的 `CancelledError` 分支有机会写入 `stopped/cancelled` 心跳。
3. `close_mongo()` 必须晚于 `stop_jjc_sync_workers()` 执行；如果当前项目还没有关闭 Mongo 的 shutdown 回调，也要在计划实现时保留这个顺序约束，避免未来新增关闭逻辑时反向注册。
4. `stop_jjc_sync_workers()` 对取消收尾、写心跳失败、`gather()` 返回异常等情况只记录 warning，不应阻断 bot 退出流程。
5. 不额外清理 Mongo 队列租约；异常退出时仍依赖既有 lease 过期恢复。

**路径 B — 强杀路径（`os._exit(0)`、`kill -9`、容器强杀、进程崩溃等不触发 `driver.on_shutdown` 的路径）：**

1. shutdown 回调不会执行，`stopped/cancelled` 心跳不会写入。
2. 旧心跳依赖 `jjc_sync_workers` 的在线判定 TTL（当前约 5 分钟）自然失效。
3. 角色租约依赖既有 lease 过期恢复机制处理。
4. 对这条路径不承诺任何收尾动作，实现中不为此增加额外保护代码。

手工回归对应拆为：
- 优雅停止路径：正常 `Ctrl+C` 停止 bot，确认 worker 心跳写入 stopped/cancelled。
- 强杀路径：通过 `/修改配置 JJC_SYNC_WORKER_COUNT=0` 触发 `os._exit(0)` 重启，确认旧 worker 即便没有立即 stopped，也会在 5 分钟内从 active 状态自然失效，未完成角色可由下一次启动恢复。

## 模块与文件落位

- `config.py`
  - 新增 `JJC_SYNC_WORKER_COUNT`，默认 `0`。
  - 默认值保持内置 worker 关闭；使用者可以直接改 `config.py`，环境变量覆盖仅作为部署可选能力。
  - 将 `JJC_SYNC_WORKER_COUNT` 加入 `RUNTIME_CONFIG_KEYS`，支持 `runtime_config.json` 覆盖。
- `src/plugins/config_manager.py`
  - 首版不做完整配置 schema 重构，但需要将 `/修改配置` 和 `/查看配置` 的配置项列表收敛为一个最小统一字典（dict），避免两处列表继续产生明显不一致。每个配置项的 schema 只包含：
    - `type`：值类型（`int`、`str` 等）。
    - `sensitive`：是否敏感，敏感字段在 `/查看配置` 中只展示「已配置」或脱敏形式。
    - `allow_modify`：是否允许通过 `/修改配置` 修改（如 `MONGO_URI` 不允许）。
    - `validate`：可选校验函数，如 `lambda v: v >= 0`。
  - 所有 schema 项默认可查看；不设 `allow_view` 字段。`/查看配置` 展示所有已注册配置项，敏感字段仅展示脱敏值（如 `MON***`），非敏感字段展示完整值。
  - 不引入 `enum_values`、`description`、`default`、分组标签等字段，避免过度设计。
  - 新增 `JJC_SYNC_WORKER_COUNT`；`MONGO_URI` 仍不允许通过 QQ 命令修改。
  - `JJC_SYNC_WORKER_COUNT` 按 int 校验，要求 `>= 0`。
- `bot.py`
  - 在现有 `_startup_mongo()` 中完成 Mongo 初始化后调用 worker runtime 的启动函数。
  - 新增 `driver.on_shutdown` 回调调用停止函数，注册和实现都要保证 worker stop 早于未来可能存在的 `close_mongo()`。
  - 不在 `bot.py` 中直接写 worker 管理细节，避免入口文件继续膨胀。
- `src/services/jx3/jjc_sync_worker_runtime.py`
  - 新增内置 worker 生命周期管理。
  - 只依赖 `config.py`、`jjc_match_data_sync_service` 和标准库 `asyncio/socket`。
  - 不写 JJC 同步业务规则。
  - worker_id 使用稳定槽位名 `bot:{host}:{index}`，让 bot 重启后复用同一条 `jjc_sync_workers` 记录。
  - 停止阶段必须容忍 Mongo 写入失败或 task 取消收尾失败，只记录 warning。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - `register_worker()` 对同一 `worker_id` 重新注册时刷新 `started_at`、`pid`、`host`、`status` 和 `heartbeat_at`。
  - 重新注册时清空 `current_identity_id/current_identity_key/current_server/current_name/last_error`，避免稳定 worker_id 重启后短暂展示上一次处理的角色。
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
  - 明确 `runtime_config.json` 不应提交，以及当前 QQ 管理命令重启路径可能不会立即写 stopped 心跳。
- `docs/exec-plans/index.md`
  - 将本计划加入 Active。
- `.gitignore` 与配置模板文件
  - 先用 `git rm --cached runtime_config.json` 将已跟踪的真实运行时配置移出 Git 索引。
  - 补充 `runtime_config.json` 忽略规则，或采用等价保护策略。
  - 新增 `runtime_config.example.json` 模板文件（确定交付物），包含所有可配置项及其默认值，不含真实敏感值。

## 行为规则

- `JJC_SYNC_WORKER_COUNT <= 0`：不启动任何内置 worker，完全维持当前行为。
- `JJC_SYNC_WORKER_COUNT > 0`：
  - 每个 bot 进程启动对应数量 worker。
  - 多 bot 实例部署时，总 worker 数等于所有实例配置数量之和。
  - 多 worker 并发安全继续依赖 Mongo `lease_owner/lease_expires_at`。
- 配置非法时：
  - `JJC_SYNC_WORKER_COUNT < 0`：记录错误并不启动内置 worker。
- 环境变量非法时：按默认值回退，不允许在 import `config.py` 阶段抛异常；runtime 启动阶段仍做二次校验。
- `/修改配置` 层尽量提前拦截非法值，避免把无效配置写入 `runtime_config.json`；启动期 runtime 仍保留二次校验，防止手工编辑配置文件导致异常启动。
- bot 托管 worker 与 CLI worker 可以同时存在；只要 worker 总量控制合理，Mongo 租约能避免重复领取。
- 内置 worker 重启后会复用 `bot:{host}:{index}` 心跳记录，不再为每次重启新增 worker 记录。升级前已经产生的 `bot:{host}:{process_start_epoch}:{pid}:{index}` 旧记录仍会按离线历史保留，可后续按需人工清理。
- `scripts/jjc_sync.py` 或其他脚本中 `import config` 或 `from config import ...` 不会启动内置 worker。内置 worker 仅在 `bot.py` 显式调用 `start_jjc_sync_workers()` 时创建；`jjc_sync_worker_runtime` 模块自身不注册 `@driver.on_startup`，因此任何不经过 `bot.py` 启动流程的脚本都只会加载配置而不会触发 worker 启动。
- QQ `/jjc同步暂停` 仍是软暂停，内置 worker 和外置 worker 都会在下一个 tick 进入 paused。

## 风险与约束

- 内置 worker 与 QQ 消息处理、HTTP API 共享同一个 Python 进程和事件循环。worker 数量过大时，推栏请求、详情保存和日志输出可能影响 bot 响应。
- 如果容器/进程被强杀，或通过当前 `/修改配置`、`/重启` 的 `os._exit(0)` 路径退出，shutdown 回调不会可靠执行；旧心跳会在现有 5 分钟在线判定后失效，角色租约按已有过期恢复机制处理。
- 如果线上同时保留 systemd/supervisor/手工 CLI worker，又配置了内置 worker，总 worker 数可能超过预期，需要在 runbook 中明确统计口径。
- 默认关闭是必要兼容要求，避免部署升级后无意开始同步。
- 内置 worker `worker_id` 若包含 pid、启动时间戳或随机值，会让 worker 列表在每次重启后积累离线历史；实现必须使用稳定槽位标识。
- `runtime_config.json` 同时承载敏感凭证和启动配置，必须先保护提交边界，再允许通过 QQ 命令写入更多配置。

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
  - `worker_id` 包含 `bot:` 前缀、host 和 index；不包含 pid、启动时间戳或 uuid。
  - mock `jjc_match_data_sync_service.run_worker`，断言 `mode="incremental_or_full"` 和 `worker_id` 均正确传入；`idle_sleep`、`max_seconds`、`max_roles` 不作为内置 worker 配置传入。
  - mock `run_worker` 抛出非 `asyncio.CancelledError` 的 `Exception`（如 `RuntimeError`）时，wrapper 捕获该异常、记录 exception 级别日志、task 正常退出，不影响 bot 主进程和其他 worker 继续运行。
  - shutdown 会 cancel task 并等待收尾。
  - shutdown 时 Mongo 仍可用；`stop_jjc_sync_workers()` 失败只记录 warning，不阻断退出。
  - runtime 模块不自行注册 NoneBot startup/shutdown；启动顺序由 `bot.py` 调用保证。
  - `JJC_SYNC_WORKER_COUNT < 0` 不启动 worker。
- `tests/test_config.py` 或现有配置测试：
  - `_env_int` 对以下输入均返回预期结果，且不抛异常：
    - 环境变量未设置 → 返回默认值。
    - 环境变量为空字符串 `""` → 返回默认值。
    - 环境变量为纯空白 `"  "` → 返回默认值。
    - 环境变量为非法字符串（如 `"abc"`、`"1.5"`、`"true"`、`"--"`、`"0x1"`）→ 返回默认值。
    - 环境变量为正常数字字符串（如 `"0"`、`"3"`、`"-1"`）→ 返回对应 int 值。
  - 非法环境变量不会导致 `config.py` import 失败（即 `_env_int` 本身不抛异常，且 `config.py` 模块级导入不因非法值而崩溃）。
  - `JJC_SYNC_WORKER_COUNT` 通过环境变量设置为 `-1` 时，`config.py` 不抛异常（`_env_int` 只做类型转换不做业务校验），但 runtime 启动阶段二次校验应拒绝并记录错误。
- `tests/test_config_manager.py` 或现有配置命令测试：
  - `/修改配置 JJC_SYNC_WORKER_COUNT=1` 能写入 `runtime_config.json` 并触发重启流程。
  - `/修改配置 JJC_SYNC_WORKER_COUNT=-1` 会被拒绝。
  - `/修改配置 MONGO_URI=...` 会被拒绝，避免通过 QQ 命令修改数据库连接串。
  - `/查看配置` 会展示 `JJC_SYNC_WORKER_COUNT`。
  - `/查看配置` 不明文展示 `TOKEN`、`TICKET`、`MONGO_URI`。
  - `/修改配置` 的 allowed keys 和 `/查看配置` 的展示列表均从同一个 `CONFIG_SCHEMA` dict 派生，新增配置项只需在 `CONFIG_SCHEMA` 中注册一次，两处自动同步，防止列表分叉。
- `.gitignore` / 配置文件保护测试或检查：
  - 执行 `git ls-files runtime_config.json`，期望无输出。
  - 确认 `runtime_config.json` 不进入提交范围；如项目已有等价机制，则在验证记录中说明。
- `tests/test_jjc_sync_worker_queue.py`
  - 同一稳定 `worker_id` 二次注册只保留一条 worker 记录。
  - 二次注册刷新 `started_at/pid/status/heartbeat_at` 并清空上一次残留的 current 字段。

手工回归：

1. 默认配置启动 `python bot.py`，确认 `/jjc同步状态` 显示无活跃 worker。
2. 设置 `JJC_SYNC_WORKER_COUNT=1` 启动 `python bot.py`，或执行 `/修改配置 JJC_SYNC_WORKER_COUNT=1` 等待自动重启，确认 `/api/jjc/sync/workers` 和 `/jjc同步状态` 能看到 `bot:` 前缀 worker。
   - 连续重启 bot 后，同一 host/index 的内置 worker 名称应保持 `bot:{host}:0`，不会继续新增新的内置 worker 名称。
3. 执行 `/jjc同步开始 limit=1`，确认角色进入 queued 后被内置 worker 领取。
4. 执行 `/jjc同步暂停 测试`，确认 worker 进入 paused；再 `/jjc同步恢复`，确认继续领取。
5. 优雅停止路径：`Ctrl+C` 正常停止 bot，确认 worker 心跳写入 stopped/cancelled，Mongo 连接在 worker 停止完成后关闭。
6. 强杀路径：通过 `/修改配置 JJC_SYNC_WORKER_COUNT=0` 触发 `os._exit(0)` 重启，确认旧 worker 不会写入 stopped 心跳，但其 `jjc_sync_workers` 记录在约 5 分钟内从 active 状态自然失效，未完成角色由下一次启动或 CLI worker 恢复。

## 回滚方案

- 将 `JJC_SYNC_WORKER_COUNT` 设置为 `0` 并重启 bot，即可关闭内置 worker；如果通过管理员命令操作，执行 `/修改配置 JJC_SYNC_WORKER_COUNT=0`。
- 如需代码级回滚，删除 `config.py` 新增配置、`bot.py` lifecycle 调用、新增 runtime 模块，并回滚 README/runbook 说明。
- 独立 CLI worker 模式不受影响，回滚后继续使用：

```bash
python scripts/jjc_sync.py worker --mode=incremental_or_full
```

## 实施步骤

> 步骤 1 是硬前置条件：必须先确保 `runtime_config.json` 不会进入提交范围，再开始任何代码或配置变更。后续所有步骤依赖此保护已生效。

1. [x] **（硬前置）** 先保护 `runtime_config.json` 提交边界：执行 `git rm --cached runtime_config.json`，补 `.gitignore` 或等价保护策略，并验证 `git ls-files runtime_config.json` 无输出。不要等新增配置后再补这个保护。
2. [x] 新增唯一配置项 `JJC_SYNC_WORKER_COUNT`，默认关闭，加入 `RUNTIME_CONFIG_KEYS`，并增加容错 `_env_int` 解析。
3. [x] 新增 `jjc_sync_worker_runtime`，实现显式 start/stop task 管理，不注册隐式 startup/shutdown。
4. [x] 在 `bot.py` Mongo 初始化后显式调用 startup，在 shutdown 显式调用停止；确保 worker stop 早于 `close_mongo()`，停止失败只记录 warning。
5. [x] 扩展 `/修改配置`、`/查看配置`：最小收敛 allowed keys/展示列表，支持 `JJC_SYNC_WORKER_COUNT`、参数校验和敏感值脱敏展示；明确拒绝通过 QQ 命令修改 `MONGO_URI`。
6. [x] 补单元测试和 py_compile 验证。
7. [x] 更新 README、README-Docker、runbook，明确内置/外置 worker 共存、runtime 配置安全和当前非优雅重启路径。
8. [x] 完成后在本计划记录执行结果；代码未提交前计划留在 active。

## 执行结果

- 已将 `runtime_config.json` 从 Git 索引移除并加入 `.gitignore`，本地文件内容未删除。
- 已新增 `JJC_SYNC_WORKER_COUNT`、bot 内置 JJC worker runtime、bot startup/shutdown 显式接入、配置管理 schema、文档说明和单元测试。
- 2026-06-04：根据线上反馈修正内置 worker_id 策略，从 `bot:{host}:{process_start_epoch}:{pid}:{index}` 改为稳定槽位 `bot:{host}:{index}`；同步修正 worker 重新注册时刷新启动时间并清空旧 current 字段，避免重启后积累新的离线 worker 名称。
- 已执行验证：
  - `git ls-files runtime_config.json`：无输出。
  - `python -m py_compile bot.py config.py src/services/jx3/jjc_sync_worker_runtime.py`：通过。
  - `python -m unittest tests.test_config tests.test_config_manager tests.test_jjc_sync_worker_runtime`：通过。
  - `python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_worker_queue`：通过。
