# 文件缓存迁移 Mongo 计划

更新时间：2026-03-09

本文只讨论“当前文件缓存和运行态 JSON 数据”迁移到 Mongo 的方案，不包含业务代码改造实现。目标是先划清迁移范围、集合设计和落地顺序，避免把配置文件、图片缓存、进程内短 TTL 缓存一起混进来。

## 目标

- 把分散在文件系统中的结构化缓存收口到统一存储边界
- 保留现有分层方向：`plugins -> services -> infra/storage`
- 让可恢复的运行态数据在重启后仍可恢复
- 为后续把文件读写迁到 `src/storage/` 提供明确目标模型
- 后续实现阶段按 TDD 推进，先写失败测试，再补最小实现

## 非目标

- 本文不要求把所有文件都迁到 Mongo
- 本文不包含图片二进制、模板文件、静态资源迁移
- 本文不要求替换当前进程内短 TTL 内存缓存
- 本文不改 `groups.json` 这类配置型数据

## 当前盘点

### 适合优先迁移

1. `status_monitor` 通用缓存
   - 现状：[`src/plugins/status_monitor/storage.py`](../../../src/plugins/status_monitor/storage.py) 直接读写 `data/cache/*.json`
   - 内容：`status_history`、`server_status`、`news_ids`、`records_ids`、`event_codes_ids`、`server_open_history`、`server_maintenance_history`
   - 迁移动因：结构化 JSON、跨重启有价值、目前无 repo 边界

2. 竞技场排行榜缓存
   - 现状：[`src/services/jx3/jjc_cache_repo.py`](../../../src/services/jx3/jjc_cache_repo.py) 使用 `data/cache/jjc_ranking_cache.json`
   - 语义：单 key 缓存，TTL 约 2 小时
   - 迁移动因：已具备 repo 边界，最容易先落 Mongo 版本

3. 竞技场心法缓存
   - 现状：[`src/services/jx3/jjc_cache_repo.py`](../../../src/services/jx3/jjc_cache_repo.py) 使用 `data/cache/kungfu/<server>_<name>.json`
   - 语义：按 `server + name` 缓存，TTL 约 7 天，且包含 `weapon_checked`、`teammates_checked`、`teammates` 完整性判断
   - 迁移动因：文件数量多、天然适合文档模型、命中规则明确

4. 区服简称解析缓存
   - 现状：[`src/services/jx3/server_resolver.py`](../../../src/services/jx3/server_resolver.py) 使用 `data/cache/server_master_cache.json`
   - 语义：一个查询词映射多个 alias key，共享同一份结果，TTL 7 天
   - 迁移动因：显式 TTL、结构简单、和 `src/storage/` 的 `server_alias_cache` 方向一致

5. 提醒任务持久化数据
   - 现状：[`src/plugins/jx3bot_handlers/reminder.py`](../../../src/plugins/jx3bot_handlers/reminder.py) 使用 `data/group_reminders.json`
   - 语义：创建、取消、完成、启动恢复待执行任务
   - 迁移动因：这是“可恢复运行态数据”，不是纯缓存，但非常适合 Mongo

6. 万宝楼订阅数据
   - 现状：[`src/plugins/wanbaolou/__init__.py`](../../../src/plugins/wanbaolou/__init__.py) 使用 `data/wanbaolou_subscriptions.json`
   - 语义：用户主动维护的订阅关系
   - 迁移动因：这是业务持久化数据，不应该继续放在单文件里

7. 服务器列表本地回退缓存
   - 现状：[`src/plugins/jx3bot_handlers/cache_init.py`](../../../src/plugins/jx3bot_handlers/cache_init.py) 启动时写 `server_data.json`，[`src/infra/jx3api_get.py`](../../../src/infra/jx3api_get.py) 读取
   - 语义：远端请求失败时的本地回退数据
   - 迁移动因：属于标准远端数据镜像缓存，适合统一进入 Mongo

8. 竞技场统计快照
   - 现状：[`src/services/jx3/jjc_ranking.py`](../../../src/services/jx3/jjc_ranking.py) 写 `data/jjc_ranking_stats/<timestamp>.json`，[`src/api/routers/jjc_ranking_stats.py`](../../../src/api/routers/jjc_ranking_stats.py) 读取
   - 语义：按时间戳保留历史快照，并通过 HTTP API 列表/读取
   - 迁移动因：这是天然的历史文档集合

### 适合后置迁移

1. 万宝楼别名缓存
   - 现状：[`src/plugins/wanbaolou/alias.py`](../../../src/plugins/wanbaolou/alias.py) 使用 `data/wanbaolou_alias_cache.json`
   - 判断：可以迁，但它还会反向重建 `waiguan.json` 供搜索器加载，短期内收益不如前面几项高

2. 百战活动元数据
   - 现状：[`src/services/jx3/baizhan.py`](../../../src/services/jx3/baizhan.py) 使用 `data/baizhan_images/baizhan_data.json`
   - 判断：元数据可迁，但图片文件仍需保留在本地；建议和图片缓存拆开设计，放到第二阶段

### 不建议纳入本次迁移

1. `groups.json`
   - 原因：它是群配置，不是缓存；当前已有 `GroupConfigRepo` 边界，是否迁 Mongo 应单独做“配置存储迁移”决策

2. `runtime_config.json`、`restart_info.json`
   - 原因：它们更像单机控制面和进程重启握手，不是通用缓存

3. `mpimg/wanbaolou/*.png`、`data/baizhan_images/baizhan_latest.png`、`mpimg/img/baizhan/skills/*`
   - 原因：这是本地二进制资源缓存，迁 Mongo 会把问题从“文件缓存”变成“对象存储/大文件存储”

4. `waiguan.json`
   - 原因：当前搜索器直接从文件构建索引，短期内保留为生成产物更稳妥

5. 进程内短 TTL 缓存
   - 现状：[`src/infra/jx3api_get.py`](../../../src/infra/jx3api_get.py) 的 `cacheout.Cache`，[`src/plugins/wanbaolou/api.py`](../../../src/plugins/wanbaolou/api.py) 的 `SimpleCache`
   - 原因：它们是请求级/进程级热点缓存，不需要先落库

## 推荐集合设计

原则：纯缓存走统一 `cache_entries`，有明确业务主键和查询方式的运行态数据走独立集合。

### 1. `cache_entries`

用途：

- `status_monitor` 各类 JSON 缓存
- `server_data.json`
- `server_master_cache`
- 后续可接入 `wanbaolou_alias_cache`
- 后续可接入 `baizhan_data.json`

建议文档结构：

```json
{
  "_id": "status_monitor:status_history",
  "namespace": "status_monitor",
  "key": "status_history",
  "payload": {
    "梦江南": {
      "last_maintenance": 1700000000,
      "last_open": 1700003600
    }
  },
  "version": 1,
  "updated_at": "2026-03-09T00:00:00Z",
  "expires_at": null,
  "meta": {
    "source_file": "data/cache/status_history.json"
  }
}
```

建议索引：

- 唯一索引：`{ namespace: 1, key: 1 }`
- TTL 索引：`{ expires_at: 1 }`，仅用于确实要自动过期的缓存文档

落表映射建议：

- `status_monitor/status_history`
- `status_monitor/server_status`
- `status_monitor/news_ids`
- `status_monitor/records_ids`
- `status_monitor/event_codes_ids`
- `status_monitor/server_open_history`
- `status_monitor/server_maintenance_history`
- `jx3/server_data`
- `jx3/server_master_aliases`
- `wanbaolou/alias_cache`（后置）
- `baizhan/latest_meta`（后置）

### 2. `jjc_ranking_cache`

用途：

- 替代 `data/cache/jjc_ranking_cache.json`

建议文档结构：

```json
{
  "_id": "current",
  "cache_time": 1700000000,
  "expires_at": "2026-03-09T10:00:00Z",
  "data": {},
  "updated_at": "2026-03-09T08:00:00Z"
}
```

建议索引：

- 唯一索引：`{ _id: 1 }`
- TTL 索引：`{ expires_at: 1 }`

说明：

- 这是单文档缓存，不需要复杂建模
- 即使使用 TTL，也建议读取时继续保留显式有效性判断，避免 Mongo TTL 删除延迟影响业务预期

### 3. `jjc_kungfu_cache`

用途：

- 替代 `data/cache/kungfu/<server>_<name>.json`

建议文档结构：

```json
{
  "_id": "梦江南:某角色",
  "server": "梦江南",
  "name": "某角色",
  "cache_time": 1700000000,
  "expires_at": "2026-03-16T08:00:00Z",
  "kungfu": "莫问",
  "found": true,
  "weapon_checked": true,
  "weapon": "XX",
  "weapon_icon": "https://...",
  "weapon_quality": 6,
  "teammates_checked": true,
  "teammates": [
    {
      "name": "队友A",
      "kungfu_id": "10014"
    }
  ],
  "payload": {},
  "updated_at": "2026-03-09T08:00:00Z"
}
```

建议索引：

- 唯一索引：`{ server: 1, name: 1 }`
- TTL 索引：`{ expires_at: 1 }`
- 可选查询索引：`{ updated_at: -1 }`

说明：

- 这里不建议塞进 `cache_entries`，因为数量大、主键明确、未来很可能要做定向清理或按角色排查
- 读取逻辑仍需保留现有完整性判定：`weapon_checked`、`teammates_checked`、`teammates[].kungfu_id`

### 4. `group_reminders`

用途：

- 替代 `data/group_reminders.json`

建议文档结构：

```json
{
  "_id": "reminder_id",
  "group_id": "123456",
  "creator_user_id": "654321",
  "mention_type": "all",
  "message": "开团",
  "remind_at": "20260310193000",
  "remind_at_ts": 1773478200,
  "status": "pending",
  "created_at": 1773470000,
  "done_at": null,
  "canceled_at": null
}
```

建议索引：

- 唯一索引：`{ _id: 1 }`
- 组合索引：`{ group_id: 1, status: 1, remind_at_ts: 1 }`
- 组合索引：`{ creator_user_id: 1, status: 1, remind_at_ts: 1 }`

说明：

- 这不是纯缓存，是“可恢复任务状态”
- 不建议对 `done/canceled` 直接做短 TTL；至少先保留一段历史，方便排障和审计

### 5. `wanbaolou_subscriptions`

用途：

- 替代 `data/wanbaolou_subscriptions.json`

建议文档结构：

```json
{
  "_id": "group_id:user_id:item_name",
  "group_id": "123456",
  "user_id": "654321",
  "item_name": "龙隐·星月·标准",
  "price_threshold": 5200,
  "created_at": 1773470000,
  "updated_at": 1773470000,
  "enabled": true,
  "extra": {}
}
```

建议索引：

- 唯一索引：`{ group_id: 1, user_id: 1, item_name: 1 }`
- 查询索引：`{ item_name: 1, enabled: 1 }`
- 查询索引：`{ group_id: 1, user_id: 1, enabled: 1 }`

说明：

- 当前文件结构是“大字典套列表”，落 Mongo 后建议改成“一条订阅一条文档”
- 这样更适合增删改查，也能避免整文件覆盖写

### 6. `jjc_ranking_stats`

用途：

- 替代 `data/jjc_ranking_stats/<timestamp>.json`

建议文档结构：

```json
{
  "_id": 1700000000,
  "generated_at": 1700000100,
  "ranking_cache_time": 1700000000,
  "default_week": 3,
  "current_season": "凌雪藏锋",
  "week_info": "第3周",
  "kungfu_statistics": {}
}
```

建议索引：

- 唯一索引：`{ _id: 1 }`
- 排序索引：`{ generated_at: -1 }`

说明：

- 这是历史快照，不建议自动 TTL，除非后续确认只保留最近 N 天

## 字段与 TTL 设计原则

1. 同时保留 `cache_time` 和 `expires_at`
   - `cache_time` 保持和现有业务语义一致
   - `expires_at` 用于 Mongo TTL 自动清理

2. TTL 只用于真正可丢弃的缓存
   - 适用：`jjc_ranking_cache`、`jjc_kungfu_cache`、`server_master_aliases`、`server_data`
   - 不适用：`wanbaolou_subscriptions`、`jjc_ranking_stats`

3. 读路径不要完全依赖 TTL 删除器
   - Mongo TTL 删除不是实时触发
   - 业务读取时仍应按 `cache_time`/`expires_at` 再判一次

4. 文档内保留 `source_file`
   - 只在迁移初期保留，便于排查和回滚

## 推荐迁移顺序

### Phase 1：先迁已有 repo 边界的数据

- `jjc_ranking_cache`
- `jjc_kungfu_cache`
- `server_master_cache`
- `server_data`

原因：

- 这些点大多已经在 `services/infra`，改动面最可控
- 可以先验证 Mongo 连接、TTL、索引和回退逻辑
- 也最适合先建立第一批存储层测试样板

### Phase 2：迁运行态 JSON 数据

- `status_monitor` 各类缓存
- `group_reminders`
- `wanbaolou_subscriptions`

原因：

- 这些文件现在散在插件层，迁移时顺便要补 `storage` 边界

### Phase 3：迁次优先级缓存

- `wanbaolou_alias_cache`
- `baizhan_data.json`
- 视需要再评估 `waiguan.json` 是否改为 Mongo + 本地索引生成产物

## 迁移步骤建议

1. 先补 Mongo 基础设施
   - 在 `src/storage/` 定义 port 和 Mongo adapter
   - 连接配置走环境变量或 `config.py`
   - 先补连接装配和索引初始化测试，再写实现

2. 做“双读优先 Mongo、回退文件”的过渡期
   - 读：先读 Mongo，未命中再读旧文件
   - 写：先双写 Mongo 和旧文件
   - 先补 repo 级读写行为测试，再接业务调用点

3. 做一次性数据回填
   - 启动前扫描现有 JSON 文件并导入 Mongo
   - 导入脚本只做结构映射，不改业务字段语义
   - 先补样例文件到目标文档的映射测试，再写导入脚本

4. 观察稳定后切单写 Mongo
   - 保留文件回读一个发布周期
   - 确认没有依赖文件侧效果的隐藏逻辑后再删除文件写入

5. 最后删除旧文件路径和兼容逻辑
   - 同步更新 `README.md`、`project-architecture.md`、`docs/references/runbook.md`

## TDD 要求

### 开发顺序

1. 先为 port / repo 定义行为测试
2. 再实现 Mongo adapter
3. 再接入 service / plugin 读写路径
4. 最后删除文件兼容逻辑

### 最小测试层次

1. 单元测试
   - 字段映射
   - TTL / `expires_at` 计算
   - cache hit / miss / fallback 判定
   - 提醒恢复与订阅删除等状态转换

2. repo 集成测试
   - Mongo adapter 的增删改查
   - 索引初始化
   - 双读双写行为

3. 回填脚本测试
   - 旧 JSON 样例导入
   - 重复导入幂等
   - 坏数据容错

4. 高风险链路回归测试
   - `jjc_ranking_stats` 的 list/read
   - `group_reminders` 的 pending 恢复
   - `wanbaolou_subscriptions` 的新增/取消/触发后删除

### 通过标准

- 不允许先改主逻辑、再补测试
- 每个 Phase 至少要有一组失败测试先落地
- 删除旧文件读写前，必须有对应测试覆盖 Mongo 主路径

## 风险与注意点

1. `status_monitor` 的多份缓存目前是“整文件覆盖写”
   - 迁 Mongo 时要先定义 key 级别边界，否则容易变成一个超大文档

2. `jjc_kungfu_cache` 不能只靠 TTL
   - 现有命中条件包含数据完整性，不是单纯“未过期即可”

3. `group_reminders` 有启动恢复语义
   - Mongo 文档必须能支持“查出所有 pending 且按提醒时间恢复调度”

4. `wanbaolou_subscriptions` 是业务数据，不应与纯缓存共表
   - 否则后续权限、查询和去重都会变差

5. 图片缓存不应和 JSON 缓存一起迁
   - 这会把 Mongo 选型问题变成文件对象存储问题

## 建议结论

如果只做一轮“当前文件缓存迁 Mongo”，建议纳入首批迁移的范围是：

- `jjc_ranking_cache`
- `jjc_kungfu_cache`
- `server_master_cache`
- `server_data`
- `status_monitor` JSON 缓存
- `group_reminders`
- `wanbaolou_subscriptions`
- `jjc_ranking_stats`

建议暂不纳入首批：

- `groups.json`
- `runtime_config.json`
- `restart_info.json`
- `waiguan.json`
- 所有图片文件缓存
- 所有进程内短 TTL 内存缓存

按这个范围推进，收益最大，且不容易把“缓存迁移”扩成“全仓库存储重构”。
