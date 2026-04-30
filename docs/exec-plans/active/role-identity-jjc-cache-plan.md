# 角色身份与 JJC 缓存重构执行计划

更新时间：2026-04-29

## 当前进展

- 已完成：
  - 阶段 1 文档设计
  - 阶段 2 存储层实现与索引接入
  - 阶段 3 迁移脚本落地并完成全量迁移
  - 阶段 4 中 `jjc_cache_repo.py`、`jjc_ranking.py`、`jjc_ranking_inspect.py` 的灰度读路径接入
  - 迁移核验脚本 `scripts/check_role_identity_migration.py` 落地并完成一次线上核验
- 当前核验结论：
  - `role_identities` 与 `role_jjc_cache` 当前各 10658 条
  - 两边 `identity_key` 完全对齐
  - `checked_at` 无缺失
  - `global_role_id`、`zone + game_role_id` 在 identity/jjc 两侧均无重复
- 已完成的真实链路回归：
  - 使用样本角色 `乾坤一掷 / 一冬冬一 / SK01-OABFKL-WERHJU6LVO77YBNC5RPRJK3DKU` 验证 `get_role_recent(...)`
  - 传 `global_role_id` 时成功返回 20 条近期对局，身份来源 `detail_hint_global_role_id`
  - 仅传 `server + name` 且绕过首页缓存 (`cursor=1`) 时成功返回 20 条近期对局，身份来源 `role_identity_name_match`
  - 使用最近对局 `match_id=253549814` 验证 `get_match_detail(...)`，成功返回 3v3 双方玩家详情
- 本轮回归发现的附带问题：
  - `init_mongo()` 在现网 `wanbaolou_subscriptions` 重复索引冲突场景下会输出 logging formatting error，原因是 `_safe_index()` 的 warning 日志写法与当前 logger 实现不兼容；该问题与本次 JJC 重构无直接耦合，但需要单独修复
- 仍待完成：
  - 阶段 5 继续观察新集合主写 + 旧集合 shadow write 的线上稳定性
  - 阶段 6 旧集合 TTL Date 字段修复或正式标注为 legacy-only
  - 阶段 7 更完整的功能级回归（竞技排名、竞技排名统计、JJC 角色近期联动）

## 背景

当前 `kungfu_cache` 以 `server + name` 作为唯一键，实际承载了角色身份、心法、武器、队友和检查状态等多类信息。JJC 排行榜通常能拿到 `gameRoleId + zone + server + roleName`，但不一定有 `globalRoleId`；推栏战局历史需要 `global_role_id`；对局详情可能含有 `global_role_id`、`role_id`、`person_id`，但前提是已经拿到 `match_id`。

因此不能直接把 `role_id` 或 `global_role_id` 当成唯一主键。新的设计应使用内部 `identity_key`，并保留多种外部 ID 与身份升级机制。

## 目标

- QQ 用户和游戏角色不合并。
- 游戏角色拥有独立身份模型。
- JJC 心法、武器、队友缓存从角色身份中拆出。
- 旧 `kungfu_cache` 数据可迁移，迁移过程幂等、可 dry-run。
- 现有 `竞技排名`、`JJC 角色近期`、`战绩/竞技查询` 不回退。
- 数据库设计、索引、迁移脚本、回归清单同步更新。

## 目标数据库设计

### `role_identities`

用途：存储游戏角色身份，不存具体心法缓存结果。

核心字段：

| 字段 | 说明 |
|---|---|
| `identity_key` | 内部主键 |
| `identity_level` | `global`、`game_role` 或 `name` |
| `server` / `normalized_server` | 当前服务器名与规范化服务器名 |
| `name` / `normalized_name` | 当前角色名与规范化角色名 |
| `zone` | 大区 |
| `game_role_id` | 排行榜常见角色 ID |
| `role_id` | 角色详情或对局详情中的角色 ID |
| `global_role_id` | 推栏战局历史所需全局角色 ID |
| `person_id` | 对局详情中的 person ID |
| `aliases` | 历史名称、服务器或旧 `identity_key` |
| `sources` | `ranking`、`indicator`、`match_detail`、`migrated_kungfu_cache` 等来源 |
| `first_seen_at` / `last_seen_at` / `updated_at` | Date 类型时间 |
| `schema_version` | schema 版本 |

`identity_key` 生成规则：

| 条件 | key |
|---|---|
| 有 `global_role_id` | `global:{global_role_id}` |
| 无 global，但有 `zone + game_role_id` | `game:{zone}:{game_role_id}` |
| 只有名称入口 | `name:{normalized_server}:{normalized_name}` |

索引：

| 索引 | 约束 |
|---|---|
| `identity_key` | unique |
| `global_role_id` | partial unique |
| `zone + game_role_id` | partial unique |
| `normalized_server + normalized_name` | 普通索引 |
| `last_seen_at` | 普通索引 |

### `role_jjc_cache`

用途：存储 JJC 角色画像缓存，关联 `identity_key`。

核心字段：

| 字段 | 说明 |
|---|---|
| `identity_key` | 关联 `role_identities.identity_key` |
| `server` / `name` / `zone` | 查询和展示冗余字段 |
| `game_role_id` / `role_id` / `global_role_id` | 外部 ID 冗余，便于调试和查询 |
| `kungfu` / `kungfu_id` / `kungfu_pinyin` | 当前判定心法 |
| `kungfu_indicator` / `kungfu_match_history` | 不同来源心法 |
| `kungfu_selected_source` | 最终采用来源 |
| `weapon` / `weapon_icon` / `weapon_quality` | 武器信息 |
| `weapon_checked` | 是否完成武器检查 |
| `teammates` | 队友信息 |
| `teammates_checked` | 是否完成队友检查 |
| `match_history_checked` / `match_history_win_samples` | 战局历史检查信息 |
| `source` | 写入来源 |
| `checked_at` | Date 类型检查时间 |
| `expires_at` | Date 类型过期时间，或使用 `checked_at` TTL |
| `schema_version` | schema 版本 |

索引：

| 索引 | 约束 |
|---|---|
| `identity_key` | unique |
| `global_role_id` | 普通索引 |
| `zone + game_role_id` | 普通索引 |
| `normalized_server + normalized_name` | 普通索引 |
| `checked_at` | TTL |

## 阶段 1：文档设计

先改文档，不动代码。

改动：

- 更新 `docs/design-docs/database-design.md`
- 新增角色身份模型、`identity_key` 生成规则、身份升级规则
- 新增 `role_identities` 与 `role_jjc_cache`
- 标记旧 `kungfu_cache` 为 legacy，并说明迁移与废弃计划
- 明确 `server + name` 是查询入口，不是永久身份主键
- 明确 `role_id/global_role_id` 可能缺失，不得无脑作为唯一主键

验收：

- 数据库文档能指导新增 repo、索引和迁移脚本实现。
- 文档中的索引与后续 `src/infra/mongo.py:_ensure_indexes()` 一致。

## 阶段 2：存储层实现

新增 repo：

```text
src/storage/mongo_repos/role_identity_repo.py
src/storage/mongo_repos/role_jjc_cache_repo.py
```

`RoleIdentityRepo` 能力：

- `build_identity_key(...)`
- `upsert_from_ranking(...)`
- `upsert_from_indicator(...)`
- `upsert_from_match_detail(...)`
- `find_by_global_role_id(...)`
- `find_by_game_role_id(zone, game_role_id)`
- `find_by_name(server, name)`
- `resolve_best_identity(...)`
- `upgrade_identity(...)`

`RoleJjcCacheRepo` 能力：

- `load_by_identity_key(...)`
- `load_by_best_identity(...)`
- `save(...)`
- `cleanup_expired(...)`，仅作为 TTL 兜底时使用

索引改动：

- 更新 `src/infra/mongo.py:_ensure_indexes()`
- TTL 字段使用 `datetime`，不要继续对 float/int 时间戳字段创建 TTL 索引

验收：

```bash
python -m py_compile src/storage/mongo_repos/role_identity_repo.py
python -m py_compile src/storage/mongo_repos/role_jjc_cache_repo.py
python -m py_compile src/infra/mongo.py
```

## 阶段 3：迁移脚本

新增脚本：

```text
scripts/migrate_role_identity_and_jjc_cache.py
```

迁移逻辑：

1. 遍历旧 `kungfu_cache`
2. 对每条记录生成候选身份：
   - 有 `global_role_id`：`global:{global_role_id}`
   - 否则有 `role_id` 或 `game_role_id` 且有 `zone`：`game:{zone}:{id}`
   - 否则：`name:{server}:{name}`
3. 写入 `role_identities`
4. 写入 `role_jjc_cache`
5. 原始字段尽量保留到 `role_jjc_cache`
6. 输出迁移统计：总数、global 数、game_role 数、name 数、跳过数、冲突数

脚本要求：

- 默认 dry-run
- 支持 `--apply` 真写入
- 支持 `--limit` 小批量验证
- 幂等
- 不删除旧 `kungfu_cache`
- 冲突输出到日志或 JSON 报告

验收：

```bash
python scripts/migrate_role_identity_and_jjc_cache.py --limit 20
python scripts/migrate_role_identity_and_jjc_cache.py --limit 20 --apply
```

## 阶段 4：业务读路径灰度切换

先让业务优先读新集合，读不到回退旧集合。

改动范围：

- `src/services/jx3/jjc_cache_repo.py`
- `src/services/jx3/jjc_ranking.py`
- `src/services/jx3/jjc_ranking_inspect.py`

策略：

1. `get_user_kungfu(server, name)`：
   - 从排行榜拿到 `gameRoleId + zone + server + name`
   - 写入或更新 `role_identities`
   - 查询 `role_jjc_cache`
   - miss 后走现有心法判定逻辑
   - 判定完成后写新集合
   - 兼容写旧 `kungfu_cache` 一段时间

2. `_resolve_role_identity(...)`：
   - 优先查 `role_identities`
   - 有 `global_role_id` 直接用
   - 有 `game_role_id + zone` 调 indicator 补 global
   - 查不到再用排行榜实时解析
   - 最后才回退旧 `kungfu_cache`

3. `jjc_role_recent`：
   - 缓存 key 短期仍可使用 `server + name`
   - payload 附带 `identity_key`
   - 后续再评估是否按 `identity_key` 缓存

验收：

- 排行榜能正常生成心法统计。
- 没有 `global_role_id` 的排行榜角色仍能通过 `gameRoleId + zone` 尝试补全。
- indicator 补全失败时，不阻塞基础心法缓存写入，只将身份级别降为 `game_role` 或 `name`。

## 阶段 5：写路径切换

确认读路径稳定后，改成新集合为主写。

策略：

- `role_identities` 与 `role_jjc_cache` 为主写。
- 旧 `kungfu_cache` 保留 shadow write 一个观察周期。
- 文档标记 `kungfu_cache` 为 legacy。
- 暂不删除旧集合和旧迁移脚本。

## 阶段 6：TTL 与时间字段修复

修复当前 TTL 隐患。

改动：

- 新集合使用 Date 字段承载 TTL。
- `jjc_ranking_cache.created_at` 已经是 Date，可保留。
- 旧集合若继续长期保留：
  - `kungfu_cache.cache_time` 补 `cache_time_dt`
  - `jjc_role_recent.cached_at` 补 `cached_at_dt`
  - `server_master_cache.cached_at` 补 `cached_at_dt`

优先级：

1. 新集合 TTL 必须正确。
2. 旧集合如果即将废弃，可只保留业务 TTL 判断，并在文档标注 TTL 索引不可靠。
3. 旧集合如长期保留，再补 Date 字段和迁移。

## 阶段 7：回归清单

最小编译验证：

```bash
python -m py_compile src/infra/mongo.py
python -m py_compile src/storage/mongo_repos/role_identity_repo.py
python -m py_compile src/storage/mongo_repos/role_jjc_cache_repo.py
python -m py_compile src/services/jx3/jjc_cache_repo.py
python -m py_compile src/services/jx3/jjc_ranking.py
python -m py_compile src/services/jx3/jjc_ranking_inspect.py
```

功能回归：

- `竞技排名`
  - 首次查询无缓存
  - 二次查询命中新缓存
  - 统计结果仍生成图片和文件
- `竞技排名统计`
  - healer/dps 统计不变
  - 橙武占比字段仍正常
- JJC 角色近期接口
  - 只传 `server + name`
  - 传 `game_role_id + zone`
  - 传 `global_role_id`
- 对局详情
  - `match_id` 查询正常
  - 对局 player 的 `global_role_id`、`role_id`、`kungfu` 解析正常
- 老数据兼容
  - 迁移前仅旧 `kungfu_cache` 存在时，仍能读到缓存
  - 迁移后新集合命中
  - 新旧冲突时优先新集合

建议补充诊断脚本：

```text
scripts/check_role_identity_migration.py
```

检查内容：

- 新旧数量对比
- `identity_level` 分布
- 同一 `server + name` 多身份冲突
- 同一 `global_role_id` 多记录冲突
- 缺失 `server/name` 的异常记录

## 阶段 8：发布与回滚

上线顺序：

1. 发布文档、新 repo 和索引代码，但业务仍走旧路径。
2. 跑 dry-run 迁移。
3. 小批量 `--apply`。
4. 开启读新回退旧。
5. 全量迁移。
6. 观察日志和命中率。
7. 切主写新集合。
8. 保留旧集合至少一个观察周期。

回滚策略：

- 不删除旧 `kungfu_cache`。
- 读路径保留 fallback。
- 如果新身份解析出问题，关闭新 repo 读取，回到旧 `server + name`。
- 迁移脚本只 upsert 新集合，不修改旧集合，回滚成本低。

## 推荐实施顺序

1. 更新数据库设计文档，把本方案固化。
2. 实现 `RoleIdentityRepo` 和 `RoleJjcCacheRepo`。
3. 加索引，修新集合 TTL。
4. 写 dry-run 迁移脚本。
5. 改 `jjc_ranking_inspect` 的身份解析。
6. 改 `jjc_ranking/get_user_kungfu` 的缓存读写。
7. 跑小批量迁移和回归。
8. 全量迁移后再考虑废弃旧 `kungfu_cache`。
