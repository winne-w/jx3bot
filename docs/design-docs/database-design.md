# 数据库设计

更新时间：2026-05-11

本文是当前项目数据库结构的维护文档。以后新增、删除、重命名集合或字段，调整索引、TTL、迁移脚本、存储归属时，必须同步更新本文。

## 总览

- 当前主存储是 MongoDB，连接串来自 `config.MONGO_URI`，可由环境变量 `MONGO_URI` 或 `runtime_config.json` 覆盖。
- Mongo 初始化入口是 `src/infra/mongo.py:init_mongo()`，启动时会连接数据库、执行 `ping`，并通过 `_ensure_indexes()` 幂等创建索引。
- 存储访问边界优先放在 `src/storage/mongo_repos/`。历史上仍有 `src/services/jx3/jjc_cache_repo.py` 直接封装 JJC 缓存访问，修改时应保持调用方兼容，避免在 handler 中直接读写 Mongo。
- 集合采用 MongoDB 默认 `_id`，业务唯一性由下表索引保证。文档字段没有强 schema 校验，字段契约以本文、repo 写入逻辑和迁移脚本共同约束。

## 维护规则

- 数据库相关改动必须同步修改本文，包括集合、字段、索引、TTL、数据类型、迁移脚本和读写 repo 的变化。
- 新增持久化能力优先新增或扩展 `src/storage/mongo_repos/`，不要在 `plugins`、handler、API router 中散写 `db.collection`。
- 新增索引必须写入 `src/infra/mongo.py:_ensure_indexes()`，并在本文的集合章节记录索引名、字段和唯一性。
- 有历史 JSON 或文件缓存需要迁移时，迁移脚本放在 `scripts/`，脚本说明要写明源路径、目标集合和幂等键。
- 时间字段应优先使用 Unix 秒级时间戳；若使用 Mongo `datetime` 用于 TTL，必须在字段说明中明确类型和原因。
- **TTL 字段约束**：MongoDB TTL 索引仅对 `Date` 类型字段生效，对 `float`/`int` 类型字段创建 TTL 索引实际不会触发自动删除。新建集合的 TTL 字段必须使用 `datetime` 类型；旧集合若使用非 `Date` 字段声明了 TTL 索引，应在对应集合描述中标注"TTL 实际不生效"，并在合理时机补 `_dt` 后缀的 Date 冗余字段或由 repo 业务逻辑自行判断过期。
- 群号、QQ 号等外部 ID 当前多数以字符串落库，新增字段应沿用对应集合已有类型，避免同一字段混用数字和字符串。

## 集合设计

### `group_configs`

用途：群配置持久化，替代旧 `groups.json`。用于开服监控、日常推送、群默认服务器等按群配置。

读写归属：

- `src/storage/mongo_repos/group_config_repo.py`
- 迁移脚本：`scripts/migrate_group_configs.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `group_id` | string | 群号，业务唯一键 |
| 其他配置字段 | any | 从旧 `{group_id: config}` 结构展开保存，例如 `servers`、开服推送相关开关等 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_group_id` | `group_id` | unique |

### `reminders`

用途：群提醒任务持久化，支持启动后恢复 pending 任务、取消提醒和完成状态记录。

读写归属：

- `src/storage/mongo_repos/reminder_repo.py`
- 业务入口：`src/plugins/jx3bot_handlers/reminder.py`
- 迁移脚本：`scripts/migrate_reminders.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `reminder_id` | string | 提醒业务 ID，当前由 `uuid.uuid4().hex` 生成 |
| `group_id` | string | 群号 |
| `creator_user_id` | string | 创建提醒的 QQ 号 |
| `mention_type` | string | `user` 或 `all` |
| `message` | string | 提醒内容 |
| `remind_at` | string | 执行时间，格式为 `YYYYMMDDHHMMSS` |
| `created_at` | int | 创建时间 Unix 秒 |
| `status` | string | `pending`、`done`、`canceled` |
| `done_at` | int | 完成时间 Unix 秒，仅完成后写入 |
| `canceled_at` | int | 取消时间 Unix 秒，仅取消后写入 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_reminder_id` | `reminder_id` | unique |
| `idx_group_status` | `group_id`, `status` | 普通复合索引 |
| `idx_status_remind_at` | `status`, `remind_at` | 普通复合索引 |

### `wanbaolou_subscriptions`

用途：万宝楼价格订阅，替代旧 `data/wanbaolou_subscriptions.json`。

读写归属：

- `src/storage/mongo_repos/wanbaolou_sub_repo.py`
- 业务入口：`src/plugins/wanbaolou/`
- 迁移脚本：`scripts/migrate_wanbaolou_subs.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `user_id` | string | 订阅用户 QQ 号 |
| `item_name` | string | 订阅商品名 |
| `price_threshold` | int | 价格阈值 |
| `group_id` | string/null | 订阅所在群，私聊或未知时为 `null` |
| `created_at` | float | 创建或重新启用时间 Unix 秒 |
| `active` | bool | 是否有效；删除订阅时置为 `False` |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_user_id` | `user_id` | 普通索引 |
| `idx_user_item` | `user_id`, `item_name` | unique |

### `status_cache`

用途：状态监控插件的通用缓存集合，存储新闻、技改、福利码、服务器状态和状态历史等小型状态。

读写归属：

- `src/storage/mongo_repos/status_cache_repo.py`
- 业务入口：`src/plugins/status_monitor/storage.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `cache_name` | string | 缓存名，例如 `records_ids`、`news_ids`、`event_codes_ids`、`server_status`、`status_history` |
| `data` | any | 缓存内容 |
| `updated_at` | int | 更新时间 Unix 秒 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_cache_name` | `cache_name` | unique |

### `server_master_cache`

用途：区服主服查询缓存，减少重复请求 `jx3api` 主服接口。

读写归属：

- `src/storage/mongo_repos/server_master_repo.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `key` | string | 查询 key |
| `name` | string | 主服名称 |
| `zone` | string | 大区 |
| `server_id` | string | 区服 ID |
| `cached_at` | int | 缓存写入时间 Unix 秒（⚠ int 类型，TTL 索引不生效） |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_key` | `key` | unique |
| `idx_cached_at` | `cached_at` | TTL 604800 秒（⚠ int 类型，TTL 实际不生效） |

说明：repo 内部也会按 `ttl_seconds` 主动判断过期并删除；TTL 索引因字段类型为 int 不可靠，只作兜底意图声明。若长期保留本集合，应补 `cached_at_dt`（Date 类型）用于真实 TTL。

### `kungfu_cache` **[LEGACY — 已删除]**

> **状态**：本集合已被 `role_identities` + `role_jjc_cache` 替代。运行时代码已移除对本集合的依赖，且历史 `kungfu_cache` 集合已于 2026-04-30 从 MongoDB 删除（删除前文档数 11474）。新代码不应再直接依赖本集合。

用途：JJC 排名中角色心法、武器和队友心法判断缓存，替代旧 `data/cache/kungfu/*.json`。以 `server + name` 为唯一键，但该键不是永久身份主键——同一角色改名/转服后会产生新记录，同一角色也可能因来源不同存在多条记录。

历史归属：

- 历史心法解析逻辑：`src/services/jx3/kungfu.py`
- 历史迁移脚本：`scripts/migrate_kungfu_cache.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `server` | string | 服务器名 |
| `name` | string | 角色名 |
| `kungfu` | string/null | 心法中文名 |
| `kungfu_id` | string/int/null | 推栏返回的心法 ID |
| `weapon` | object/null | 武器详情原始结构 |
| `weapon_checked` | bool | 是否完成武器检查 |
| `teammates` | array | 队友结构列表，包含 `role_name`、`server`、`role_id`、`global_role_id`、`kungfu_id` 等 |
| `teammates_checked` | bool | 是否完成队友心法检查 |
| `cache_time` | float | 缓存时间 Unix 秒（⚠ float 类型不可用于 MongoDB TTL 索引；TTL 依赖 `idx_cache_time` 实际不生效，仅由 repo 业务逻辑判断过期） |
| 其他结果字段 | any | 历史缓存文件和心法解析结果可能携带的附加字段 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_server_name` | `server`, `name` | unique |
| `idx_cache_time` | `cache_time` | TTL 604800 秒（⚠ float 类型，TTL 实际不生效） |

迁移到新集合的说明：

- 迁移脚本：`scripts/migrate_role_identity_and_jjc_cache.py`，支持 dry-run / `--apply` / `--limit`，幂等。
- 运行时业务已不再回退本集合；新集合 miss 时直接查外部接口并回写 `role_identities` / `role_jjc_cache`。
- 本集合已完成历史清理；迁移脚本仍保留用于审计和历史参考。

### `role_identities`

用途：游戏角色身份统一模型。不存心法缓存结果，只维护角色在不同来源（排行榜、indicator、对局详情）中的身份标识及其关联关系。替代 `kungfu_cache` 中以 `server + name` 作为唯一键的弱身份模型。

读写归属：

- `src/storage/mongo_repos/role_identity_repo.py`
- 迁移脚本：`scripts/migrate_role_identity_and_jjc_cache.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `identity_key` | string | 内部主键，按 `identity_key` 生成规则计算，业务唯一 |
| `identity_level` | string | 身份级别：`global`（有 `global_role_id`）、`game_role`（有 `zone + game_role_id`）、`name`（仅 `server + name`） |
| `server` | string | 当前服务器名 |
| `normalized_server` | string | 规范化服务器名（去除空格、统一大小写等） |
| `name` | string | 当前角色名，只保存纯角色名；推栏对局详情里的 `角色名·服务器` 展示名在派生写入时必须先拆掉服务器后缀 |
| `normalized_name` | string | 规范化角色名 |
| `zone` | string/null | 大区，来源于排行榜或 indicator |
| `game_role_id` | string/null | 排行榜常见的角色 ID（`gameRoleId`） |
| `role_id` | string/null | 角色详情或对局详情中的角色 ID |
| `global_role_id` | string/null | 推栏战局历史所需的全局角色 ID |
| `person_id` | string/null | 对局详情中的 person ID |
| `aliases` | array | 历史名称、历史服务器名、旧 `identity_key` 等，支持改名/转服后的回溯查询 |
| `sources` | array | 数据来源列表，取值：`ranking`、`indicator`、`match_detail`、`migrated_kungfu_cache` |
| `profile_observed_at` | datetime/null | 当前 `server` / `name` 所依据的资料观测时间；排行榜/indicator 用查询时间，对局详情用 `match_time` |
| `first_seen_at` | datetime | 首次记录时间 |
| `last_seen_at` | datetime | 最近一次出现时间 |
| `updated_at` | datetime | 最近一次字段更新（如升级 identity_level）时间 |
| `schema_version` | int | schema 版本号 |

`identity_key` 生成规则：

| 优先级 | 条件 | key 格式 | identity_level |
|---|---|---|---|
| 1 | 有 `global_role_id` | `global:{global_role_id}` | `global` |
| 2 | 无 global，有 `zone + game_role_id` | `game:{zone}:{game_role_id}` | `game_role` |
| 3 | 只有名称入口 | `name:{normalized_server}:{normalized_name}` | `name` |

**身份升级规则**：当一条较低级别身份（如 `name` 或 `game_role`）后来获得了更高级别的外部 ID 时，执行升级：

- `name` → `game_role`：从排行榜拿到 `zone + game_role_id` 后，重新计算 `identity_key` 为 `game:{zone}:{game_role_id}`，将旧 `identity_key` 推入 `aliases`。
- `game_role` → `global`：通过 indicator 或对局详情拿到 `global_role_id` 后，重新计算 `identity_key` 为 `global:{global_role_id}`，将旧 `identity_key` 推入 `aliases`。
- 升级后旧 `identity_key` 记录不删除，但标记或合并到新记录。
- 同一 `global_role_id` 不得出现多条记录；同一 `zone + game_role_id` 组合同理。
- `match_detail` 属于历史对局来源，只有当对局 `match_time` 晚于现有 `profile_observed_at` 时才更新当前 `server` / `name`，避免用旧对局覆盖转服/改名后的当前资料。
- 对于 `match_detail` 来源，原始详情里的 `players_info[].role_name` 可以保留推栏展示值；但派生写入 `role_identities.name` 时必须按“仅当最后一个 `·` 右侧等于当前 `server` 才拆分”的规则规范化为纯角色名。

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_identity_key` | `identity_key` | unique |
| `idx_global_role_id` | `global_role_id` | unique, partial（仅 `global_role_id` 不为 null 时） |
| `idx_zone_game_role_id` | `zone`, `game_role_id` | unique, partial（仅 `zone` 与 `game_role_id` 均不为 null 时） |
| `idx_normalized_server_name` | `normalized_server`, `normalized_name` | 普通索引（用于按名称查询入口） |
| `idx_last_seen_at` | `last_seen_at` | 普通索引 |

### `role_jjc_cache`

用途：JJC 角色画像缓存，关联 `identity_key`。从 `kungfu_cache` 中拆分出心法、武器、队友等可变缓存信息，与角色身份模型解耦。

读写归属：

- `src/storage/mongo_repos/role_jjc_cache_repo.py`
- 迁移脚本：`scripts/migrate_role_identity_and_jjc_cache.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `identity_key` | string | 关联 `role_identities.identity_key`，业务唯一 |
| `server` | string | 查询与展示冗余字段 |
| `name` | string | 查询与展示冗余字段 |
| `normalized_server` | string | 规范化服务器名，与 `role_identities` 对齐用于关联查询 |
| `normalized_name` | string | 规范化角色名，与 `role_identities` 对齐用于关联查询 |
| `zone` | string/null | 查询与展示冗余字段 |
| `game_role_id` | string/null | 外部 ID 冗余，便于调试和查询 |
| `role_id` | string/null | 外部 ID 冗余 |
| `global_role_id` | string/null | 外部 ID 冗余 |
| `kungfu` | string/null | 最终判定的心法中文名 |
| `kungfu_id` | string/int/null | 最终判定的心法 ID |
| `kungfu_pinyin` | string/null | 心法拼音 |
| `kungfu_indicator` | string/null | 通过 indicator 接口获取的心法名 |
| `kungfu_match_history` | string/null | 通过战局历史统计获取的心法名 |
| `kungfu_selected_source` | string/null | 最终采用的心法来源：`indicator`、`match_history`、`kungfu_cache` 等 |
| `weapon` | object/null | 武器详情原始结构 |
| `weapon_icon` | string/null | 武器图标 |
| `weapon_quality` | string/int/null | 武器品质 |
| `weapon_checked` | bool | 是否完成武器检查 |
| `teammates` | array | 队友信息列表 |
| `teammates_checked` | bool | 是否完成队友心法检查 |
| `match_history_checked` | bool | 是否完成战局历史检查 |
| `match_history_win_samples` | int | 战局历史胜利采样数 |
| `source` | string | 写入来源：`ranking`、`inspect`、`migrated` |
| `checked_at` | datetime | 检查/更新时间（用于 TTL 过期判断） |
| `expires_at` | datetime | 过期时间，仅供 repo 业务清理使用；不参与 MongoDB TTL 索引（TTL 仅由 `checked_at` 驱动） |
| `schema_version` | int | schema 版本号 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_identity_key` | `identity_key` | unique |
| `idx_global_role_id` | `global_role_id` | 普通索引 |
| `idx_zone_game_role_id` | `zone`, `game_role_id` | 普通索引 |
| `idx_normalized_server_name` | `normalized_server`, `normalized_name` | 普通索引 |
| `idx_checked_at` | `checked_at` | TTL 604800 秒（Date 类型，7 天） |

### `jjc_ranking_cache`

用途：JJC 排行榜完整结果缓存，避免频繁请求排行榜接口和重复计算。

读写归属：

- `src/services/jx3/jjc_cache_repo.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `cache_key` | string | 当前固定为 `ranking` |
| `cache_time` | float | 业务缓存时间 Unix 秒 |
| `data` | object | 排行榜结果结构 |
| `created_at` | datetime | Mongo TTL 使用的写入时间（Date 类型，TTL 正常生效） |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_cache_key` | `cache_key` | unique |
| `idx_created_at` | `created_at` | TTL 7200 秒（Date 类型，TTL 正常生效） |

### `jjc_role_recent`

用途：JJC 角色近期战绩检查缓存，替代旧 `data/cache/jjc_ranking_inspect/role_recent/`。

读写归属：

- `src/storage/mongo_repos/jjc_inspect_repo.py`
- 业务逻辑：`src/services/jx3/jjc_ranking_inspect.py`
- 迁移脚本：`scripts/migrate_jjc_role_recent.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `server` | string | 服务器名 |
| `name` | string | 角色名 |
| `cached_at` | float | 缓存时间 Unix 秒（⚠ float 类型，TTL 索引不生效） |
| `data` | object | 角色近期战绩结果 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_server_name` | `server`, `name` | unique |
| `idx_cached_at` | `cached_at` | TTL 600 秒（⚠ float 类型，TTL 实际不生效） |

### `jjc_role_indicator`

用途：JJC 角色推栏 indicator 指标缓存，用于排行榜角色弹窗顶部指标展示。

读写归属：

- `src/storage/mongo_repos/jjc_inspect_repo.py`
- 业务逻辑：`src/services/jx3/jjc_ranking_inspect.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `cache_key` | string | 缓存键，使用 `identity_key`（如 `global:<global_role_id>`），业务唯一 |
| `identity_key` | string | 关联 `role_identities.identity_key` |
| `server` | string | 服务器名 |
| `name` | string | 角色名 |
| `game_role_id` | string/null | 游戏角色 ID |
| `global_role_id` | string/null | 推栏全局角色 ID |
| `zone` | string/null | 区服分区 |
| `indicator` | object | 规整后的 3v3 指标：`source`、`type`、`total_matches`、`win_rate`、`score`、`best_score`、`grade` |
| `raw` | object | `role/indicator` 原始响应 |
| `cached_at` | float | 缓存时间 Unix 秒（⚠ float 类型，TTL 索引不生效；过期由 repo 业务 TTL=86400 秒判断；页面主动刷新可绕过缓存） |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_cache_key` | `cache_key` | unique |
| `idx_cached_at` | `cached_at` | 普通索引（用于排查和后续清理；过期判断由业务逻辑完成，不依赖 TTL 索引） |

写入来源：

- 排行榜页面角色 indicator 接口按需读取推栏并写入。
- 每日/手动 JJC 排名统计在心法判定过程中已请求到 `role/indicator` 时，会同步预热写入本集合。

### `jjc_match_detail`

用途：JJC 对局详情缓存，替代旧 `data/cache/jjc_ranking_inspect/match_detail/`。

读写归属：

- `src/storage/mongo_repos/jjc_inspect_repo.py`
- 业务逻辑：`src/services/jx3/jjc_ranking_inspect.py`、`src/services/jx3/jjc_ranking.py`
- 迁移脚本：`scripts/migrate_jjc_match_detail.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `match_id` | int | 对局 ID，业务唯一键 |
| `cached_at` | float | 缓存时间 Unix 秒 |
| `data` | object | 对局详情原始或规整后的结果 |

`data` 内部玩家节点字段（拆表后）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `players_info[].equipment_snapshot_hash` | string | 关联 `jjc_equipment_snapshot.snapshot_hash`，替代原 `armors` 数组 |
| `players_info[].talent_snapshot_hash` | string | 关联 `jjc_talent_snapshot.snapshot_hash`，替代原 `talents` 数组 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_match_id` | `match_id` | unique |

写入来源：

- 排行榜页面对局详情接口按需读取推栏并写入。
- JJC 对局同步通过排行榜 inspect service 写入。
- 每日/手动 JJC 排名统计在心法判定过程中已请求到最近胜场 `match/detail` 时，会同步预热写入本集合，并复用装备/奇穴快照拆分逻辑。

当前存储形态：

- `data` 字段是 MongoDB 嵌套对象（BSON document），不是 JSON 字符串。代码通过 Motor/PyMongo 写入 Python `dict`，Mongo 底层以 BSON 保存；这是推荐形态，支持嵌套字段查询、局部更新和后续迁移。
- 不应把 `data` 改成 JSON 字符串。JSON 字符串会让 Mongo 只能按普通字符串处理，无法直接索引或查询 `data.detail.*` 子字段。
- 现有 API 返回结构依赖 `data.detail.basic_info`、`team1`、`team2`、`players_info[].armors`、`players_info[].talents` 等字段。前端 `public/jjc-ranking-stats.html` 当前展示基础对局信息、双方玩家、分数/血量/装分、装备图标和奇穴图标。
- 推栏明确返回 `code=-1`、`msg=no data found`、`data=null` 时，`data` 保存轻量不可用终态：`{"match_id": <int>, "unavailable": true, "code": -1, "message": "no data found", "detail": null}`。这类文档不进入装备/奇穴快照拆表，读取时原样返回并带缓存命中信息。

2026-04-30 只读抽样观察：

- 当前集合文档数约 341，逻辑大小约 20.45 MB，平均每局约 60 KB；WiredTiger 压缩后集合存储约 7.0 MB，索引约 80 KB。
- 顺序采样 80 局显示单局 BSON 大小约 51-61 KB，3v3 对局固定 6 名玩家。
- 主要体积来自玩家装备与奇穴：`armors` 平均约 4.1 KB/玩家，`talents` 平均约 3.1 KB/玩家，`metrics` 平均约 1.1 KB/玩家，`body_qualities` 平均约 1.0 KB/玩家。
- 因用户希望保留字段完整性，本集合后续优化优先考虑拆表与去重，不以字段裁剪作为默认方向。

后续演进约束：

- 历史对局详情是“对局当时快照”，不要直接改成从角色当前画像表读取装备、奇穴、分数等动态状态，否则会把历史对局展示成当前角色状态。
- 可以把角色身份字段（如 `global_role_id`、`role_id`、`person_id`、服务器、角色名）与已有 `role_identities` 关联，但对局时的 `kungfu`、`mmr`、`score`、`total_score`、`equip_score`、`max_hp`、`mvp`、`fight_seconds` 等仍属于对局快照。
- `players_info[].role_name` 可继续保留推栏原始展示名，例如 `角色名·服务器`；运行时若要派生写入 `role_identities` 或 `jjc_sync_role_queue`，必须先规范化为纯角色名，不直接回写快照源数据。
- 第一阶段拆表已完成：`jjc_equipment_snapshot` 保存完整 `armors` 数组，`jjc_talent_snapshot` 保存完整 `talents` 数组，`jjc_match_detail` 的玩家节点保存对应 `*_snapshot_hash`。读取详情时由 `JjcInspectRepo` 批量查快照并拼回原 API 结构。历史详情缓存不做兼容迁移，必要时通过 `scripts/clear_jjc_match_detail_snapshot_cache.py` 清空后重新按新格式写入。
- `snapshot_hash` 必须基于规范化后的完整数组生成：装备按稳定字段（优先 `pos`，再 `ui_id`/`name`）排序，奇穴按稳定字段（优先 `level`，再 `id`/`name`）排序，JSON 序列化使用固定 key 顺序和固定分隔符。
- 后续若需要“点了某个奇穴的对局数”“有 CW 的对局数”等统计，可在 snapshot 表补充可查询索引字段（如 `talent_ids`、`talent_names`、`item_ui_ids`、`item_names`、`has_cw`），或再建 `jjc_match_player_fact` 事实表。事实表应视为可重建的查询索引，不应替代完整详情与快照源数据。
- 若大量爬取导致热表继续增长，应考虑冷热分层：热集合保留近期可快速查询结构，归档集合或对象存储保留完整历史详情。无论是否归档，`match_id` 仍是幂等主键。

计划文档：`docs/exec-plans/active/jjc-match-detail-storage-plan.md`。

### `jjc_equipment_snapshot`

用途：保存完整装备快照，按内容 hash 去重。与 `jjc_match_detail` 解耦，避免每场对局重复存储相同装备数组。

读写归属：

- `src/storage/mongo_repos/jjc_match_snapshot_repo.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `snapshot_hash` | string | 规范化 `armors` 数组后的 SHA-256 内容 hash，业务唯一 |
| `armors` | array | 完整装备数组，不裁剪字段 |
| `created_at` | datetime | 首次写入时间 |
| `last_seen_at` | datetime | 最近一次被对局引用的时间 |
| `schema_version` | int | schema 版本，初始为 1 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_snapshot_hash` | `snapshot_hash` | unique |
| `idx_last_seen_at` | `last_seen_at` | 普通索引 |

### `jjc_talent_snapshot`

用途：保存完整奇穴快照，按内容 hash 去重。与 `jjc_match_detail` 解耦，避免每场对局重复存储相同奇穴数组。

读写归属：

- `src/storage/mongo_repos/jjc_match_snapshot_repo.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `snapshot_hash` | string | 规范化 `talents` 数组后的 SHA-256 内容 hash，业务唯一 |
| `talents` | array | 完整奇穴数组，不裁剪字段 |
| `created_at` | datetime | 首次写入时间 |
| `last_seen_at` | datetime | 最近一次被对局引用的时间 |
| `schema_version` | int | schema 版本，初始为 1 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_snapshot_hash` | `snapshot_hash` | unique |
| `idx_last_seen_at` | `last_seen_at` | 普通索引 |

### `jjc_sync_role_queue`

用途：JJC 对局数据同步的角色队列，保存每个待同步角色的本赛季同步进度与执行租约。

读写归属：

- `src/storage/mongo_repos/jjc_sync_repo.py`
- 业务入口：`src/plugins/jx3bot_handlers/jjc_match_data_sync.py`
- 同步编排：`src/services/jx3/jjc_match_data_sync.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `identity_key` | string | 角色身份键，优先 `global:{global_role_id}`，其次 `game:{zone}:{role_id}`，最后 `name:{normalized_server}:{normalized_name}`，业务唯一 |
| `server` | string | 服务器名 |
| `name` | string | 角色名，只保存纯角色名；对局详情自动发现链路写入前必须先去掉可判定的服务器展示后缀 |
| `normalized_server` | string | 规范化服务器名 |
| `normalized_name` | string | 规范化角色名 |
| `global_role_id` | string/null | 推栏全局角色 ID |
| `role_id` | string/null | 角色 ID |
| `person_id` | string/null | 推栏个人 ID；对局详情缺 `global_role_id` 时可用于 `person-history` 补全 |
| `zone` | string/null | 区服分区 |
| `identity_source` | string/null | 同步前身份补全来源，如 `role_identity_name_match`、`live_ranking_global_role_id`、`person_history` |
| `source` | string | 来源：`manual`、`ranking`、`match_detail` |
| `priority` | int | 调度优先级，手动添加高于自动发现 |
| `status` | string | 状态：`pending`、`syncing`、`exhausted`、`cooldown`、`failed`、`disabled` |
| `season_id` | string/null | 当前赛季标识 |
| `season_start_time` | int | 当前赛季开始时间 Unix 秒 |
| `full_synced_until_time` | int/null | 已完整覆盖到的最新时间点 Unix 秒 |
| `oldest_synced_match_time` | int/null | 已同步到的最早对局时间 Unix 秒 |
| `latest_seen_match_time` | int/null | 最近看到的最新对局时间 Unix 秒 |
| `history_exhausted` | bool/null | 本赛季是否已经回溯到赛季开始 |
| `last_cursor` | int | 最近处理 cursor |
| `lease_owner` | string/null | 当前执行实例标识 |
| `lease_expires_at` | float/null | 执行租约过期时间 Unix 秒，用于重启恢复 |
| `last_synced_at` | float/null | 最近同步时间 Unix 秒 |
| `next_sync_after` | float/null | 下一次允许同步时间 Unix 秒 |
| `fail_count` | int | 连续失败次数 |
| `last_error` | string/null | 最近错误 |
| `created_at` | float | 创建时间 Unix 秒 |
| `updated_at` | float | 更新时间 Unix 秒 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_identity_key` | `identity_key` | unique |
| `idx_status_priority_next_sync_after` | `status`, `priority`, `next_sync_after` | 普通复合索引 |
| `idx_normalized_server_name` | `normalized_server`, `normalized_name` | 普通复合索引 |
| `idx_global_role_id` | `global_role_id` | 普通索引 |
| `idx_lease_expires_at` | `lease_expires_at` | 普通索引 |

### `jjc_sync_match_seen`

用途：保存已发现对局与详情同步状态，避免重复请求详情。

读写归属：

- `src/storage/mongo_repos/jjc_sync_repo.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `match_id` | int | 对局 ID，业务唯一 |
| `source_identity_key` | string/null | 首次发现该对局的角色身份键 |
| `source_server` | string/null | 首次发现来源服务器 |
| `source_role_name` | string/null | 首次发现来源角色名 |
| `status` | string | 状态：`discovered`、`detail_syncing`、`detail_saved`、`failed`、`detail_unavailable` |
| `match_time` | int/null | 对局时间 Unix 秒 |
| `lease_owner` | string/null | 当前执行实例标识 |
| `lease_expires_at` | float/null | 执行租约过期时间 Unix 秒 |
| `discovered_at` | float | 首次发现时间 Unix 秒 |
| `detail_saved_at` | float/null | 详情保存时间 Unix 秒 |
| `detail_retry_after` | float/null | 失败后下次重试时间 Unix 秒 |
| `detail_unavailable_reason` | string/null | 详情不可用原因 |
| `detail_unavailable_code` | int/null | 详情不可用代码 |
| `detail_unavailable_at` | float/null | 标记不可用时间 Unix 秒 |
| `fail_count` | int | 连续失败次数 |
| `last_error` | string/null | 最近错误 |
| `updated_at` | float | 更新时间 Unix 秒 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_match_id` | `match_id` | unique |
| `idx_status_match_time` | `status`, `match_time` | 普通复合索引 |
| `idx_source_identity_key` | `source_identity_key` | 普通索引 |
| `idx_lease_expires_at` | `lease_expires_at` | 普通索引 |

### `jjc_sync_state`

用途：保存同步全局状态，如暂停/恢复开关。

读写归属：

- `src/storage/mongo_repos/jjc_sync_repo.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `key` | string | 状态键，当前固定为 `global`，业务唯一 |
| `paused` | bool | 是否全局暂停 |
| `reason` | string | 暂停原因 |
| `updated_at` | float | 更新时间 Unix 秒 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_key` | `key` | unique |

### `announcements`

用途：系统公告与更新说明，通过前端 SPA 展示并支持 QQ 机器人管理员命令维护。

读写归属：

- `src/storage/mongo_repos/announcement_repo.py`
- API 入口：`src/api/routers/announcements.py`
- QQ 管理命令：`src/plugins/announcement_admin.py`

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `announcement_id` | string | UUID 十六进制字符串，业务唯一键 |
| `title` | string | 公告标题 |
| `content` | string | 公告正文 |
| `date` | string | 日期键如 `2026-05-11`，用于分组和最新日期比较 |
| `created_at` | float | 创建时间 Unix 秒 |
| `created_by` | string | 创建者 QQ 号 |

索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_announcement_id` | `announcement_id` | unique |
| `idx_date_created_at` | `date` (降序), `created_at` (降序) | 普通复合索引 |

## 文件型持久化与非 Mongo 数据

以下数据当前仍不是 MongoDB schema，但会影响运行状态，修改时也要确认是否需要纳入本文：

- `runtime_config.json`: `/修改配置` 等运行时配置写入文件，包含可覆盖的 `MONGO_URI` 等配置。
- `data/jjc_ranking_stats/<timestamp>/summary.json` 与 `details/`: JJC 统计产物，属于文件型统计快照，不在 Mongo 中。details 成员包含 `weapon_name` 字段用于橙武白名单判定。
- `data/baizhan_images/baizhan_data.json`、图片缓存和 `mpimg/`: 静态或缓存资源。

## 已清理的未使用 Mongo 集合

2026-04-30 按当前代码引用、`src/infra/mongo.py:_ensure_indexes()` 和本文集合设计核对，以下 MongoDB 集合不属于运行时代码访问边界，已从配置库 `jx3bot` 删除：

| 集合 | 删除前文档数 | 清理原因 |
|---|---:|---|
| `cache_entries` | 9 | 未在当前代码、迁移脚本或数据库设计中引用 |
| `group_reminders` | 0 | 历史提醒集合名；当前使用 `reminders` |
| `jjc_kungfu_cache` | 0 | 历史/临时集合名；当前 JJC 角色缓存使用 `role_identities` 与 `role_jjc_cache` |
| `jjc_match_detail_snapshot_migration_backup` | 0 | 临时备份集合，当前代码无引用 |
| `jjc_ranking_stats` | 1 | Mongo 集合无运行时代码引用；当前 JJC 统计快照写入 `data/jjc_ranking_stats/` 文件目录 |

## 历史迁移脚本

| 脚本 | 源数据 | 目标集合 | 幂等键 |
|---|---|---|---|
| `scripts/migrate_group_configs.py` | `groups.json` | `group_configs` | `group_id` |
| `scripts/migrate_reminders.py` | `data/group_reminders.json` | `reminders` | `reminder_id` |
| `scripts/migrate_wanbaolou_subs.py` | `data/wanbaolou_subscriptions.json` | `wanbaolou_subscriptions` | `user_id`, `item_name` |
| `scripts/migrate_kungfu_cache.py` | `data/cache/kungfu/*.json` | `kungfu_cache` | `server`, `name` |
| `scripts/migrate_jjc_role_recent.py` | `data/cache/jjc_ranking_inspect/role_recent/` | `jjc_role_recent` | `server`, `name` |
| `scripts/migrate_jjc_match_detail.py` | `data/cache/jjc_ranking_inspect/match_detail/` | `jjc_match_detail` | `match_id` |
| `scripts/migrate_role_identity_and_jjc_cache.py` | `kungfu_cache` | `role_identities`, `role_jjc_cache` | `identity_key` |
| `scripts/fix_jjc_match_detail_role_names.py` | `role_identities`, `jjc_sync_role_queue` 中被 `match_detail` 污染的角色名 | 原集合就地修复，备份写入独立 backup collection | `batch_id`, `source_collection`, `original_id` |
| `scripts/fix_jjc_ranking_weapon_names.py` | `data/jjc_ranking_stats/` 历史快照 details 缺少 `weapon_name` | 就地补齐 `weapon_name` 并重算 `summary.json` 的 `legendary_count_map` | `timestamp`, `range`, `lane`, `kungfu` |
