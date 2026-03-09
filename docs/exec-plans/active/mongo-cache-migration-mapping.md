# 文件缓存迁移 Mongo 字段对照

更新时间：2026-03-09

本文是 [`mongo-cache-migration-plan.md`](./mongo-cache-migration-plan.md) 的补充，聚焦三件事：

- 现有文件数据的真实结构
- 旧文件到 Mongo 文档的字段映射
- 回填脚本与双写切换时的执行清单

本文仍然不包含代码改动。

## 范围

首批覆盖：

- `status_monitor` JSON 缓存
- `server_data.json`
- `jjc_ranking_cache.json`
- `data/cache/kungfu/*.json`
- `server_master_cache.json`
- `data/group_reminders.json`
- `data/wanbaolou_subscriptions.json`
- `data/jjc_ranking_stats/*.json`

后置覆盖：

- `data/wanbaolou_alias_cache.json`
- `data/baizhan_images/baizhan_data.json`

## 真实文件形状

### 1. `data/wanbaolou_subscriptions.json`

当前样本结构：

```json
{
  "11010783": [
    {
      "item_name": "天选风不欺·无执",
      "price_threshold": 1,
      "group_id": 41432113,
      "created_at": 1745631849.2131052
    }
  ]
}
```

特点：

- 顶层 key 是 `user_id`
- 每个用户是一个订阅数组
- 当前没有独立订阅 id
- 当前没有 `updated_at`、`enabled`、`notified_at`

### 2. `data/cache/status_history.json`

当前样本结构：

```json
{
  "梦江南": {
    "last_maintenance": 1700000000,
    "last_open": 1700003600
  }
}
```

特点：

- 顶层 key 是服务器名
- value 是小对象
- 更适合作为一条缓存文档整体存储，而不是拆成每服一条

### 3. `data/cache/news_ids.json` / `records_ids.json` / `event_codes_ids.json`

当前样本结构：

```json
{
  "ids": ["xxx", "yyy"]
}
```

特点：

- 明显是去重用 ID 集合缓存
- 适合保持原样放入 `payload`

### 4. `server_data.json`

当前样本结构：

```json
{
  "code": 200,
  "msg": "success",
  "data": [],
  "time": 1740000000
}
```

特点：

- 是远端接口的原样镜像
- 目前由启动流程写入，失败时由 `idget()` 作为回退数据读取

### 5. `data/baizhan_images/baizhan_data.json`

当前样本结构：

```json
{
  "start_timestamp": 1745794800,
  "end_timestamp": 1746399600,
  "result": {}
}
```

特点：

- 元数据和图片分离
- 只要 `end_timestamp > now` 就认为图片缓存仍有效

### 6. `data/group_reminders.json`

当前代码推断结构来自 [`reminder.py`](../../../src/plugins/jx3bot_handlers/reminder.py)：

```json
{
  "41432113": [
    {
      "id": "uuidhex",
      "group_id": "41432113",
      "creator_user_id": "11010783",
      "mention_type": "user",
      "message": "开团",
      "remind_at": "20260310193000",
      "created_at": 1773470000,
      "status": "pending",
      "done_at": 1773478200,
      "canceled_at": null
    }
  ]
}
```

特点：

- 顶层按 `group_id` 聚合
- 真正的业务主键是 `reminder.id`
- 启动时只恢复 `status == pending` 的记录

### 7. `data/cache/jjc_ranking_cache.json`

当前代码推断结构来自 [`jjc_cache_repo.py`](../../../src/services/jx3/jjc_cache_repo.py)：

```json
{
  "cache_time": 1773470000,
  "data": {}
}
```

特点：

- 单文件单文档
- 读路径只关心 `cache_time` 和 `data`

### 8. `data/cache/kungfu/<server>_<name>.json`

当前代码推断结构来自 [`jjc_cache_repo.py`](../../../src/services/jx3/jjc_cache_repo.py)：

```json
{
  "server": "梦江南",
  "name": "某角色",
  "kungfu": "莫问",
  "found": true,
  "cache_time": 1773470000,
  "weapon_checked": true,
  "weapon": "XX",
  "weapon_icon": "https://...",
  "weapon_quality": 6,
  "teammates_checked": true,
  "teammates": []
}
```

特点：

- 字段并不完全固定
- 读路径只对部分字段做强校验
- 文档模型必须允许保留剩余扩展字段

### 9. `data/cache/server_master_cache.json`

当前代码推断结构来自 [`server_resolver.py`](../../../src/services/jx3/server_resolver.py)：

```json
{
  "梦江南": {
    "name": "梦江南",
    "zone": "电信五区",
    "id": "123",
    "cached_at": 1773470000
  },
  "梦": {
    "name": "梦江南",
    "zone": "电信五区",
    "id": "123",
    "cached_at": 1773470000
  }
}
```

特点：

- 一个真实区服结果会复制到多个 alias key
- 如果直接原样迁移，也应保留 alias -> result 的映射关系

### 10. `data/jjc_ranking_stats/<timestamp>.json`

当前代码推断结构来自 [`jjc_ranking.py`](../../../src/services/jx3/jjc_ranking.py)：

```json
{
  "generated_at": 1773470100,
  "ranking_cache_time": 1773470000,
  "default_week": 3,
  "current_season": "凌雪藏锋",
  "week_info": "第3周",
  "kungfu_statistics": {}
}
```

特点：

- 文件名时间戳本身就是天然主键
- API 提供 `list` 和 `read(timestamp)` 两种访问方式

## 字段映射表

### A. 通用缓存 `cache_entries`

适用文件：

- `status_history.json`
- `server_status.json`
- `news_ids.json`
- `records_ids.json`
- `event_codes_ids.json`
- `server_open_history.json`
- `server_maintenance_history.json`
- `server_data.json`
- `server_master_cache.json`
- 后置：`wanbaolou_alias_cache.json`
- 后置：`baizhan_data.json`

映射规则：

| 旧文件 | namespace | key | payload | expires_at |
| --- | --- | --- | --- | --- |
| `data/cache/status_history.json` | `status_monitor` | `status_history` | 整个文件 JSON | `null` |
| `data/cache/server_status.json` | `status_monitor` | `server_status` | 整个文件 JSON | `null` |
| `data/cache/news_ids.json` | `status_monitor` | `news_ids` | 整个文件 JSON | `null` |
| `data/cache/records_ids.json` | `status_monitor` | `records_ids` | 整个文件 JSON | `null` |
| `data/cache/event_codes_ids.json` | `status_monitor` | `event_codes_ids` | 整个文件 JSON | `null` |
| `data/cache/server_open_history.json` | `status_monitor` | `server_open_history` | 整个文件 JSON | `null` |
| `data/cache/server_maintenance_history.json` | `status_monitor` | `server_maintenance_history` | 整个文件 JSON | `null` |
| `server_data.json` | `jx3` | `server_data` | 整个文件 JSON | `写入时 + TTL` |
| `data/cache/server_master_cache.json` | `jx3` | `server_master_aliases` | 整个文件 JSON | `写入时 + 7天` |
| `data/wanbaolou_alias_cache.json` | `wanbaolou` | `alias_cache` | 整个文件 JSON | `写入时 + refresh 间隔 * 2` |
| `data/baizhan_images/baizhan_data.json` | `baizhan` | `latest_meta` | 整个文件 JSON | `end_timestamp` 转 `Date` |

推荐通用字段：

```json
{
  "_id": "namespace:key",
  "namespace": "status_monitor",
  "key": "status_history",
  "payload": {},
  "version": 1,
  "updated_at": "2026-03-09T00:00:00Z",
  "expires_at": null,
  "meta": {
    "source_file": "data/cache/status_history.json"
  }
}
```

### B. `jjc_ranking_cache`

映射规则：

| 旧字段 | 新字段 |
| --- | --- |
| `cache_time` | `cache_time` |
| `data` | `data` |
| 无 | `expires_at = cache_time + 7200` |
| 无 | `updated_at` |

目标文档：

```json
{
  "_id": "current",
  "cache_time": 1773470000,
  "data": {},
  "expires_at": "2026-03-09T10:00:00Z",
  "updated_at": "2026-03-09T08:00:00Z"
}
```

### C. `jjc_kungfu_cache`

映射规则：

| 旧字段 | 新字段 |
| --- | --- |
| 文件名 `<server>_<name>.json` | `_id = server + ':' + name` |
| `server` | `server` |
| `name` | `name` |
| `cache_time` | `cache_time` |
| 原文件其余字段 | 同名保留 |
| 无 | `expires_at = cache_time + 7天` |
| 无 | `updated_at` |

补充规则：

- 如果旧文件缺 `server/name`，优先从文件名反推
- 不在迁移时重算 `weapon_checked` / `teammates_checked`
- 不删除未知字段，统一保留

### D. `group_reminders`

映射规则：

| 旧字段 | 新字段 |
| --- | --- |
| `id` | `_id` |
| `group_id` | `group_id` |
| `creator_user_id` | `creator_user_id` |
| `mention_type` | `mention_type` |
| `message` | `message` |
| `remind_at` | `remind_at` |
| `remind_at` | `remind_at_ts` |
| `created_at` | `created_at` |
| `status` | `status` |
| `done_at` | `done_at` |
| `canceled_at` | `canceled_at` |

补充规则：

- `remind_at_ts` 由 `YYYYMMDDHHMMSS` 解析为秒级时间戳
- 若 `group_id` 已存在于记录内，以记录值为准；否则退回顶层 group key

### E. `wanbaolou_subscriptions`

映射规则：

当前旧结构是：

```json
{
  "user_id": [
    {
      "item_name": "...",
      "price_threshold": 100,
      "group_id": 123,
      "created_at": 1773470000
    }
  ]
}
```

目标一条订阅一条文档：

```json
{
  "_id": "41432113:11010783:天选风不欺·无执:1745631849.2131052",
  "group_id": "41432113",
  "user_id": "11010783",
  "item_name": "天选风不欺·无执",
  "price_threshold": 1,
  "created_at": 1745631849.2131052,
  "updated_at": 1745631849.2131052,
  "enabled": true,
  "source": "legacy_json"
}
```

补充规则：

- 旧数据没有真正唯一键，迁移期 `_id` 建议使用 `group_id:user_id:item_name:created_at`
- `group_id` 允许为空；为空时可写成 `null` 或空字符串，但索引策略要统一
- 不建议在迁移时去重，因为当前业务允许同一用户对同一物品配置多个阈值

### F. `jjc_ranking_stats`

映射规则：

| 旧来源 | 新字段 |
| --- | --- |
| 文件名 `<timestamp>.json` | `_id` |
| `generated_at` | `generated_at` |
| `ranking_cache_time` | `ranking_cache_time` |
| `default_week` | `default_week` |
| `current_season` | `current_season` |
| `week_info` | `week_info` |
| `kungfu_statistics` | `kungfu_statistics` |

补充规则：

- 文件名解析失败则跳过，不入库
- 如果库内已存在同 `_id` 文档，默认跳过而不是覆盖

## 索引清单

### 必需索引

```javascript
db.cache_entries.createIndex(
  { namespace: 1, key: 1 },
  { unique: true, name: "uk_namespace_key" }
)

db.jjc_ranking_cache.createIndex(
  { expires_at: 1 },
  { expireAfterSeconds: 0, name: "ttl_expires_at" }
)

db.jjc_kungfu_cache.createIndex(
  { server: 1, name: 1 },
  { unique: true, name: "uk_server_name" }
)

db.jjc_kungfu_cache.createIndex(
  { expires_at: 1 },
  { expireAfterSeconds: 0, name: "ttl_expires_at" }
)

db.group_reminders.createIndex(
  { group_id: 1, status: 1, remind_at_ts: 1 },
  { name: "idx_group_status_remind_at" }
)

db.group_reminders.createIndex(
  { creator_user_id: 1, status: 1, remind_at_ts: 1 },
  { name: "idx_creator_status_remind_at" }
)

db.wanbaolou_subscriptions.createIndex(
  { group_id: 1, user_id: 1, item_name: 1, created_at: 1 },
  { unique: true, name: "uk_group_user_item_created" }
)

db.wanbaolou_subscriptions.createIndex(
  { user_id: 1, enabled: 1 },
  { name: "idx_user_enabled" }
)

db.wanbaolou_subscriptions.createIndex(
  { item_name: 1, enabled: 1 },
  { name: "idx_item_enabled" }
)

db.jjc_ranking_stats.createIndex(
  { generated_at: -1 },
  { name: "idx_generated_at_desc" }
)
```

### 可选索引

- `cache_entries.expires_at`
  - 只有确实启用 TTL 的缓存才需要
- `jjc_kungfu_cache.updated_at`
  - 便于排查热写角色

## 回填脚本执行清单

### Step 1：建索引

- 先创建集合与索引
- TTL 索引先在测试库验证，再上生产库

### Step 2：回填单文档缓存

顺序建议：

1. `cache_entries`
2. `jjc_ranking_cache`
3. `jjc_ranking_stats`

回填规则：

- 文件不存在直接跳过
- JSON 解析失败写错误日志并继续
- 已存在同 key 文档时默认跳过

### Step 3：回填批量文档

顺序建议：

1. `jjc_kungfu_cache`
2. `wanbaolou_subscriptions`
3. `group_reminders`

回填规则：

- 批量写入按 100 到 500 条分批
- 对单条坏数据只记错误，不中断全量回填

### Step 4：生成回填报告

至少输出：

- 扫描文件数
- 成功写入数
- 已存在跳过数
- 解析失败数
- 字段缺失数

## TDD 测试夹具建议

为后续实现准备这些最小夹具：

1. 文件样例夹具
   - `wanbaolou_subscriptions.json`
   - `status_history.json`
   - `jjc_ranking_cache.json`
   - `group_reminders.json`
   - `server_master_cache.json`

2. 映射断言夹具
   - 断言旧 JSON 到目标 Mongo 文档的字段保持一致
   - 断言 `_id`、`expires_at`、`updated_at` 生成规则正确

3. 幂等夹具
   - 同一批样例导入两次，结果不新增重复文档

4. 容错夹具
   - 缺字段 JSON
   - 非法时间格式
   - 空文件
   - 损坏 JSON

建议在实现前先把这些夹具和期望结果定下来，再写导入逻辑。

## 双写期建议

### 读路径

- 先读 Mongo
- Mongo 未命中再回退旧文件
- 如果从旧文件命中，可以异步回填一次 Mongo

### 写路径

- 先写 Mongo
- 再写旧文件
- 任一失败都记录日志，且日志要带集合名/文件名/主键

### 关闭文件写入的前提

- 至少运行一个完整周期
- 启动恢复链路验证通过
- `status_monitor`、`提醒`、`万宝楼订阅`、`jjc_ranking_stats API` 手工回归通过

## 手工验证清单

1. 启动前导入旧文件后，Mongo 中各集合文档数符合预期
2. 机器人启动后，`group_reminders` 中 `pending` 任务能恢复调度
3. 查询竞技场时，`jjc_ranking_cache` 和 `jjc_kungfu_cache` 能写入且命中
4. `/api/jjc/ranking-stats?action=list` 与 `read` 能从 Mongo 返回历史数据
5. `status_monitor` 重启后仍能延续去重状态，不重复推送旧新闻/旧技改/旧兑换码
6. 万宝楼订阅新增、查看、取消、触发提醒后删除，行为与迁移前一致

## 建议的文档后续动作

如果后续真的开始实施代码迁移，还需要补两类文档：

- `docs/design-docs/` 下的 Mongo 存储边界设计
- `docs/references/runbook.md` 下的 Mongo 初始化、索引创建、回填和回滚步骤
