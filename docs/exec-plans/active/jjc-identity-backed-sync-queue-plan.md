# JJC 对局身份投影与 `_id` 关联同步队列改造计划

状态：方案待确认
更新时间：2026-05-25

## 首轮方案审计修订摘要

2026-05-25 子 agent 审计后，本计划补充以下约束，作为后续实现的硬性依据：

- `role_identities._id` 是新队列关联主键，投影链路必须使用保留 `_id` 的 repo 方法；不得依赖当前会 `pop("_id")` 的兼容返回。
- `_sync_match_detail()` 的保存/投影链路不得再把 `_enrich_detail_with_indicator()` 作为入队前置；入队不要求 SK01 `global_role_id`。
- `JjcSyncRepo` 队列相关方法必须整体迁移到 `identity_id`，包括领取、入队、续租、释放、重置、优先级、单角色领取和分页查询。
- 新旧队列 collection 切换必须先引入 `_queue_col()` 抽象，再执行迁移和默认集合切换，回滚不能只停留在文档说法。
- 页面查看对局、缓存命中 replay 补全后重存、缓存 miss 首次保存、排名预热、同步 worker、历史脚本更新详情等入口必须逐项判定是否投影。

## 背景

当前页面查看对局接口 `GET /api/jjc/ranking-stats/match-detail` 会通过 `JjcRankingInspectService.get_match_detail()` 拉取或读取 `jjc_match_detail` 缓存，但不会把对局玩家写入 `role_identities`，也不会把玩家加入同步队列。同步 worker 路径会在 `_sync_match_detail()` 中调用 `_enqueue_players_from_detail()`，写入身份表和 `jjc_sync_role_queue`，但现有队列文档仍以 `identity_key` 为业务关联键，并且可执行队列写入要求 SK01 `global_role_id`，导致同步详情时仍可能为每个对局玩家补打 indicator/person-history。

本计划将“保存可查看的对局详情”统一视为一个身份投影入口：只要某个入口保存了可解析的对局详情，就必须将双方玩家已知身份字段写入 `role_identities`，并确保对应角色存在于新的 `_id` 关联同步队列中。新的同步队列以 `role_identities._id` 为唯一关联，不再要求入队前已有 SK01 `global_role_id`；worker 领取角色后再基于身份表已有的 server/name/zone/game_role_id 等字段刷新 indicator，拿到 SK01 `global_role_id` 后查询战局历史。

## 目标

- 页面查看对局、同步 worker、统计预热等所有会保存 `jjc_match_detail` 的入口，都在保存成功后投影对局玩家身份。
- 投影时保存当前详情已经能可靠获得的字段：`global_id`、`game_role_id`/`role_id`、`zone`、`server`、纯角色名、`person_id`、可能已有的 SK01 `global_role_id`。
- 投影写入遵守 `role_identities.role_info_observed_match_time` 时间水位：旧对局不得覆盖较新身份画像；旧对局只允许补齐缺失字段。
- 新建同步队列集合，以 `role_identities._id` 作为唯一关联字段，不再以 `global_role_id` 或 `identity_key` 作为主关联。
- 写迁移脚本，把旧 `jjc_sync_role_queue` 数据迁移到新集合，并保留同步水位、状态、优先级、租约/冷却相关字段。
- 将同步队列所有读写改到新集合；旧集合仅作为迁移源和回滚保留。
- worker 领取角色后先从 `role_identities` 读取当前身份字段，调用 indicator 刷新 SK01 `global_role_id`，更新 `role_identities`，再用最新 SK01 查询推栏战局历史。

## 非目标

- 不改变 `jjc_match_detail` 原始缓存结构；详情快照仍保存推栏/replay 原始可展示数据。
- 不在对局保存投影阶段主动调用 indicator；投影只使用已随详情/replay/person 已知的数据。
- 不删除旧 `jjc_sync_role_queue` 集合；首版保留用于回滚和迁移审计。
- 不重新设计 worker 心跳、全局暂停、详情租约、失败退避和页面展示的整体交互，只将其关联键与集合切换到新队列。
- 不用旧对局推断当前转服/改名后的最新身份；严格按对局时间水位保护已有画像。

## 核心业务规则

### 对局保存后的身份投影

- 新增领域用例，例如 `JjcMatchDetailIdentityProjectionService.project_saved_match_detail(match_id, payload, source)`。
- 投影入口接受已保存或即将保存的详情 payload，支持当前两类结构：
  - 页面/inspect 缓存结构：`{"match_id": ..., "detail": {...}, "replay": ...}`
  - 推栏原始详情结构：`{"data": {"detail": {...}}}` 或已 `asdict()` 后的 `detail`。
- 从 `detail.team1.players_info`、`detail.team2.players_info` 提取玩家；先用 replay 合并得到的数字 `global_id`，其次使用详情已有 `global_id`、`role_id`、`zone`、`server`、`person_id`、`global_role_id`。
- `players_info[].role_name` 写入身份表前必须规范化为纯角色名：仅当最后一个 `·` 右侧等于当前 `server` 时拆掉服务器后缀；原始详情不改。
- `match_time` 优先取 `detail.match_time`，缺失时取调用方传入的 fallback；没有对局时间时只补缺失字段，不覆盖已有非空画像字段。
- `role_identities` upsert 返回或可再次解析得到目标身份文档 `_id`，投影用该 `_id` upsert 新同步队列候选。
- 投影应幂等：重复查看同一对局、同步 worker 重试、统计预热重复保存，不得创建重复 identity 或重复队列记录。
- 投影失败不应导致页面接口整体失败，但要记录 warning，并在 API `data.cache` 同级返回非阻塞字段 `projection_error=true`、`projection_message=<摘要>`；同步 worker 内同样不因队列投影失败回滚已保存详情，只记录 `projection_error` 并继续 mark saved。

### 对局保存入口清单

实现前必须按下表逐项接入或显式排除。凡是保存了可解析 `detail.team*.players_info` 的入口，都必须调用投影服务；不可用详情或只保存 replay 片段的脚本入口需要明确是否重放完整详情投影。

| 入口 | 现有位置 | 行为 | 投影要求 |
|---|---|---|---|
| 页面查看对局，缓存 miss 首次保存 | `src/services/jx3/jjc_ranking_inspect.py:get_match_detail()`，`cache_repo.save_match_detail()` 首次写入 | 拉取推栏详情、补 replay、写 `jjc_match_detail` | 保存成功后立即投影；`detail=None/unavailable` 不投影，记录 `projection_skipped=no_detail` |
| 页面查看对局，缓存 hit 但 replay 补全后重存 | `src/services/jx3/jjc_ranking_inspect.py:get_match_detail()` 缓存命中分支 | 对旧缓存补 replay 并重新保存 | 重存成功后投影，确保历史缓存可补齐身份和队列 |
| 排名/统计预热保存对局 | `src/services/jx3/jjc_ranking.py:_warmup_inspect_cache_from_kungfu_detail()` | 从心法详情预热 match detail 缓存 | 保存成功后投影 |
| 同步 worker 保存对局 | `src/services/jx3/jjc_match_data_sync.py:_sync_match_detail()` | 同步角色历史时保存详情 | replay 补全后、mark saved 前投影；不得依赖 SK01 才入队 |
| 历史脚本补 replay | `scripts/backfill_jjc_role_id_from_match_replay.py:persist_replay_to_match_detail()` | 只更新 `data.replay` | 脚本本身不作为在线投影入口；迁移后新增可选 `--reproject-match-detail` 或单独重放脚本，从完整 `jjc_match_detail` 重放投影 |
| 其他直接调用 `JjcInspectRepo.save_match_detail()` 的新增入口 | 后续代码 | 任意保存完整详情 | 新增代码必须同步接入投影；测试通过入口清单防漏 |

投影调用不放在 `JjcInspectRepo.save_match_detail()` 内部首版实现，避免存储层反向依赖 service；但 `JjcInspectRepo` 的调用方必须在保存成功后显式调用投影。后续如果要从 repo 层统一兜底，应改为通过可注入 callback，不能让 storage 依赖 services。

### 身份时间水位

- `role_identities.upsert_from_match_detail()` 继续作为唯一身份写入口之一，增强返回值以便调用方拿到 `_id`、`identity_key` 和是否发生画像覆盖。
- 为避免破坏旧调用，`RoleIdentityRepo` 增加专用方法或参数：
  - 推荐新增 `upsert_from_match_detail_with_id(...)`、`resolve_best_identity_with_id(...)`、`get_by_id(identity_id)`、`refresh_indicator_fields_by_id(...)`。
  - 旧 `upsert_from_match_detail()`、`resolve_best_identity()` 返回结构保持兼容，仍可去掉 `_id`。
  - 新方法返回文档必须包含原生 `ObjectId` `_id`，并额外可提供 `identity_id_str` 仅供日志/API。
  - 投影服务和新队列 repo 只能使用保留 `_id` 的方法。
- 对局来源只有 `observed_match_time > existing.role_info_observed_match_time` 时允许覆盖当前画像字段。
- 当 `observed_match_time <= existing.role_info_observed_match_time` 时：
  - 不覆盖 `server`、`name`、`zone`、`game_role_id`、`role_id`、`global_role_id`、`person_id` 等已有非空画像字段。
  - 可以补齐 existing 中为空、而当前详情有值的字段。
  - 仍更新 `sources`、`last_seen_at` 等不会污染当前画像的追踪字段。
- 如果同一玩家通过 `global_id` 升级身份，需要沿用现有 `identity_key` 升级/aliases 规则，并确保新队列记录关联到最终身份 `_id`。

### 字段口径

- `global_id`：JJC 稳定身份 ID，来自 match/replay `players[].global_role_id` 或详情中已合并的数字 ID；不得与 SK01 混用。
- `global_role_id`：SK01 全局角色 ID，仅用于请求推栏 match-history，由 indicator 或兼容兜底获得。
- `game_role_id`：身份表标准角色 ID 字段。对局详情/replay 中的 `role_id` 写入身份时映射为 `game_role_id`，同时可保留 `role_id` 作为兼容字段。
- `role_id`：队列和 API 中仅作为兼容展示/旧数据字段；新逻辑构造 indicator 请求优先读 `game_role_id`，缺失时再回退 `role_id`。
- `identity_key`：仍保留为身份升级、别名和展示诊断字段，但不是新队列主关联和租约 fence。
- `identity_id`：新队列唯一业务关联字段，repo 内部使用 `ObjectId`，service/API 输出统一转为字符串。

### 新同步队列

- 新集合建议命名：`jjc_sync_identity_queue`。
- 唯一业务关联：`identity_id`，类型使用 `ObjectId`，对应 `role_identities._id`。
- 队列可冗余展示字段：`identity_key`、`server`、`name`、`normalized_server`、`normalized_name`、`global_id`、`global_role_id`、`game_role_id`、`role_id`、`person_id`、`zone`。这些字段只做展示、查询和诊断；worker 每次领取后仍以 `identity_id` 回读 `role_identities` 为准。
- 新增记录默认 `status='pending'`、`source='match_detail'`、自动发现优先级建议沿用 `priority=-10`；手动添加继续使用较高优先级。
- 入队不要求 `global_role_id`。只要可以 upsert 到一条 `role_identities` 并得到 `_id`，就可以写入队列候选。
- 旧队列中的 `full_synced_until_time`、`oldest_synced_match_time`、`latest_seen_match_time`、`history_exhausted`、`last_cursor`、`status`、`queued_at`、`queue_*`、`priority`、`fail_count`、`last_error`、`next_sync_after` 等字段迁移到新集合。
- 租约字段 `lease_owner`、`lease_expires_at` 可迁移，但正式迁移建议先暂停 worker，确认没有活跃 `syncing` 后执行；如强制迁移活跃租约，脚本需提供 `--include-syncing` 显式开关。

### 队列 repo 方法迁移表

`JjcSyncRepo` 必须先新增 `_queue_col()`，运行时代码只通过该方法访问角色队列集合。新代码的生产默认 `_queue_col()` 固定指向 `jjc_sync_identity_queue`；旧集合只作为迁移源和代码版本回滚目标，不要求新 `identity_id` repo 方法兼容旧集合。

| 现有方法/职责 | 旧主键 | 新主键与过滤 | 说明 |
|---|---|---|---|
| `_leased_role_filter(identity_key, lease_owner, now)` | `identity_key` | `_leased_queue_filter(identity_id, lease_owner, now)`，过滤 `identity_id + status='syncing' + lease_owner + lease_expires_at > now` | 所有租约 fence 统一改为 `identity_id` |
| `upsert_role(...)` | 计算/迁移 `identity_key` | `upsert_identity_queue_candidate(identity_doc, source, priority, ...)`，按 `identity_id` upsert | 入队候选不要求 SK01；同步水位不因重复投影重置 |
| `enqueue_next_roles(...)` | 集合内角色文档 | 仍按 `status/priority/next_sync_after` 选候选，但返回包含 `identity_id` | 排序规则不变 |
| `enqueue_role(identity_key, ...)` | `identity_key` | `enqueue_identity(identity_id, ...)` | 手动入队和 API 入队使用 |
| `claim_queued_role(...)` | 返回含 `identity_key` | 原子领取 `status='queued'`，设置租约，返回含 `identity_id` | worker 后续用 `identity_id` 读身份表 |
| `claim_specific_role(identity_key, ...)` | `identity_key` | `claim_specific_identity(identity_id, ...)` | `sync_single_role()` 使用 |
| `renew_role_lease(identity_key, ...)` | `identity_key + lease_owner` | `renew_identity_lease(identity_id, ...)` | worker heartbeat/详情处理过程中续租 |
| `release_role_success/failure/interrupted(identity_key, ...)` | `identity_key + lease_owner` | `release_identity_success/failure/interrupted(identity_id, ...)` | 成功/失败/暂停释放都必须 fence 当前租约 |
| `reset_role_progress(identity_key)` | `identity_key` | `reset_identity_progress(identity_id)`，保留按 server/name 查到 identity 后再 reset | 管理入口保持按名称查找 |
| `update_role_priority(identity_key, ...)` | `identity_key` | `update_identity_priority(identity_id, ...)` | 优先级更新不依赖 `identity_key` |
| `get_role_by_name(...)` / `list_queue(...)` | 队列冗余 name | 继续按冗余 `normalized_server/name` 查询；返回 `identity_id` 字符串 | 用户入口不暴露 ObjectId 类型 |
| `update_role_identity_fields_and_key(...)` | 迁移 `identity_key` | 替换为 `sync_identity_snapshot(identity_doc, lease_owner=None)` | 只同步队列冗余字段，不改变队列主键 |

旧方法可保留一层兼容 wrapper，但内部必须先解析 `identity_key -> role_identities._id -> identity_id`，并标注为迁移期使用；新 service 代码不得继续调用旧主键方法。兼容 wrapper 仍访问新集合，不作为旧集合运行适配层。

### worker 查询身份与 indicator

- `claim_queued_role()` 从新集合领取角色后，返回 `identity_id` 和队列文档。
- `_sync_one_role()` 开始时必须通过 `identity_id` 从 `role_identities` 读取最新身份，而不是信任队列冗余字段。
- worker 先调用 indicator 刷新 SK01 `global_role_id`：
  - 优先使用 `role_identities.zone + game_role_id + server` 构造 indicator 请求；`game_role_id` 缺失时才回退 `role_id`。
  - 新增 `global_role_id_refreshed_at` 和 `global_role_id_refresh_source` 字段。默认规则：领取后若已有 SK01 且 `global_role_id_refreshed_at` 距当前不超过 24 小时，可复用；否则必须刷新 indicator。24 小时作为首版常量，后续再按需要配置化。
  - 若字段不足以请求 indicator，才按现有兼容逻辑尝试 inspect 身份解析或 person-history 兜底；person-history/inspect resolver 只能补足 indicator 请求字段或最后兜底 SK01，不得替代首选 indicator 刷新。
  - indicator 返回后写回 `role_identities.upsert_from_indicator()` 或新增专用刷新方法，并同步更新队列冗余字段。
  - 若 indicator 返回 SK01 与现有字段冲突，按身份表冲突规则记录 warning，不直接用旧对局覆盖较新身份。
- 拿到最新 SK01 `global_role_id` 后，调用现有 match-history 同步流程；若仍无法获得 SK01，则释放为失败或冷却，错误信息明确为“indicator 无法补全 global_role_id”。
- `_sync_match_detail()` 保存/投影链路必须移除 `_enrich_detail_with_indicator()` 调用；详情可继续通过 replay 补 `global_id`，随后调用统一身份投影。若未来要为展示增强重新引入 indicator 补水，必须在投影之后异步执行，且不得影响是否写 identity/queue。

### `jjc_sync_match_seen` 关联字段

- 新增 `source_identity_id`，类型 `ObjectId`，关联首次发现对局的新队列身份。
- 保留 `source_identity_key` 作为 legacy 诊断字段和旧数据兼容，不再作为 join 主键。
- `mark_match_seen/discover_match` 类方法新增 `source_identity_id` 参数；worker 调用时从当前队列角色传入。
- 索引新增 `idx_source_identity_id`；旧 `idx_source_identity_key` 保留至少一个版本周期。
- 迁移脚本可按旧 `source_identity_key` 尽力回填 `source_identity_id`，无法唯一解析时保留空值并输出统计。
- 保留“首次发现身份”语义：`mark_match_discovered()` 对新对局仍只在 insert 时写来源；对旧记录只允许在 `source_identity_id` 为空且能从旧 `source_identity_key` 唯一解析时补写，不得因后续其他角色再次发现同一 match 覆盖首次来源。

### worker 心跳与展示字段

- `jjc_sync_workers` 新增 `current_identity_id`，类型存储为 `ObjectId` 或字符串均可，但 service/API 输出统一为字符串。
- 保留 `current_identity_key` 作为 legacy 展示和排查字段，worker 心跳同时写入当前身份的 `identity_id`、`identity_key`、`server`、`name`。
- `list_workers()`、`queue_status()` 和 `public/jjc-sync-queue.html` 展示层新增 `current_identity_id`，旧字段继续展示至少一个版本周期。
- 相关测试覆盖 `_heartbeat_worker()` 在当前角色来自新队列时写入 `current_identity_id`，并确认 JSON 输出不会泄漏原生 `ObjectId`。

## 数据结构与索引

### 新集合 `jjc_sync_identity_queue`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `identity_id` | ObjectId | 关联 `role_identities._id`，业务唯一 |
| `identity_key` | string | 关联身份的当前 `identity_key`，仅冗余展示和迁移诊断 |
| `server` / `name` | string | 当前展示服务器和纯角色名，冗余自身份表 |
| `normalized_server` / `normalized_name` | string | 规范化查询字段 |
| `global_id` | string/null | JJC 稳定身份 ID，冗余自身份表 |
| `global_role_id` | string/null | SK01 ID，worker 刷新后冗余 |
| `game_role_id` / `role_id` | string/null | indicator 请求所需角色 ID |
| `person_id` | string/null | 推栏个人 ID |
| `zone` | string/null | 区服分区 |
| `identity_source` | string/null | 最近身份刷新来源 |
| `source` | string | 队列来源：`manual`、`ranking`、`match_detail`、`migration` 等 |
| `priority` | int | 调度优先级 |
| `status` | string | `pending`、`queued`、`syncing`、`exhausted`、`cooldown`、`failed`、`disabled` |
| `queued_at` | float/null | 最近排队时间 |
| `queue_batch_id` / `queue_mode` / `queue_source` | string/null | 最近入队信息 |
| `season_id` | string/null | 当前赛季标识 |
| `season_start_time` | int | 当前赛季开始时间 |
| `full_synced_until_time` | int/null | 已完整覆盖到的最新时间点 |
| `oldest_synced_match_time` | int/null | 已同步到的最早对局时间 |
| `latest_seen_match_time` | int/null | 最近看到的最新对局时间 |
| `history_exhausted` | bool/null | 本赛季是否回溯完成 |
| `last_cursor` | int | 最近处理 cursor |
| `lease_owner` / `lease_expires_at` | string/null, float/null | 执行租约 |
| `last_synced_at` / `next_sync_after` | float/null | 同步时间与冷却 |
| `fail_count` | int | 连续失败次数 |
| `last_error` | string/null | 最近错误 |
| `created_at` / `updated_at` | float | 创建和更新时间 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_identity_id` | `identity_id` | unique |
| `idx_identity_key` | `identity_key` | 普通索引 |
| `idx_status_priority_next_sync_after` | `status`, `priority`, `next_sync_after` | 普通复合索引 |
| `idx_status_priority_queued_at` | `status`, `priority`, `queued_at` | 普通复合索引 |
| `idx_normalized_server_name` | `normalized_server`, `normalized_name` | 普通复合索引 |
| `idx_global_id` | `global_id` | 普通索引 |
| `idx_global_role_id` | `global_role_id` | 普通索引 |
| `idx_lease_expires_at` | `lease_expires_at` | 普通索引 |

### 旧集合 `jjc_sync_role_queue`

- 迁移完成后运行时代码不再读写该集合。
- 文档保留为 legacy，迁移脚本默认只读旧集合、upsert 新集合。
- 回滚策略是“代码版本回滚”，不是让新代码直接切回旧集合。旧集合文档没有 `identity_id`，不能由新 `identity_id` repo 方法直接 claim/renew/release。

### 集合切换顺序

1. 代码阶段 A：新增 `jjc_sync_identity_queue` 索引、`_queue_col()` 抽象；新代码默认指向新集合，旧集合只作为迁移源。
2. 代码阶段 B：实现新队列写入和 worker 新主键逻辑；旧集合不承担新代码运行时读写。
3. 数据阶段：暂停 worker，执行 dry-run，正式迁移，校验状态分布和样本水位。
4. 切换阶段：生产默认 `_queue_col()` 指向 `jjc_sync_identity_queue`，恢复 worker。
5. 回滚阶段：暂停 worker，运行新集合到旧集合的反向同步脚本，将新集合中新推进的水位、状态、候选角色尽力写回 `jjc_sync_role_queue` 的 `identity_key` 模型；然后回滚代码版本到旧队列实现并恢复 worker。
6. 回滚后补偿：代码版本回滚后，页面查看/详情投影不会继续写新集合。若回滚前新集合已产生页面投影候选，必须通过反向同步脚本写回旧集合；若需要从详情缓存重新发现候选，运行 `jjc_match_detail` 重放投影到旧集合的兼容脚本。

## 模块与文件落位

- `src/services/jx3/match_detail_identity_projection.py`（新增）
  - 提供对局详情玩家提取、身份 upsert、队列候选 upsert 的业务编排。
  - 不依赖 NoneBot、FastAPI 或渲染。
- `src/services/jx3/jjc_ranking_inspect.py`
  - `get_match_detail()` 在 `cache_repo.save_match_detail()` 成功后调用投影服务。
  - 缓存命中但 replay 补全导致重新保存时，也调用投影，确保历史缓存补齐身份和队列。
- `src/services/jx3/jjc_ranking.py`
  - `_warmup_inspect_cache_from_kungfu_detail()` 保存 match detail 缓存后调用投影。
- `src/services/jx3/jjc_match_data_sync.py`
  - `_sync_match_detail()` 保存详情链路改用统一投影，删除“无 SK01 不入队”的限制。
  - `_sync_one_role()` 改为基于 `identity_id` 读取身份并先刷新 indicator。
  - `queue_status()`、`list_queue()`、`set_role_priority()`、`add_role()`、`sync_single_role()` 改为新队列 repo 方法。
- `src/storage/mongo_repos/role_identity_repo.py`
  - 增加保留 `_id` 的专用 upsert/resolve/get/refresh 方法，旧方法返回保持兼容。
  - 增加按 `_id` 读取身份、按 `_id` 刷新 indicator 字段、时间水位判断单测。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 新增 `_queue_col()`，生产默认固定 `jjc_sync_identity_queue`；旧集合不作为新代码运行时配置目标。
  - 所有对外方法参数从 `identity_key` 改为 `identity_id`；保留 `identity_key` wrapper 只用于迁移期兼容，不给新 service 调用。
  - 新增 `upsert_identity_queue_candidate(identity_doc, source, priority, season...)`。
- `src/infra/mongo.py`
  - 为 `jjc_sync_identity_queue` 创建索引。
- `scripts/migrate_jjc_sync_identity_queue.py`（新增）
  - 从旧 `jjc_sync_role_queue` 读取，解析/查找/必要时创建 `role_identities`，按 `identity_id` upsert 新队列。
  - 支持 `--dry-run`、`--limit`、`--skip-syncing`、`--include-syncing`、`--verbose`。
  - 提供反向同步子命令或独立脚本，将新队列的水位/候选尽力写回旧 `identity_key` 队列，用于代码版本回滚前补偿。
- `scripts/backfill_jjc_role_id_from_match_replay.py`
  - 更新测试和写入逻辑：不再要求 SK01 `global_role_id` 才写队列，改为写新集合并关联 identity `_id`。
- `src/api/routers/jjc_sync.py`、`public/jjc-sync-queue.html`、QQ handler、CLI
  - API 返回字段保留 `identity_key` 兼容展示，同时新增 `identity_id`。
  - worker 状态返回字段保留 `current_identity_key`，新增 `current_identity_id`。
  - 用户可见搜索仍按 server/name/status 工作。
- 文档：
  - `docs/design-docs/database-design.md` 增加新集合、标注旧集合 legacy、更新脚本清单。
  - `README.md` 与 `docs/references/runbook.md` 更新迁移和回归说明。

## 迁移方案

1. 部署前检查：
   - 暂停 JJC 同步 worker，确认 `jjc_sync_role_queue.status='syncing'` 数量为 0。
   - 备份旧集合：`jjc_sync_role_queue`、`role_identities`、`jjc_sync_match_seen`。
2. 运行 dry-run：
   - 统计旧队列总数、可解析到现有 identity 的数量、需要新建 identity 的数量、缺少 server/name 且无法迁移的数量、潜在 duplicate `identity_id` 数量。
3. 正式迁移：
   - 对每条旧队列，优先按 `global_id` 查 `role_identities`，再按 `identity_key`、`global_role_id`、`zone+role_id/game_role_id`、`normalized_server+normalized_name` 查找。
   - 找不到时用旧队列字段创建 `role_identities`，来源标记 `sync_queue_migration`。
   - 以最终身份 `_id` upsert `jjc_sync_identity_queue`，复制同步水位和状态字段。
   - 对同一 `identity_id` 多条旧队列冲突：保留水位更深、`last_synced_at` 更新或优先级更高的记录；冲突样本写日志和 summary JSON。
4. 切换运行时代码：
   - repo 默认 collection 指向新集合。
   - 页面/API/worker 读新队列。
   - 旧集合只读不写。
5. 回填 `jjc_sync_match_seen.source_identity_id`：
   - 按旧 `source_identity_key` 解析到新队列/身份表；唯一命中则写入 `source_identity_id`。
   - 无法唯一解析的记录保留旧字段，输出待审计样本。
   - 只补空 `source_identity_id`，不覆盖已有首次发现来源。
6. 验证通过后恢复 worker。
7. 生成回滚补偿脚本 dry-run summary，确认如需代码版本回滚时可将新集合候选和水位同步回旧集合。

## 实施步骤

1. 存储与索引
   - 新增新集合索引。
   - 扩展 `RoleIdentityRepo` 的保留 `_id` 方法和按 `_id` 读取/刷新能力。
   - 改造 `JjcSyncRepo` 增加 `_queue_col()`，并按方法迁移表以 `identity_id` 为主键。
   - 扩展 `jjc_sync_match_seen` 写入 `source_identity_id`。

2. 对局身份投影
   - 新增投影 service，统一解析详情玩家、调用身份 upsert、写队列候选。
   - 按“对局保存入口清单”将 `JjcRankingInspectService.get_match_detail()` 两个保存点、`JjcRankingService` 预热保存入口、`JjcMatchDataSyncService._sync_match_detail()` 接入投影。
   - 替换 `_enqueue_players_from_detail()` 的队列写入职责；移除对 SK01 `global_role_id` 的入队硬限制。
   - 明确历史脚本不在线投影，新增重放投影选项或独立重放脚本。

3. worker 身份刷新
   - `_sync_one_role()` 领取新队列记录后按 `identity_id` 读身份。
   - 按冷却规则调用 indicator 刷新 SK01，并把结果写回身份表和队列冗余字段。
   - 用刷新后的 SK01 调用现有 match-history 查询。

4. 入口与展示
   - QQ/CLI/API 的队列状态、分页、添加、优先级调整改用新队列。
   - 页面保留原展示字段，新增 `identity_id` 和 worker `current_identity_id` 便于排查。

5. 迁移脚本
   - 实现 dry-run、正式迁移、summary 输出。
   - 实现反向同步 dry-run/正式执行，用于代码版本回滚前把新集合候选和水位同步回旧集合。
   - 增加单测覆盖旧 identity_key、global_id、name fallback、重复身份合并和缺字段跳过。

6. 文档联动
   - 更新数据库设计、README API/页面说明、runbook 迁移和回滚步骤。
   - 本计划状态更新为“实施中/已验证/待提交”。

## 验证计划

- 单元测试：
  - `tests.test_role_identity_repo`：旧对局不覆盖新画像、新对局覆盖、upsert 返回 `_id`。
  - 新增 `tests.test_jjc_match_detail_identity_projection`：页面 payload、同步 payload、replay global_id、无 SK01 仍写队列、幂等重复投影。
  - `tests.test_jjc_sync_repo`：新集合 `identity_id` 唯一、入队排序、领取租约、续租、释放成功/失败/中断、重置、优先级、collection 切换。
  - `tests.test_jjc_match_data_sync`：worker 先按 `_id` 读 identity、按冷却规则刷新 indicator、再查询 match-history；无 SK01 的队列记录可被领取；`_sync_match_detail()` 不再调用 `_enrich_detail_with_indicator()`。
  - `tests.test_jjc_sync_match_seen` 或现有 repo 测试：首次发现写入 `source_identity_id`；第二个 identity 再发现同一 `match_id` 不覆盖 `source_identity_id/source_identity_key/source_server/source_role_name`；migration/backfill 只在 `source_identity_id` 为空且旧 key 唯一解析时补写。
  - worker 状态/API 测试：`current_identity_id` 输出为字符串，`current_identity_key` 兼容保留。
  - 新增迁移脚本测试：dry-run 统计、旧队列迁移到新队列、重复 identity 合并、新队列反向同步旧队列。
- 编译检查：
  - `python -m py_compile src/services/jx3/match_detail_identity_projection.py src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/storage/mongo_repos/role_identity_repo.py src/infra/mongo.py scripts/migrate_jjc_sync_identity_queue.py`
- 回归命令：
  - `python -m unittest tests.test_role_identity_repo tests.test_jjc_sync_repo tests.test_jjc_match_data_sync tests.test_jjc_sync_router tests.test_jjc_match_detail_snapshots tests.test_jjc_match_detail_hydration`
  - 新增测试文件后加入同一回归集合。
- 手工验证：
  - 页面查看一个未同步过的对局后，确认双方玩家写入 `role_identities`，并在 `jjc_sync_identity_queue` 有 pending 候选。
  - 旧对局再次查看不会覆盖身份表中更新的 server/name/zone/role_id。
  - 迁移 dry-run 与正式迁移数量一致，迁移后队列页面数量与状态分布符合预期。
  - worker 领取一个只有 `identity_id`、无 `global_role_id` 的队列记录，先刷新 indicator，再同步战局历史。

## 风险与回滚

- 风险：`ObjectId` 在 API JSON 化和测试 fake collection 中需要统一转换。处理：service/API 输出时转字符串，repo 内部保持 ObjectId。
- 风险：旧队列多条记录可能映射到同一 identity。处理：迁移脚本输出冲突 summary，并按更保守水位合并；高风险样本人工确认。
- 风险：worker 启动时 indicator 压力集中。处理：保留现有 sleep/串行锁，必要时增加 indicator 刷新冷却字段，避免同一 identity 频繁刷新。
- 风险：页面查看对局投影失败会导致队列漏人。处理：记录投影错误，提供后续脚本从 `jjc_match_detail` 批量重放投影。
- 回滚：旧集合保留不删；如果新队列切换异常，先暂停 worker，执行新队列到旧队列的反向同步 dry-run 和正式同步，再回滚代码版本到旧 `identity_key` 队列实现。新代码不支持直接把 `_queue_col()` 指向旧集合运行。回滚后可能重复扫描部分对局，但 `jjc_sync_match_seen` 和 `jjc_match_detail` 幂等可降低外部重复请求。若反向同步无法覆盖所有候选，运行 `jjc_match_detail` 重放投影到旧集合的兼容脚本。

## 待确认问题

- 新集合名称是否采用 `jjc_sync_identity_queue`，还是直接复用旧业务名但 Mongo 集合改为 `jjc_sync_role_queue_v2`。
