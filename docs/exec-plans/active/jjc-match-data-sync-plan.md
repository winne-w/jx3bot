# JJC 对局数据同步计划

状态：计划中
更新时间：2026-04-30

## 背景

本功能不是“爬虫”，而是通过官方提供的推栏/JJC 接口同步角色本赛季对局历史与对局详情，作为后续学习分析的数据准备。第一阶段只做数据拉取、去重、续拉和任务状态管理，不做职业分布统计、强弱分析或统计 API。

现有能力已经支持按需查看角色近期战绩和单局详情，并将对局详情按 `match_id` 缓存到 `jjc_match_detail`。新的同步能力应复用现有详情保存链路，避免重复设计原始详情存储。

## 目标

- 通过 QQ 管理员命令添加需要同步的角色。
- 通过 QQ 管理员命令触发一轮 JJC 对局数据同步。
- 对新角色尽量同步完整个本赛季对局历史。
- 对已完整同步过的角色按时间水位增量同步，只补齐上次完整覆盖时间点之后的新对局。
- 从已保存对局详情中发现双方角色，并加入后续同步队列。
- 支持服务重启后继续同步，不因中断丢失进度或误标记完成。
- 所有推栏接口请求前执行随机 sleep，规则与竞技排名查询的 sleep 风格保持一致。

## 非目标

- 不做心法出场、胜率、唯一玩家数等统计。
- 不做职业强弱或对位分析。
- 不新增统计事实表。
- 不新增 HTTP 管理入口，第一阶段入口只放在 QQ 命令。
- 不把同步任务默认自动开启；应由管理员命令触发或显式配置启用。

## QQ 入口

命令命名使用“同步”，避免使用“爬虫”。

建议入口：

```text
/jjc同步添加 <服务器> <角色名>
/jjc同步添加 <服务器> <角色名> global_role_id=<id> role_id=<id> zone=<zone>
/jjc同步开始
/jjc同步开始 full
/jjc同步开始 incremental
/jjc同步状态
/jjc同步暂停
/jjc同步恢复
/jjc同步重置 <服务器> <角色名>
```

命令语义：

- `/jjc同步添加`：添加或更新待同步角色，来源标记为 `manual`，优先级高于自动发现角色。
- `/jjc同步开始`：触发一轮同步，默认模式为 `incremental_or_full`，有水位则增量，没有水位则本赛季全量。
- `/jjc同步开始 full`：对选中的待同步角色尽量同步完整个本赛季。
- `/jjc同步开始 incremental`：只同步上次完整覆盖时间点之后的新对局。
- `/jjc同步状态`：查看队列状态、最近一轮同步摘要、最近错误。
- `/jjc同步暂停` / `/jjc同步恢复`：控制后续同步任务是否允许执行。
- `/jjc同步重置`：重置指定角色本赛季同步进度，从最新对局重新向赛季开始同步。

权限限制：

- 这些命令只有机器人管理员能触发。
- 管理员判断必须复用现有“限制 / 重启”命令的权限逻辑或同一份管理员配置，不单独维护一套权限。

## 数据模型

### `jjc_sync_role_queue`

用途：保存角色同步队列与每个角色的本赛季同步进度。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `identity_key` | string | 角色身份键，优先 `global:{global_role_id}`，其次 `game:{zone}:{role_id}`，最后 `name:{server}:{name}` |
| `server` | string | 服务器 |
| `name` | string | 角色名 |
| `normalized_server` | string | 规范化服务器名 |
| `normalized_name` | string | 规范化角色名 |
| `global_role_id` | string/null | 推栏全局角色 ID |
| `role_id` | string/null | 角色 ID |
| `zone` | string/null | 区服分区 |
| `source` | string | `manual`、`ranking`、`match_detail` |
| `priority` | int | 调度优先级，手动添加高于自动发现 |
| `status` | string | `pending`、`syncing`、`exhausted`、`cooldown`、`failed`、`disabled` |
| `season_id` | string/null | 当前赛季标识 |
| `season_start_time` | int | 当前赛季开始时间 Unix 秒 |
| `full_synced_until_time` | int/null | 已完整覆盖到的最新时间点 |
| `oldest_synced_match_time` | int/null | 已同步到的最早对局时间 |
| `latest_seen_match_time` | int/null | 最近看到的最新对局时间 |
| `history_exhausted` | bool | 本赛季是否已经回溯到赛季开始 |
| `last_cursor` | int | 最近处理 cursor，仅用于诊断和中断恢复参考 |
| `lease_owner` | string/null | 当前执行实例标识 |
| `lease_expires_at` | datetime/null | 执行租约过期时间，用于重启恢复 |
| `last_synced_at` | int/null | 最近同步时间 Unix 秒 |
| `next_sync_after` | int/null | 下一次允许同步时间 Unix 秒 |
| `fail_count` | int | 连续失败次数 |
| `last_error` | string/null | 最近错误 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

建议索引：

- `identity_key` unique
- `status`, `priority`, `next_sync_after`
- `normalized_server`, `normalized_name`
- `global_role_id`
- `lease_expires_at`

### `jjc_sync_match_seen`

用途：保存已发现对局与详情同步状态，避免重复请求详情。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `match_id` | int | 对局 ID，业务唯一 |
| `source_identity_key` | string/null | 首次发现该对局的角色身份键 |
| `source_server` | string/null | 首次发现来源服务器 |
| `source_role_name` | string/null | 首次发现来源角色 |
| `status` | string | `discovered`、`detail_syncing`、`detail_saved`、`failed` |
| `match_time` | int/null | 对局时间 Unix 秒 |
| `lease_owner` | string/null | 当前执行实例标识 |
| `lease_expires_at` | datetime/null | 执行租约过期时间 |
| `first_seen_at` | datetime | 首次发现时间 |
| `detail_saved_at` | datetime/null | 详情保存时间 |
| `fail_count` | int | 连续失败次数 |
| `last_error` | string/null | 最近错误 |
| `updated_at` | datetime | 更新时间 |

建议索引：

- `match_id` unique
- `status`, `match_time`
- `source_identity_key`
- `lease_expires_at`

## 同步水位

同步终止不应依赖普通页数限制，而应依赖时间水位和赛季边界。

关键字段：

- `season_start_time`：本赛季起点。
- `full_synced_until_time`：该角色已经完整覆盖到的最新时间点。

示例：

- 5 号 12:00 已将某角色本赛季从赛季开始到 5 号 12:00 全部同步完成，则记录 `full_synced_until_time = 5号12点`。
- 6 号 03:00 再次同步时，从最新对局向前拉取，只处理 `match_time > 5号12点` 的对局。
- 当页面进入 `match_time <= 5号12点` 的已覆盖区间，处理完边界页里所有新对局后停止，不继续向更早历史请求。
- 本轮完整结束后才更新 `full_synced_until_time = 6号03点`。

`full_synced_until_time` 只能在本轮确认完整覆盖目标区间后提交，不能每页提前推进。这样服务重启时不会把半截任务误标记为完成。

## 同步流程

### 首次本赛季全量同步

适用于新角色或重置后的角色。

```text
run_upper_time = 当前时间
stop_time = season_start_time
cursor = 0
```

流程：

1. 从 `cursor=0` 拉取官方战局历史。
2. 每次请求前随机 sleep。
3. 过滤并处理 3v3 对局。
4. 对每个 `match_id` 写入 `jjc_sync_match_seen`。
5. 如果 `jjc_match_detail` 已存在或 `jjc_sync_match_seen.status = detail_saved`，跳过详情请求。
6. 否则请求官方对局详情并保存到 `jjc_match_detail`。
7. 从详情的 `team1.players_info` 和 `team2.players_info` 发现角色，写入或更新 `jjc_sync_role_queue`。
8. 逐页向历史回溯，直到遇到 `match_time <= season_start_time`、接口空页或尾页。
9. 正常完成后提交 `full_synced_until_time = run_upper_time`。

### 后续增量同步

适用于已有 `full_synced_until_time` 的角色。

```text
run_upper_time = 当前时间
stop_time = full_synced_until_time
cursor = 0
```

流程：

1. 从最新战绩开始拉取。
2. 只处理 `match_time > stop_time` 的对局。
3. 对 `match_time <= stop_time` 的对局视为已覆盖区间。
4. 边界页处理完后停止，不继续请求更早页面。
5. 正常完成后提交 `full_synced_until_time = run_upper_time`。

## 终止条件

业务终止条件：

- 到达 `full_synced_until_time`。
- 到达 `season_start_time`。
- 官方接口返回空列表。
- 官方接口返回明显尾页。

工程安全阀：

- 单轮最大运行时长。
- 单角色最大请求数 safety。
- 连续相同 cursor 次数。
- 连续相同页面指纹次数。
- 全局暂停开关。

安全阀触发时，不应标记 `history_exhausted = true`，也不应推进 `full_synced_until_time`。应记录错误并让角色进入 `cooldown` 或 `failed`，后续可继续。

## 服务重启恢复

同步任务必须可中断、可恢复、幂等。所有关键进度落 MongoDB，不依赖内存。

启动恢复逻辑：

1. 找出 `jjc_sync_role_queue.status = syncing` 且 `lease_expires_at < now` 的角色。
2. 将这些角色恢复为 `pending`，清空 `lease_owner` 和 `lease_expires_at`。
3. 找出 `jjc_sync_match_seen.status = detail_syncing` 且 `lease_expires_at < now` 的对局。
4. 将这些对局恢复为 `discovered`，清空 `lease_owner` 和 `lease_expires_at`。

中断后的行为：

- 已保存的 `jjc_match_detail` 通过 `match_id` 幂等去重。
- 已发现但未保存详情的对局会重新尝试。
- 正在同步的角色会回到 `pending`。
- `full_synced_until_time` 在本轮完整完成前不会推进，因此不会漏掉中断区间。

示例：

```text
run_upper_time = 6号03点
stop_time = 5号12点
```

如果同步到 6 号 01 点时服务重启，`full_synced_until_time` 仍是 5 号 12 点。重启后再次执行 `/jjc同步开始`，系统重新从 `cursor=0` 补到 5 号 12 点。已保存过的 match 通过 `match_id` 跳过，未保存的继续补齐。完整完成后才提交 `full_synced_until_time = 6号03点`。

## 官方接口请求 sleep

所有官方推栏接口请求前都必须随机 sleep：

- 战局历史请求。
- 对局详情请求。
- 身份补全请求。

sleep 规则与竞技排名查询保持一致。若现有逻辑是 `random.uniform(3, 5)` 或固定等待加随机等待，应抽成公共 helper，让排名查询和同步任务共用，避免两套规则漂移。

## 调度与状态

角色状态流转：

```text
pending -> syncing -> exhausted/cooldown
pending -> syncing -> failed
failed -> pending
exhausted -> cooldown
cooldown -> pending
disabled 不参与调度
```

说明：

- `exhausted` 表示本赛季历史已回溯到赛季开始。
- `cooldown` 表示暂时不用同步，未来用于增量检查。
- 已 `exhausted` 的活跃角色未来仍可能有新对局，不能永久停止。

## 实现落点

建议新增：

```text
src/services/jx3/jjc_match_data_sync.py
src/storage/mongo_repos/jjc_sync_repo.py
src/plugins/jx3bot_handlers/jjc_match_data_sync.py
```

建议修改：

```text
src/services/jx3/singletons.py
src/infra/mongo.py
docs/design-docs/database-design.md
docs/references/runbook.md
docs/tasks/in-progress/jjc-ranking-role-inspect.md 或新增独立 task 文档
```

职责：

- handler：QQ 命令、管理员校验、参数解析。
- service：同步流程编排、时间水位、状态流转、重启恢复。
- repo：同步队列、对局 seen、租约、状态读写。
- inspect service：复用现有对局详情加载与保存能力。
- mongo：索引初始化。

## 用例设计

先写测试，再实现。

1. 管理员权限
   - 非管理员发送 `/jjc同步开始`，断言拒绝。
   - 管理员发送，断言进入 service。

2. 手动添加角色
   - `/jjc同步添加 梦江南 角色A` 写入 `jjc_sync_role_queue`。
   - 状态为 `pending`，来源为 `manual`。

3. 重复添加角色
   - 已存在角色再次添加，不重复插入。
   - 更新身份字段、来源和优先级，不重置同步水位，除非显式 reset。

4. 首次本赛季全量同步
   - 角色没有 `full_synced_until_time`。
   - mock 多页战绩直到赛季开始前。
   - 断言持续分页，保存 match，最后提交 `full_synced_until_time = run_upper_time`。

5. 增量同步
   - 角色已有 `full_synced_until_time = 5号12点`。
   - mock 返回 6号3点到5号12点之间的数据，以及更早数据。
   - 断言只处理水位之后的数据，到水位停止。

6. 不用普通页数作为业务终止
   - mock 返回很多页，只要还没到水位或赛季开始，就继续。
   - 断言不会因为普通页数限制提前标记完成。

7. 安全阀
   - mock cursor 不前进或页面重复。
   - 断言进入 `failed` 或 `cooldown`，不推进 `full_synced_until_time`，不标记 `history_exhausted = true`。

8. 对局详情去重
   - `jjc_match_detail` 已有 `match_id`。
   - 断言不重复请求详情。

9. 详情发现新角色
   - 保存详情后发现双方 6 个玩家。
   - 断言新玩家入队，已有玩家不重置进度。

10. 服务重启恢复
    - `syncing` 角色租约过期，启动恢复后变回 `pending`。
    - `detail_syncing` 对局租约过期，启动恢复后变回 `discovered`。

11. 水位提交时机
    - 中途失败或重启时，断言 `full_synced_until_time` 不变。
    - 正常触达 stop_time 后，才提交到本轮 `run_upper_time`。

12. 官方接口 sleep
    - mock sleep helper。
    - 断言历史请求、详情请求和身份补全请求前都调用随机 sleep。

13. Python 3.9 编译检查
    - 新增文件不使用 `str | None`、`dict[str, Any] | None` 等不兼容注解。

## 可委派实施步骤

本章节用于把工作拆成可交给 Claude 或其他执行代理的小任务。每一步都应单独提交可验证改动，除非明确说明依赖前一步。

### Step 0：确认现有管理员权限入口

目标：找到“限制 / 重启”命令使用的管理员判断逻辑，形成复用方案。

输入：

- `src/plugins/`
- `src/plugins/jx3bot_handlers/`
- `src/services/jx3/singletons.py`

输出：

- 在计划文档或任务备注中记录管理员判断函数/配置位置。
- 不改业务代码，除非只是补充极小的 helper 注释。

验收：

- 明确 `/jjc同步*` 命令应复用哪个管理员判断入口。
- 明确非管理员拒绝时复用什么提示风格。

### Step 1：抽取官方接口随机 sleep helper

目标：把竞技排名查询现有等待规则抽成可复用 helper，让数据同步任务复用同一规则。

改动范围：

- `src/services/jx3/jjc_ranking.py`
- 可新增 `src/services/jx3/tuilan_rate_limit.py` 或放在更合适的现有 service 工具模块。

要求：

- 保持竞技排名查询现有等待行为不变。
- 数据同步后续调用同一个 helper。
- helper 支持测试时注入或 mock，避免单测真实 sleep。

测试：

- 新增或更新单测，断言 helper 被调用。
- 至少执行相关文件 `py_compile`。

验收：

- 竞技排名查询逻辑仍可读。
- 没有新增第二套 sleep 规则。

### Step 2：实现同步仓储 `JjcSyncRepo`

目标：只实现 Mongo 仓储，不写同步编排。

新增文件：

- `src/storage/mongo_repos/jjc_sync_repo.py`

能力：

- `upsert_role(...)`：添加/更新待同步角色。
- `claim_next_roles(...)`：按状态、优先级、冷却时间领取角色，并写入租约。
- `release_role_success(...)`：成功完成后更新水位和状态。
- `release_role_failure(...)`：失败后记录错误、失败次数和冷却。
- `recover_expired_leases(...)`：恢复过期 `syncing` / `detail_syncing`。
- `mark_match_discovered(...)`：记录发现的 `match_id`。
- `claim_match_detail(...)`：领取待同步详情的对局。
- `mark_match_detail_saved(...)`：标记详情已保存。
- `mark_match_detail_failed(...)`：标记详情失败。

要求：

- 所有写入幂等。
- 字段命名使用 `sync`，不要出现 `crawler` / `crawl`。
- Python 3.9 类型注解兼容。

测试：

- 使用 mock Motor collection 或现有测试风格覆盖 upsert、claim、lease recovery、match seen 去重。

验收：

- 仓储层不依赖 NoneBot。
- 仓储层不调用官方接口。

### Step 3：补 Mongo 索引和数据库文档

目标：为 `jjc_sync_role_queue` 和 `jjc_sync_match_seen` 补索引，并同步数据库设计文档。

改动范围：

- `src/infra/mongo.py`
- `docs/design-docs/database-design.md`

索引：

- `jjc_sync_role_queue.identity_key` unique
- `jjc_sync_role_queue.status + priority + next_sync_after`
- `jjc_sync_role_queue.normalized_server + normalized_name`
- `jjc_sync_role_queue.global_role_id`
- `jjc_sync_role_queue.lease_expires_at`
- `jjc_sync_match_seen.match_id` unique
- `jjc_sync_match_seen.status + match_time`
- `jjc_sync_match_seen.source_identity_key`
- `jjc_sync_match_seen.lease_expires_at`

测试：

- `python -m py_compile src/infra/mongo.py`

验收：

- 文档字段、索引、归属与代码一致。

### Step 4：实现同步领域对象和解析 helper

目标：实现不访问外部接口的纯逻辑，降低 service 复杂度。

建议位置：

- `src/services/jx3/jjc_match_data_sync.py`

能力：

- 构建 `identity_key`。
- 从官方历史列表 item 提取 `match_id`、`match_time`、`pvp_type`。
- 从对局详情 payload 提取双方角色。
- 判断页面是否到达 `stop_time` / `season_start_time`。
- 生成页面指纹，用于安全阀判断重复页面。

测试：

- 纯单元测试覆盖边界字段缺失、时间水位、赛季边界、非 3v3 过滤、详情玩家提取。

验收：

- 这些 helper 不依赖 Mongo、NoneBot 或真实官方接口。

### Step 5：实现单角色同步流程

目标：实现“一个角色从 cursor=0 拉到 stop_time/season_start_time”的核心流程。

改动范围：

- `src/services/jx3/jjc_match_data_sync.py`

输入依赖：

- `JjcSyncRepo`
- `MatchHistoryClient`
- `JjcRankingInspectService.get_match_detail`
- 官方接口 sleep helper

流程要求：

- 本轮开始固定 `run_upper_time`。
- 有 `full_synced_until_time` 时执行增量同步。
- 没有水位或 full 模式时同步到 `season_start_time`。
- 请求历史页前随机 sleep。
- 请求详情前随机 sleep，或确保详情请求内部同样经过统一 sleep。
- 到达 stop_time 后停止。
- 中途失败不推进 `full_synced_until_time`。
- 正常完成后才提交 `full_synced_until_time = run_upper_time`。

测试：

- 首次全量同步。
- 增量同步。
- 到水位停止。
- 到赛季开始停止。
- 中途失败不提交水位。
- 详情已存在时跳过重复请求。
- 重复页面触发安全阀。

验收：

- 不使用普通页数作为业务终止条件。
- 只保留 safety 上限，触发 safety 不标记完成。

### Step 6：实现一轮同步调度

目标：实现管理员触发的一轮同步，负责领取多个角色并顺序处理。

改动范围：

- `src/services/jx3/jjc_match_data_sync.py`
- `src/services/jx3/singletons.py`

能力：

- `run_once(mode=...)`
- 启动前恢复过期租约。
- 按优先级领取角色。
- 顺序同步角色，避免官方接口并发过高。
- 支持全局暂停状态。
- 返回本轮摘要：处理角色数、发现 match 数、保存详情数、失败数、耗时、最近错误。

测试：

- 暂停时不执行。
- 正常领取并处理角色。
- 一个角色失败不影响后续角色。
- 启动时调用 lease recovery。

验收：

- 不自动常驻启动，第一阶段由 QQ 管理员命令触发。

### Step 7：实现 QQ 管理命令

目标：提供 QQ 输入入口，且只有机器人管理员能触发。

新增或修改：

- `src/plugins/jx3bot_handlers/jjc_match_data_sync.py`
- `src/plugins/jx3bot_handlers/__init__.py` 或现有 handler 注册入口

命令：

- `/jjc同步添加 <服务器> <角色名>`
- `/jjc同步添加 <服务器> <角色名> global_role_id=<id> role_id=<id> zone=<zone>`
- `/jjc同步开始`
- `/jjc同步开始 full`
- `/jjc同步开始 incremental`
- `/jjc同步状态`
- `/jjc同步暂停`
- `/jjc同步恢复`
- `/jjc同步重置 <服务器> <角色名>`

要求：

- 权限与“限制 / 重启”一致。
- handler 只做权限、参数解析、调用 service、组织回复。
- service 不依赖 NoneBot 事件对象。

测试：

- 可优先做参数解析 helper 单测。
- 管理员权限可用 mock 测试，或记录手工验证路径。

验收：

- 非管理员被拒绝。
- 管理员能添加角色、触发同步、查看状态。

### Step 8：从详情发现角色并回填队列

目标：保存详情后，将双方角色加入同步队列，形成数据扩展能力。

改动范围：

- `src/services/jx3/jjc_match_data_sync.py`
- 可能复用 `RoleIdentityRepo` / `JjcCacheRepo` 的现有身份写入能力。

要求：

- 来源标记为 `match_detail`。
- 已存在角色只补充身份字段和来源，不重置水位。
- 手动添加的优先级不能被自动发现覆盖降低。
- 缺少 `global_role_id` 时使用 `zone + role_id`，再退到 `server + role_name`。

测试：

- 详情 6 个玩家入队。
- 已有玩家不重置进度。
- 手动来源优先级不被覆盖。

验收：

- 一个角色的对局详情能带出更多待同步角色。

### Step 9：状态查询与暂停恢复

目标：让管理员能看到同步任务是否健康，并控制执行。

能力：

- 查询 pending/syncing/exhausted/cooldown/failed/disabled 数量。
- 查询最近一轮摘要。
- 查询最近错误样本。
- 暂停后 `/jjc同步开始` 不执行实际同步。
- 恢复后允许执行。

测试：

- 状态聚合 repo/service 单测。
- 暂停恢复状态读写单测。

验收：

- QQ `/jjc同步状态` 输出足够判断当前是否继续同步。

### Step 10：运行文档与手工回归

目标：补齐操作手册和回归步骤。

改动范围：

- `docs/references/runbook.md`
- `docs/tasks/in-progress/jjc-ranking-role-inspect.md` 或新增独立 task 文档

内容：

- 管理员命令示例。
- 首次同步示例。
- 增量同步示例。
- 服务重启后的恢复预期。
- 常见错误和处理方式。

验收：

- 不看代码也能知道如何添加角色、启动同步、查看状态、重置角色。

### Step 11：最终验证

自动验证：

```bash
python -m unittest <新增同步相关测试>
python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration tests.test_scripts_jjc_snapshot
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/infra/mongo.py
```

手工验证：

```text
/jjc同步添加 <服务器> <角色名>
/jjc同步状态
/jjc同步开始 incremental
/jjc同步状态
```

验收：

- 所有新增自动测试通过。
- 现有 JJC 对局详情和 snapshot 测试通过。
- 手工命令能添加角色、触发同步并看到状态变化。

## 验收标准

- QQ 管理员可以添加待同步角色。
- QQ 管理员可以触发一轮同步。
- 非管理员无法触发同步相关命令。
- 新角色可以尽量同步完整个本赛季。
- 已完整同步过的角色可以按时间水位增量同步。
- 服务重启后可恢复 `syncing` / `detail_syncing` 中断状态。
- 对局详情保存到现有 `jjc_match_detail`，并按 `match_id` 幂等。
- 详情中的对战角色能进入后续同步队列。
- 官方接口请求前有随机 sleep，规则与竞技排名查询保持一致。
- 第一阶段不包含统计、强弱分析、职业分布计算。
