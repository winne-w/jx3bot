# JJC 对局同步 worker 队列重设计计划

状态：已完成并归档
更新时间：2026-05-25

## 背景

现有 `/jjc同步开始 limit=<N>` 会在当前 bot 进程内直接领取并同步最多 N 个角色；`scripts/jjc_sync.py start` 也复用同一套同步执行逻辑。队列规模变大后，管理员需要关心“触发同步”和“同步执行”的耦合关系，也无法从页面直接看到排队角色、正在处理的 worker 和优先级。

目标语义调整为：

- `/jjc同步开始 limit=10` 不再直接处理 10 个角色，而是把 10 个可同步角色标记为排队等待处理。
- 可以启动多个独立进程作为 worker；每个 worker 按优先级从排队角色中领取并同步。
- CLI 脚本启动同步时，也只是新增一个 worker 处理进程，而不是临时在脚本内跑一轮。
- 管理员可以添加指定用户，或调整队列中角色的优先级。
- 新增页面展示正在排队的角色、优先级、状态、正在处理的 worker。

## 目标

- 将“入队”和“处理”拆开：
  - 入队入口：QQ `/jjc同步开始 limit=<N>`、CLI `enqueue/start`、HTTP 管理 API。
  - 处理入口：独立 worker 进程循环领取 `queued` 角色，单进程一次处理一个角色，多进程通过 Mongo 原子租约并发协作。
- 保留现有角色同步核心 `_sync_one_role()`、对局详情去重、失败重试、水位推进、暂停/恢复规则。
- 支持角色手动入队与优先级调整：
  - `/jjc同步添加 <服务器> <角色名> [priority=<N>] ...`
  - 新增 `/jjc同步优先级 <服务器> <角色名> <priority>` 或等价 CLI/API。
- 提供只读队列页面和 API：
  - 查看 queued/syncing/pending/cooldown/failed/exhausted 统计。
  - 分页查看排队角色、优先级、服务器、角色名、来源、状态、排队时间、最近同步时间、租约 worker。
  - 查看 worker 心跳、当前角色、最近结果。
- 支持管理员通过 QQ 对话软暂停/恢复所有 worker；暂停后 worker 不再领取新角色，正在处理的角色默认完成当前角色后停止领取。
- 推栏连续返回 ticket 过期、无权限等全局鉴权错误时自动暂停全局同步，不把该错误计入单个角色的业务失败次数。
- 保持 Python 3.9 兼容类型注解。

## 非目标

- 不改 `_sync_one_role()` 内部的推栏分页、match detail、replay、indicator 规则。
- 不引入新的消息队列中间件；继续使用 MongoDB 原子更新和租约。
- 不在首版页面做登录态或复杂权限体系；写操作先通过管理员 QQ/CLI 或后续受控 API。
- 不做单个角色内部并发请求，避免放大推栏接口压力。
- 不清空现有 `jjc_sync_role_queue`，保留历史水位和身份字段。

## 核心业务规则

### 队列状态

在现有 `jjc_sync_role_queue.status` 基础上新增或明确以下状态：

| 状态 | 说明 |
|---|---|
| `pending` | 可被入队但尚未排队处理；兼容已有记录 |
| `queued` | 已排队，等待 worker 领取 |
| `syncing` | 已被某个 worker 领取，租约未过期 |
| `cooldown` | 最近同步成功，冷却期内暂不入队 |
| `exhausted` | 已回溯到赛季开始，周期性冷却后可再次入队 |
| `failed` | 连续失败过多，等待人工或冷却后重试 |
| `disabled` | 不参与入队和同步 |

### 入队规则

- `/jjc同步开始 limit=N`：
  - 校验依赖已配置、`1 <= N <= 200`；全局暂停时仍允许入队，但 worker 不会领取。
  - 从 `pending/cooldown/exhausted/failed` 且 `next_sync_after <= now 或为空` 的角色中，按 `priority desc, updated_at asc` 选择最多 N 个。
  - 原子更新为 `status='queued'`，设置 `queued_at`、`queue_batch_id`、`queue_mode`、`updated_at`。
  - 不立刻调用 `_sync_one_role()`。
  - 返回“已入队 N 个、队列剩余、是否已有 worker 运行”的摘要。
- 手动添加指定用户：
  - 继续 upsert 身份字段与角色水位。
  - 默认 `priority=100`，可传 `priority=<N>`。
  - 是否立即入队由命令决定：`/jjc同步添加` 只确保存在并设优先级；可支持 `queued=1` 直接置为 `queued`。
- 优先级调整：
  - 只修改 `priority` 与 `updated_at`。
  - 若角色已经 `queued`，下一次 worker 领取时按新优先级生效。
  - 若角色 `syncing`，不中断当前 worker。

### worker 规则

- 新增 worker 入口，例如：
  - `python scripts/jjc_sync.py worker --mode=incremental_or_full --idle-sleep=10 --minutes=0`
  - `python scripts/jjc_sync_worker.py --mode=...`
- 每个 worker 进程启动后生成 `worker_id`，写入 `jjc_sync_workers` 并定期心跳。
- 循环行为：
  1. 如果全局暂停，则心跳状态为 `paused` 并 sleep。
  2. 恢复过期角色/详情租约。
  3. 从 `queued` 中按 `priority desc, queued_at asc` 原子领取 1 个角色，设置 `status='syncing'`、`lease_owner=worker_id`、`lease_expires_at`。
  4. 调用现有 `_sync_one_role()`。
  5. 成功后复用 `release_role_success()` 进入 `cooldown/exhausted`；失败后复用 `release_role_failure()`，但首版保留现有失败状态策略。
  6. 无角色时进入 idle sleep。
- 多进程安全依赖 Mongo `find_one_and_update`，不在内存中维护共享队列。

### 中断恢复与暂停规则

- worker 进程异常退出、脚本被 Ctrl-C、容器/程序重启：
  - 未被领取的 `queued` 角色不受影响。
  - 已领取的 `syncing` 角色保留 `lease_owner` 和 `lease_expires_at`；新 worker 启动或周期 tick 会调用 `recover_expired_leases()`，租约过期后恢复为 `queued`，继续按优先级处理。
  - 对局详情 `detail_syncing` 同样靠租约恢复为可重试状态。
  - 角色水位只在 `_sync_one_role()` 完整成功后推进；中断后最多重复扫描部分历史页，已保存 match/detail 通过现有幂等逻辑跳过。
- QQ `/jjc同步暂停 [原因]`：
  - 写入 `jjc_sync_state.paused=True` 和原因，所有 worker 下一个 tick 或当前角色结束后进入 `paused` 心跳状态。
  - 暂停是软暂停：不杀正在执行的请求，不中断当前角色，避免半写状态；暂停只限制 worker 领取，不阻止管理员继续把角色写入 `queued`。
  - 管理员修改推栏 ticket 时，建议先暂停，等页面/状态命令显示 `syncing=0` 或 worker 全部 paused，再重启 bot/worker 进程加载新配置，然后 `/jjc同步恢复`。
- QQ `/jjc同步恢复`：
  - 清除暂停标记；worker 恢复领取 `queued` 角色。
- 后续如需要“立即中止当前角色”，再单独增加 stop-request 机制；首版不做强杀，避免破坏正在写入的对局状态。

### 推栏鉴权错误自动暂停

- 新增全局暂停型错误分类，例如 `JjcSyncGlobalPauseError`，用于表示 ticket 过期、无权限、认证失败、账号被限制等不是单个角色导致的错误。
- worker 或同步 service 识别到该类错误后：
  - 调用 `set_paused(True, reason=<鉴权错误摘要>)`。
  - 当前角色释放回 `queued` 或 `pending`，保留优先级和水位，不递增 `fail_count`。
  - worker 心跳写为 `paused` 或 `error_paused`，`last_error` 记录接口错误。
  - QQ `/jjc同步状态` 和页面展示自动暂停原因，提示更新 ticket 后再恢复。
- 连续判定规则：
  - 对明确的无权限/ticket 过期错误，单次即可暂停。
  - 对网络抖动、超时、推栏 5xx，不触发全局暂停，仍按现有详情/角色失败退避处理。
  - 对模糊鉴权错误可设置短窗口阈值，例如同一 worker 连续 3 次命中相同鉴权关键词再暂停，避免误判。

## 数据结构与索引

### `jjc_sync_role_queue` 新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `queued_at` | float/null | 最近一次入队时间 Unix 秒 |
| `queue_batch_id` | string/null | 本次批量入队批次 ID |
| `queue_mode` | string/null | 入队时指定的同步模式 |
| `queue_source` | string/null | 入队来源，如 `qq_start`、`manual_add`、`cli`、`api` |
| `priority_updated_at` | float/null | 最近一次优先级调整时间 |
| `priority_updated_by` | string/null | 优先级调整来源或管理员标识 |
| `interrupted_reason` | string/null | 因 worker 中断或全局暂停释放回队列的原因 |
| `interrupted_at` | float/null | 最近一次中断释放时间 |

### `jjc_sync_workers` 新集合

用途：记录独立同步 worker 进程状态，供页面和状态命令展示。

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `worker_id` | string | worker 实例 ID，业务唯一 |
| `pid` | int/null | 进程 ID |
| `host` | string/null | 主机名 |
| `mode` | string | 同步模式 |
| `status` | string | `starting/running/paused/idle/syncing/stopped/error` |
| `current_identity_key` | string/null | 当前领取角色 |
| `current_server` | string/null | 当前角色服务器 |
| `current_name` | string/null | 当前角色名 |
| `started_at` | float | 启动时间 |
| `heartbeat_at` | float | 最近心跳时间 |
| `last_result` | object/null | 最近一次角色同步摘要 |
| `last_error` | string/null | 最近 worker 级错误 |
| `stop_reason` | string/null | 正常停止、全局暂停、鉴权自动暂停或异常退出原因 |
| `updated_at` | float | 更新时间 |

索引：

- `idx_worker_id`：`worker_id` unique
- `idx_heartbeat_at`：`heartbeat_at`
- `idx_status_heartbeat_at`：`status`, `heartbeat_at`

### 索引调整

- `jjc_sync_role_queue` 增加 `idx_status_priority_queued_at`：`status`, `priority`, `queued_at`
- 复用现有 `idx_status_priority_next_sync_after` 支撑入队候选查询。

## 模块与文件落位

- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 新增 `enqueue_next_roles(...)`、`claim_queued_role(...)`、`update_role_priority(...)`、`list_queue(...)`。
  - 新增 `release_role_interrupted(...)`，用于 worker 中断、软暂停或全局鉴权失败时把当前角色安全放回队列且不递增 `fail_count`。
  - 新增 worker 注册/心跳/停止方法，或拆出 `JjcSyncWorkerRepo`；首选先放同 repo，保持本同步域集中。
- `src/services/jx3/jjc_match_data_sync.py`
  - 保留 `_sync_one_role()`。
  - 新增 `enqueue_roles(...)`、`run_worker(...)`、`set_role_priority(...)`、`queue_status(...)`。
  - 新增推栏全局鉴权错误识别与自动暂停流程，避免 ticket 失效时污染角色失败状态。
  - 将旧 `run_once/run_until_idle/start_background_run` 标记为兼容包装或调整为调用新入队/worker 语义。
- `src/plugins/jx3bot_handlers/jjc_match_data_sync.py`
  - `/jjc同步开始` 改为入队摘要。
  - `/jjc同步添加` 支持 `priority=` 和可选 `queued=1`。
  - 新增 `/jjc同步优先级 <服务器> <角色名> <priority>`。
  - `/jjc同步状态` 展示 queued 数量、syncing worker、最近 worker 状态。
- `scripts/jjc_sync.py`
  - `start` 改为启动一个 worker 处理进程或进入 worker 循环；为兼容可保留 `enqueue` 子命令。
  - 新增 `worker`、`enqueue`、`priority`、`queue` 子命令。
- `src/api/routers/jjc_sync.py`
  - 新增只读 API：
    - `GET /api/jjc/sync/queue`
    - `GET /api/jjc/sync/workers`
    - `GET /api/jjc/sync/status`
  - 如需要写 API，放在后续受控入口，避免首版裸露管理写操作。
- `public/jjc-sync-queue.html`
  - 新增队列页面，展示统计、worker 列表、队列表格、自动刷新。
- `src/api/__init__.py`
  - 注册新 router。
  - 通过 FastAPI 同源挂载 `public/`，队列页面访问路径为 `/public/jjc-sync-queue.html`，页面继续请求同源 `/api/jjc/sync/...`。
- 文档：
  - `README.md` 增加 API/页面入口。
  - `docs/design-docs/database-design.md` 补字段、集合、索引。
  - `docs/references/runbook.md` 更新运维命令和回归清单。
  - `src/plugins/config_manager.py` 管理员帮助同步更新。

## 实施步骤

1. 存储层
   - 扩展 `JjcSyncRepo` 的入队、领取 queued、优先级调整、队列分页和 worker 状态方法。
   - 补充 repo 单测，使用 fake collection 或现有测试桩覆盖排序、状态过滤、原子领取语义。

2. service 层
   - 新增入队用例 `enqueue_roles(limit, mode, source, batch_id)`。
   - 新增 worker 循环 `run_worker(...)` 和单步 `worker_tick(...)`，便于测试不跑死循环。
   - 新增全局鉴权错误分类和自动暂停处理；鉴权暂停时调用 `release_role_interrupted()` 而不是 `release_role_failure()`。
   - 调整 `status()` 返回 queued 统计和 workers。

3. QQ/CLI 入口
   - 调整 `/jjc同步开始` 输出为入队结果。
   - 新增优先级命令和 CLI 子命令。
   - 调整 `scripts/jjc_sync.py start` 的兼容文案，避免管理员误以为 `limit` 还会直接处理。

4. HTTP API 和页面
   - 新增 router，统一返回 `success_response/error_response`。
   - 新增 `public/jjc-sync-queue.html`，页面首屏就是队列和 worker 状态，不做营销型首页。
   - 页面只读，自动刷新 10 秒，提供状态筛选和分页。

5. 文档与帮助
   - 更新数据库设计、README API 列表、runbook、管理员帮助。
   - 在本计划中记录已完成状态和验证结果。

6. 运维中断与恢复
   - 在 worker 入口捕获 `KeyboardInterrupt`/取消信号，尽量写 `stopped` 心跳；进程被强杀时依赖租约过期恢复。
   - 在 runbook 增加“修改推栏 ticket”的标准流程：暂停、等待当前角色结束、重启 bot/worker、恢复、观察队列。

## 当前进度

- 2026-05-23：已完成阶段 1 方案设计，并按用户确认进入实现。
- 2026-05-23：已实现 Mongo 队列入队/领取/中断释放、worker 心跳、优先级更新、队列分页能力。
- 2026-05-23：已实现 service 入队、worker tick/loop、全局鉴权错误自动暂停、QQ 管理命令和 CLI 入口调整。
- 2026-05-23：已新增只读 HTTP API 与 `public/jjc-sync-queue.html` 队列页面。
- 2026-05-23：已同步 README、数据库设计、runbook 和管理员帮助。
- 2026-05-23：根据复审补充详情状态写回租约 fencing、身份主键迁移租约 fencing、`start --limit=0` 参数兼容修复，并将队列页挂载为 bot 同源静态页面。
- 2026-05-23：已通过本计划自动化验证。
- 2026-05-23：review 后收敛旧执行路径：过期 `syncing` 租约恢复为 `queued`，指定入队不再打断正在同步的角色，旧 `run_once` 兼容入口改为领取 `queued` 角色。
- 2026-05-23：二次 review 发现 release 缺少 lease fencing、长角色同步缺少续租、`run_once` 与 worker tick 仍有统计语义漂移、页面缺少 `queued` 展示。计划先修无争议阻塞项：release 必须校验租约 owner，长流程定期续租，旧兼容路径复用 worker tick，队列页面展示/筛选 `queued`；CLI `start --limit` 空队列退出语义和暂停期间手动入队语义待用户选择后落地。
- 2026-05-23：用户确认 `start --limit` 保持常驻等待、仅修改文案；全局暂停只限制 worker 领取，QQ/CLI 批量入队和手动添加仍允许写入 `queued`。
- 2026-05-24：三次 review 发现 `upsert_role` 仍可能迁移正在同步角色的 `identity_key`、detail 保存后的 replay/indicator/玩家入队缺少角色续租、detail 租约失效会被当成角色租约失效导致角色滞留。本轮修复目标：同步中角色禁止非 owner key 迁移，detail 后处理定期续角色租约，detail stale 释放当前角色回 queued，顺手补齐 CLI usage 和 router/CLI 测试。
- 2026-05-24：恢复后复查发现 `start --limit=0` 只在 CLI fake service 中覆盖，真实 `run_worker(max_roles=0)` 仍会返回 `invalid_max_roles`；已将 0 规范为不限制处理角色数，并补充 service 级单测。同步收敛本 service 的 logger `{}` 占位写法，避免 unittest 环境产生 logging error。
- 2026-05-24：根据 subagent review 完成阻塞问题修复：detail claim 非终态改为中断并回队列、不推进角色水位；`upsert_role()` 统一已有角色更新路径并对非 owner 写入加 `status != syncing` 原子 fencing；`run_once()` 收敛为 `run_worker(stop_when_idle=True)` 薄包装；person-history 增加分页上限并接入角色续租；测试替身和 router 模块隔离同步收敛。
- 2026-05-24：四次 review 发现 `upsert_role` key 迁移仍存在读取后被领取的 TOCTOU、detail saved 早于 replay/indicator/enqueue 可能造成玩家永久不入队、暂停期间不恢复过期租约、页面/API 状态契约不完整。本轮修复目标：迁移 update 加非 syncing 过滤并 fallback，detail 后处理成功后才标 saved 且同时续角色/detail 租约，暂停也执行 recover，补 worker_running/has_more/API 契约和 CLI 文案。
- 2026-05-24：已完成四次 review 修复：legacy key 迁移 update 增加 `status != syncing` 原子条件并在竞态失败时 fallback 到旧 key 更新；对局详情后处理完成后才标记 `detail_saved`，处理期间同时续角色与 detail 租约；暂停 tick 仍恢复过期租约；API/status 补 `worker_running/background_running`，队列分页补 `has_more`；stale lease 不再计入 worker 已处理数量；CLI `start --limit=0` 文案明确为不限数量。
- 2026-05-24：第五次 subagent review 后用户确认 detail stale 采用 A 方案：保持当前保守策略，释放整个角色回队列。本轮修复剩余确认问题：`upsert_role` 迁移竞态失败后不再 fallback 写 syncing 角色；detail claim 异常不升级为角色失败；worker running 判断增加 heartbeat 新鲜度；统一状态文案/测试契约和页面 worker badge。
- 2026-05-24：已完成第五次 review 修复：`upsert_role` 迁移竞态失败后直接返回旧 key、不再执行无租约 fallback 写；活跃 worker 判定要求 5 分钟内 heartbeat；QQ/CLI 状态文案改为全局暂停状态并补 worker 活跃语义；router fake/`has_more` 契约和 worker badge 样式已补齐。`claim_match_detail` 异常在第六次 review 后改为中断当前角色并回队列。`release_role_failure`/`mark_match_detail_failed` 的 read-modify-write 暂不改为 Mongo pipeline，因现有 lease fence 下不是本轮阻塞问题，后续可单独优化。
- 2026-05-24：第六次 subagent review 未发现 blocking，本轮继续修复确认成立的 important：长角色同步期间刷新 worker heartbeat，`upsert_role` 避免非租约 owner 写入 syncing 角色，detail claim 异常改为中断当前角色而不是推进水位，QQ/CLI/页面统一使用 heartbeat 在线语义，补齐 worker 页面字段和文档示例。
- 2026-05-24：已完成第六次 review 修复：角色同步页循环和 detail 循环间隔刷新 worker heartbeat；`claim_match_detail` 异常释放当前角色回 `queued` 并标记 tick 未处理；QQ、CLI、页面统一使用 `online/effective_status`；同步中角色的非租约 upsert 直接跳过；队列页补 `disabled` 筛选和 worker host/pid 展示。
- 2026-05-24：第七次 subagent review 聚焦代码简洁性和不必要兜底，本轮修复目标：删除 service/repo/入口/API/页面中过度兼容分支，修正 auto pause 分支顺序，收敛状态构造与中断判断，清理旧测试桩和已决策文档。
- 2026-05-25：继续第七次 review 修复：service/repo 必备方法改为直接调用，`claim_next_roles()` 不再绕过 queued，handler/API/页面移除旧响应字段兼容，布尔参数改为严格解析。
- 2026-05-24：最新 subagent review 修复完成：常驻 worker 遇到 interrupted/stale detail/stale role tick 不再退出，改为计入 `interrupted_ticks` 并按 `idle_sleep` 退避继续；one-shot `stop_when_idle=True` 仍按 interrupted 停止。detail claim 状态判断收敛到 repo `get_match_detail_sync_state()` 的 `action` 合同，service 不再 optional getattr 或硬编码终态 status。测试 `FakeRepo` 补齐 queued claim 后 `syncing` 租约、角色 release/renew owner fencing 和 detail 租约状态模拟。
- 2026-05-24：修复 JJC 同步 worker 租约 fencing 缺陷。`_sync_match_detail` 在 `role_identity_key` 非空时先强制续租/校验角色租约，角色续租失败则直接抛出 `JjcSyncStaleRoleLeaseError`、不创建任何 detail 租约。FakeRepo `_role_lease_allows` / `_detail_lease_allows` 对不存在的 doc 返回 `False`（与真实 Mongo update filter 语义一致）。修复受影响的测试（显式种子角色租约）。新增服务测试覆盖角色租约过期先于 detail claim 的防护路径，新增 worker queue 测试覆盖过期 owner 不能 `release_role_interrupted` / `release_match_detail_interrupted` 且带 `lease_owner`。
- 2026-05-25：继续收敛第七次 review 的简洁性问题，移除 `_sync_match_detail()` 中最后一个 repo 方法动态探测，`release_match_detail_interrupted()` 改为明确仓储合约调用。
- 2026-05-25：新增队列页面可用性小改动计划：`/api/jjc/sync/queue` 增加 `server`、`name` 查询参数并透传到 service/repo；repo 对服务器和角色名做转义后的模糊匹配；页面增加服务器/角色搜索框，状态筛选和 badge 展示改为中文文案，API 原始状态值保持不变以免影响 worker 逻辑。

## 验证结果

已执行：

```bash
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py scripts/jjc_sync.py src/infra/mongo.py src/plugins/config_manager.py src/api/__init__.py
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py src/api/__init__.py public/jjc-sync-queue.html scripts/jjc_sync.py src/infra/mongo.py src/plugins/config_manager.py tests/test_jjc_match_data_sync.py tests/test_jjc_match_data_sync_handler.py tests/test_jjc_sync_worker_queue.py tests/test_jjc_sync_router.py README.md docs/design-docs/database-design.md docs/references/runbook.md docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md docs/exec-plans/index.md
python -m unittest tests.test_jjc_sync_worker_queue tests.test_jjc_sync_repo
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_match_data_sync_handler tests.test_jjc_sync_router
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py tests/test_jjc_match_data_sync.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_worker_queue.py docs/design-docs/database-design.md docs/references/runbook.md docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_match_data_sync_handler tests.test_jjc_sync_worker_queue tests.test_jjc_sync_repo
python scripts/jjc_sync.py start --help
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py scripts/jjc_sync.py tests/test_jjc_match_data_sync.py tests/test_jjc_match_data_sync_handler.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_worker_queue.py public/jjc-sync-queue.html docs/references/runbook.md docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_router
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py src/api/__init__.py scripts/jjc_sync.py src/infra/mongo.py
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py scripts/jjc_sync.py src/api/__init__.py tests/test_jjc_match_data_sync.py tests/test_jjc_sync_repo.py README.md docs/references/runbook.md docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router tests.test_jjc_sync_cli
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py src/api/__init__.py scripts/jjc_sync.py src/infra/mongo.py
python scripts/jjc_sync.py start --help
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py scripts/jjc_sync.py tests/test_jjc_match_data_sync.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_router.py tests/test_jjc_sync_cli.py docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md
python -m unittest tests.test_jjc_sync_cli tests.test_jjc_match_data_sync tests.test_jjc_sync_worker_queue
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router tests.test_jjc_sync_cli
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py src/api/__init__.py scripts/jjc_sync.py src/infra/mongo.py tests/test_jjc_match_data_sync.py tests/test_jjc_sync_cli.py
python scripts/jjc_sync.py start --help
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py src/api/__init__.py scripts/jjc_sync.py src/infra/mongo.py src/plugins/config_manager.py tests/test_jjc_match_data_sync.py tests/test_jjc_match_data_sync_handler.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_worker_queue.py tests/test_jjc_sync_router.py tests/test_jjc_sync_cli.py public/jjc-sync-queue.html README.md docs/design-docs/database-design.md docs/references/runbook.md docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md docs/exec-plans/index.md
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router tests.test_jjc_sync_cli
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py tests/test_jjc_match_data_sync.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_worker_queue.py tests/test_jjc_sync_router.py
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py tests/test_jjc_match_data_sync.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_worker_queue.py tests/test_jjc_sync_router.py docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py src/api/__init__.py scripts/jjc_sync.py src/infra/mongo.py tests/test_jjc_match_data_sync.py tests/test_jjc_match_data_sync_handler.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_router.py tests/test_jjc_sync_cli.py
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router tests.test_jjc_sync_cli
python scripts/jjc_sync.py start --help
git diff --check -- src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py public/jjc-sync-queue.html scripts/jjc_sync.py tests/test_jjc_match_data_sync.py tests/test_jjc_match_data_sync_handler.py tests/test_jjc_sync_repo.py tests/test_jjc_sync_router.py tests/test_jjc_sync_cli.py tests/test_jjc_sync_worker_queue.py docs/exec-plans/active/jjc-sync-worker-queue-redesign-plan.md
```

结果：

- py_compile 通过。
- 首轮单测 108 条通过；review 修复后分组重跑 36 + 73 条通过；最终相关套件 115 条通过；本轮复审修复后相关套件 124 条通过。
- 三次 review 修复后相关套件 130 条通过；新增覆盖正在同步角色延后 key 迁移、detail 后处理续角色租约、detail stale 释放角色回队列、`start --limit` CLI 兼容参数。
- 恢复后复查相关套件 131 条通过；新增覆盖 `run_worker(max_roles=0)` 的真实 service 兼容行为，重跑后未再出现 logging error。
- review 修复后相关套件 144 条通过；覆盖 detail 非终态 claim 中断、`upsert_role()` syncing fencing 与 DuplicateKey fallback、`run_once` worker 生命周期收敛、person-history 分页上限/续租、测试替身 queued 契约和 router 模块隔离。
- 四次 review 修复后相关套件 140 条通过；新增覆盖 key 迁移 TOCTOU fallback、detail 后处理失败不标 saved、detail 租约续租、暂停状态恢复过期租约、stale tick 不计入已处理角色、`worker_running/has_more` API 契约和 CLI 文案。
- 五次 review 修复后相关套件 144 条通过；新增覆盖迁移竞态失败不 fallback 写、detail claim 异常不失败角色、旧 worker heartbeat 不算活跃、router `has_more` 末页契约和状态文案。
- 第六次 review 修复后相关套件 149 条通过；本轮新增覆盖长角色同步刷新 worker heartbeat、detail claim 异常回队列且不推进水位、同步中 upsert 不写 profile、QQ/CLI heartbeat 在线状态展示。
- 最新 review 修复后指定套件 149 条通过；新增覆盖常驻 worker interrupted 后继续 tick、one-shot interrupted 停止、FakeRepo 角色租约 owner fencing、repo detail 状态 `action=skip/interrupt/claimable` 合同。指定 py_compile 通过，指定 `git diff --check` 无 whitespace error。
- 2026-05-24：修复租赁过期 fencing 与 detail 续租顺序问题。`_leased_role_filter` 和 `_leased_match_detail_filter` 新增 `now` 参数，当 `lease_owner is not None` 时附加 `lease_expires_at > now` 检查，防止过期租约持有者写入角色/详情终态、释放、续租或身份迁移；普通 `update_role_identity_fields()` 和 key 迁移路径均纳入 active lease fencing。`renew_processing_context` 顺序改为先续角色租约再续详情租约，确保角色租约过期时不会延长详情租约后失败角色续租，避免遗留详情锁定。FakeRepo 同步增加过期租约 fencing 模拟。新增 worker_queue/repo 测试覆盖过期租约不能 renew/release/mark/update 的情景。相关套件 159 条通过。
- `python scripts/jjc_sync.py start --help` 通过，`--limit` 文案已明确队列暂空时仍常驻等待。
- `git diff --check` 无 whitespace error；Git 仅提示部分已有 CRLF/LF 转换警告。
- 2026-05-24：修复 JJC 同步 worker 租约 fencing 缺陷后全量验证通过。`python -m py_compile` 无错误；`python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router tests.test_jjc_sync_cli` 162 条全部通过；指定范围 `git diff --check` 无 whitespace error。新增覆盖：角色租约过期先于 detail claim 时直接抛出 `JjcSyncStaleRoleLeaseError` 且不创建 detail 状态/租约；过期 owner 不能 `release_role_interrupted` / `release_match_detail_interrupted` 且带 `lease_owner` 参数。
- 2026-05-25：第七次 review 简洁性收敛后验证通过。指定 `py_compile` 无错误；`python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo tests.test_jjc_sync_worker_queue tests.test_jjc_sync_router tests.test_jjc_sync_cli` 173 条全部通过；`python scripts/jjc_sync.py start --help` 通过；指定范围 `git diff --check` 无 whitespace error，仅提示既有 CRLF/LF 转换警告。
- 2026-05-25：队列页面搜索与中文状态展示改动验证通过。`python -m py_compile src/api/routers/jjc_sync.py src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py tests/test_jjc_sync_router.py tests/test_jjc_sync_worker_queue.py` 无错误；`python -m unittest tests.test_jjc_sync_router tests.test_jjc_sync_worker_queue` 30 条全部通过；指定范围 `git diff --check` 无 whitespace error，仅提示既有 CRLF/LF 转换警告。

## 验证计划

自动化：

```bash
python -m unittest tests.test_jjc_sync_repo tests.test_jjc_match_data_sync tests.test_jjc_match_data_sync_handler
python -m py_compile src/storage/mongo_repos/jjc_sync_repo.py src/services/jx3/jjc_match_data_sync.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/api/routers/jjc_sync.py scripts/jjc_sync.py
```

新增测试建议：

- `tests/test_jjc_sync_worker_queue.py`：入队排序、queued 领取、worker 心跳、优先级更新。
- `tests/test_jjc_sync_router.py`：队列/worker/status API 响应格式和参数校验。

手工回归：

1. `/jjc同步添加 梦江南 角色A priority=100 queued=1` 后页面可见 queued 角色。
2. `/jjc同步开始 limit=10 incremental` 返回入队数量，不直接处理角色。
3. 启动两个 `python scripts/jjc_sync.py worker --mode=incremental`，确认两个 worker 不会领取同一角色。
4. `/jjc同步优先级 梦江南 角色A 500` 后，queued 列表排序变化。
5. `/jjc同步暂停` 后 worker 心跳为 paused，不再领取新角色；`/jjc同步恢复` 后继续处理。
6. 人工 kill 一个 worker，等待租约过期后再次启动 worker，确认 syncing 角色能恢复为 queued 并被重新处理。
7. 模拟推栏 ticket 过期/无权限响应，确认全局同步自动暂停，当前角色不增加 fail_count，状态命令和页面展示暂停原因。

## 风险与回滚

- 风险：多 worker 放大推栏接口压力。控制方式：单 worker 单角色串行，默认只启动一个 worker；CLI 文档明确并发上限建议。
- 风险：`limit` 语义变化影响旧习惯。控制方式：QQ/CLI 输出明确“已入队，不在当前进程处理”，保留兼容命令文案。
- 风险：worker 心跳残留。控制方式：页面按 `heartbeat_at` 判断离线，worker 正常退出写 `stopped`。
- 风险：ticket 过期造成大量角色失败。控制方式：全局鉴权错误触发自动暂停，当前角色释放回队列且不累加角色失败次数。
- 回滚：将 `/jjc同步开始` 改回调用旧 `run_once/run_until_idle`；保留新增字段不影响旧逻辑，`queued` 角色可批量改回 `pending`。

## 已确认决策

- `scripts/jjc_sync.py start` 保持前台 worker 常驻运行，交给 systemd/docker/supervisor 拉起多个进程。
- 队列页面首版只读；调整优先级、添加角色继续走 QQ 管理命令和 CLI。
- `failed` 角色允许在 `next_sync_after` 到期后被 `/jjc同步开始 limit=N` 自动重新入队，保持失败重试语义。
