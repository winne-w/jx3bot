# MongoDB 迁移实施计划

## 1. 目标

将项目中基于文件的 JSON 存储和缓存全部迁移到 MongoDB，消除文件系统依赖。迁移后**空库即可启动，无需预填充初始数据**。

**数据库连接**: 通过 `runtime_config.json` 中的 `MONGO_URI` 配置，支持环境变量覆盖。连接串格式见 `config.py` 中 `MONGO_URI` 的注释示例。

## 2. 迁移范围

### 2.1 纳入迁移（10 个集合）

| 序号 | 集合名 | 数据来源 | 空库启动 | 原文件 |
|------|--------|----------|----------|--------|
| 1 | `server_master_cache` | jx3api `/data/server/master` | 缓存 miss→调 API | `data/cache/server_master_cache.json` |
| 2 | `status_cache` | 状态监控定时任务 | 首次运行→拉全量 ID | `data/cache/news_ids.json` 等 |
| 3 | `kungfu_cache` | 推栏 API 多接口聚合 | 缓存 miss→调 API | `data/cache/kungfu/{server}_{name}.json` |
| 4 | `jjc_role_recent` | 推栏 `match/history` | 缓存 miss→调 API | `data/cache/jjc_ranking_inspect/role_recent/` |
| 5 | `jjc_match_detail` | 推栏 `match/detail` | 缓存 miss→调 API | `data/cache/jjc_ranking_inspect/match_detail/` |
| 6 | `jjc_ranking_cache` | 推栏 ranking API | 缓存 miss→调 API | `data/cache/jjc_ranking_cache.json` |
| 7 | `reminders` | 用户在群内创建 | 空=无待提醒 | `data/group_reminders.json` |
| 8 | `wanbaolou_subscriptions` | 用户订阅外观 | 空=无订阅 | `data/wanbaolou_subscriptions.json` |
| 9 | `group_configs` | 管理员绑定群 | 空=无绑定群 | `groups.json` |
| 10 | `runtime_config` | 管理员修改配置 | 空=返回 `{}` | `runtime_config.json` |

### 2.2 不纳入迁移（保留文件）

| 数据 | 原文件 | 保留原因 |
|------|--------|----------|
| PNG 图片（名片/外观/技能图标） | `mpimg/`, `image_cache/`, `data/baizhan_images/*.png` | 二进制数据，文件系统最优 |
| 万宝楼外观目录 | `waiguan.json` | 数 MB 大文件，整读整写，无结构化查询需求 |
| 服务器数据 | `server_data.json` | 外部静态数据，全量加载 |
| 万宝楼别名缓存 | `data/wanbaolou_alias_cache.json` | 内存驻留为主，文件仅冷启动恢复；迁移收益极低 |
| 百战展报 | `data/baizhan_images/baizhan_*.png` | 二进制图片 + JSON，文件系统合适 |
| 重启标记 | `restart_info.json` | 跨进程瞬态标记 |
| 机器人状态 | bot status file | 进程生命周期状态，非持久化数据 |
| JJC排名统计 | `data/jjc_ranking_stats/{ts}/` | 历史快照写入后只读，通过 FastAPI 文件路由对外暴露，迁移需同步改 API 路由；纳入后续迭代 |

## 3. 集合设计

### 3.1 `server_master_cache` — 区服别名缓存

**数据来源**: 调用 jx3api `/data/server/master` 后写入。空库时缓存 miss，调 API 获取。

```javascript
{
  // _id: ObjectId (自动)
  key: "电信一区",           // 标准化区服名
  name: "电信一区",          // 主区服全名
  zone: "电信",
  server_id: "xxx",
  cached_at: 1714200000      // unix timestamp (秒)
}
// 索引:
//   {key: 1} unique
//   {cached_at: 1}  -- TTL: expireAfterSeconds: 604800 (7天)
```

**迁移类**: 新建 `src/storage/mongo_repos/server_master_repo.py`

```python
@dataclass(frozen=True)
class ServerMasterCacheRepo:
    db: AsyncIOMotorDatabase

    async def get(self, key: str) -> dict | None:
        doc = await self.db.server_master_cache.find_one({"key": key})
        if doc is None:
            return None
        # TTL 兜底检查（MongoDB TTL 索引为主，此为双保险）
        if time.time() - doc.get("cached_at", 0) >= 604800:
            await self.db.server_master_cache.delete_one({"key": key})
            return None
        return {"name": doc["name"], "zone": doc["zone"], "id": doc.get("server_id", "")}

    async def put(self, key: str, entry: dict) -> None:
        await self.db.server_master_cache.update_one(
            {"key": key},
            {"$set": {**entry, "cached_at": int(time.time())}},
            upsert=True,
        )

    async def delete(self, key: str) -> None:
        await self.db.server_master_cache.delete_one({"key": key})
```

**改动文件**: `src/services/jx3/server_resolver.py`
- `_get_cached_master_name()` → 调用 `repo.get(key)`
- `_cache_master_result()` → 调用 `repo.put(key, entry)`
- 移除 `json.load`/`json.dump` 文件操作
- 移除模块级 `_cache` 字典、`_cache_loaded` 标志

**验证方式**:
1. 清空 `server_master_cache` 集合，执行 `db.server_master_cache.drop()`
2. 重启机器人，在群里发送区服简称查询命令（如 `/竞技排名 电信一区 角色名`）
3. 观察日志输出：首次应打印 "区服简称缓存未命中" 且成功调 API 解析
4. 查看 MongoDB `server_master_cache` 集合，确认新文档已写入
5. 再次查询同一区服，观察日志应打印 "使用缓存" 且无 API 调用
6. 手动修改一条文档的 `cached_at` 为 8 天前的时间戳，再次查询应触发过期重新获取

---

### 3.2 `status_cache` — 状态监控缓存

**数据来源**: 状态监控定时任务。空库时首次运行拉取当前全量 ID 集合并写入。

```javascript
{
  // _id: ObjectId (自动)
  cache_name: "news_ids",       // 缓存名称
  data: {                       // 缓存内容
    ids: ["id1", "id2", ...]
  },
  updated_at: 1714200000        // unix timestamp (秒)
}
// 索引: {cache_name: 1} unique
```

**迁移类**: 新建 `src/storage/mongo_repos/status_cache_repo.py`

```python
@dataclass(frozen=True)
class StatusCacheRepo:
    db: AsyncIOMotorDatabase

    async def load(self, cache_name: str, default=None):
        doc = await self.db.status_cache.find_one({"cache_name": cache_name})
        if doc is None:
            return default
        return doc.get("data", default)

    async def save(self, cache_name: str, data) -> None:
        await self.db.status_cache.update_one(
            {"cache_name": cache_name},
            {"$set": {"data": data, "updated_at": int(time.time())}},
            upsert=True,
        )
```

**改动文件**: `src/plugins/status_monitor/storage.py`
- `CacheManager.save_cache()` → 调用 `repo.save(cache_name, data)`
- `CacheManager.load_cache()` → 调用 `repo.load(cache_name, default)`
- `save_id_set()` / `load_id_set()` → 上层封装保持不变，底层切到 repo

**验证方式**:
1. 清空 `status_cache` 集合
2. 手动触发状态监控定时任务或等待定时器执行
3. 检查日志 "status_monitor 首次运行，已记录 N 条新闻ID" 应为 N > 0
4. 查看 MongoDB `status_cache` 中 `cache_name="news_ids"` 的文档已写入
5. 再次触发定时任务，日志应显示 "检测到 0 条新增新闻"（因为 ID 全集已在缓存）
6. 手动在 `status_cache` 中写入一条 ID 少于当前实时的数据，再次触发应检测到增量

---

### 3.3 `kungfu_cache` — 心法缓存

**数据来源**: 推栏 API（`role/indicator` + `3c/mine/match/history` + `3c/mine/match/detail`）聚合。空库时缓存 miss，调推栏 API 获取。

```javascript
{
  // _id: ObjectId (自动)
  server: "电信一区",
  name: "角色名",
  kungfu: "离经易道",
  kungfu_id: "10081",
  found: true,
  weapon: "紫微剑·玄天",
  weapon_icon: "https://...",
  weapon_quality: 5,
  weapon_checked: true,
  teammates_checked: true,
  teammates: [
    { name: "队友1", kungfu_id: "10002", kungfu_name: "...", weapon: "...", ... }
  ],
  global_role_id: "...",
  role_id: "...",
  zone: "...",
  cache_time: 1714200000.0   // unix timestamp (秒，浮点)
}
// 索引:
//   {server: 1, name: 1} unique
//   {cache_time: 1}  -- TTL: expireAfterSeconds: 604800 (7天)
```

**迁移类**: 在现有 `JjcCacheRepo` 数据类中新增 MongoDB 操作方法，或新建独立 repo。
不改变 `JjcCacheRepo` 的公开接口签名（`load_kungfu_cache`、`save_kungfu_cache`、`load_kungfu_cache_raw`）。

```python
# 新增方法（在 JjcCacheRepo 或新建 KungfuCacheRepo 中）
async def load_kungfu_cache_mongo(self, server: str, name: str) -> dict | None:
    doc = await self.db.kungfu_cache.find_one({"server": server, "name": name})
    if doc is None:
        return None
    # TTL 兜底（与原有逻辑一致）
    cache_time = doc.get("cache_time", 0)
    if time.time() - cache_time >= self.kungfu_cache_duration:
        # MongoDB TTL 索引会自动清理，此处做即时失效
        return None
    # 原有新鲜度判断逻辑保持不变（weapon_checked, teammates_checked 等）
    return self._validate_kungfu_freshness(doc)

async def save_kungfu_cache_mongo(self, server: str, name: str, result: dict) -> None:
    await self.db.kungfu_cache.update_one(
        {"server": server, "name": name},
        {"$set": {**result, "cache_time": result.get("cache_time", time.time())}},
        upsert=True,
    )
```

**改动文件**: `src/services/jx3/jjc_cache_repo.py`
- `load_kungfu_cache(server, name)` → 内部改为调 MongoDB（保留原方法名和返回值语义）
- `save_kungfu_cache(server, name, result)` → 内部改为写 MongoDB
- `load_kungfu_cache_raw(server, name)` → 同上
- `kungfu_cache_path()` → 可废弃
- 新鲜度判断逻辑保留，MongoDB TTL 索引作为兜底

**验证方式**:
1. 清空 `kungfu_cache` 集合
2. 执行需要角色心法的命令（如 `/竞技排名 电信一区 角色名`）
3. 日志应打印 "心法缓存未命中: reason=cache_file_missing"（message 在过渡期可保持）
4. 调推栏 API 获取心法数据并写入 MongoDB，日志打印 "心法信息已更新缓存"
5. 查看 MongoDB `kungfu_cache` 集合确认文档写入，包含 `server`、`name`、`kungfu` 字段
6. 再次查询同一角色，日志应打印 "使用心法缓存" 且无推栏 API 调用
7. 手动修改 `cache_time` 为 8 天前 + `weapon_checked=false`，再次查询应触发重新获取
8. 在系统中注册 5 个不同服务器/角色，观察 `kungfu_cache` 集合中出现 5 条文档

---

### 3.4 `jjc_role_recent` — 角色近期对局缓存

**数据来源**: 推栏 `3c/mine/match/history`。空库时缓存 miss，调推栏 API 获取。

```javascript
{
  // _id: ObjectId (自动)
  server: "电信一区",
  server_enc: "电信一区",     // URL 编码前原始值
  name: "角色名",
  name_enc: "角色名",
  cached_at: 1714200000.0,
  data: {                     // 推栏 match/history API 响应
    player: {...},
    identity: {...},
    pagination: {...},
    summary: {...},
    recent_matches: [...]
  }
}
// 索引:
//   {server: 1, name: 1} unique
//   {cached_at: 1}  -- TTL: expireAfterSeconds: 600 (10分钟)
```

**迁移类**: 改造 `JjcRankingInspectCacheRepo`

```python
@dataclass(frozen=True)
class JjcRankingInspectCacheRepo:
    db: AsyncIOMotorDatabase
    role_recent_ttl_seconds: int = 600

    async def load_role_recent(self, server: str, name: str) -> dict | None:
        doc = await self.db.jjc_role_recent.find_one({"server": server, "name": name})
        if doc is None:
            return None
        cached_at = doc.get("cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        if time.time() - float(cached_at) > self.role_recent_ttl_seconds:
            return None
        return {"cached_at": cached_at, "data": doc.get("data")}

    async def save_role_recent(self, server: str, name: str, payload: dict) -> None:
        await self.db.jjc_role_recent.update_one(
            {"server": server, "name": name},
            {"$set": {"cached_at": payload.get("cached_at", time.time()), "data": payload.get("data", payload)}},
            upsert=True,
        )
```

**改动文件**: `src/storage/jjc_ranking_inspect_cache.py`
- 替换文件 I/O 为 MongoDB 读写
- 保留 TTL 检查逻辑（MongoDB TTL 索引兜底）
- `_role_recent_path()` → 废弃

**验证方式**:
1. 清空 `jjc_role_recent` 集合
2. 触发竞技排名中的角色下钻查询（查看某角色近期对局）
3. 观察日志 "JJC 角色近期缓存未命中"，确认调推栏 API
4. 查看 MongoDB `jjc_role_recent` 集合确认数据写入
5. 10 分钟内再次查询同一角色，日志应显示使用缓存且无 API 调用
6. 等待或手动修改 `cached_at` 超过 600 秒，再次查询应触发重新获取

---

### 3.5 `jjc_match_detail` — 对局详情缓存

**数据来源**: 推栏 `3c/mine/match/detail`。空库时缓存 miss，调推栏 API 获取。无 TTL。

```javascript
{
  // _id: ObjectId (自动)
  match_id: "12345678",        // 对局 ID（整数）
  cached_at: 1714200000.0,
  data: {                      // 推栏 match/detail API 响应
    match_id: ...,
    detail: {...},
    cache: {...}
  }
}
// 索引: {match_id: 1} unique
```

**迁移类**: 在 `JjcRankingInspectCacheRepo` 中增补

```python
async def load_match_detail(self, match_id: int | str) -> dict | None:
    doc = await self.db.jjc_match_detail.find_one({"match_id": int(match_id)})
    return doc  # 返回完整文档或 None

async def save_match_detail(self, match_id: int | str, payload: dict) -> None:
    await self.db.jjc_match_detail.update_one(
        {"match_id": int(match_id)},
        {"$set": {"cached_at": payload.get("cached_at", time.time()), "data": payload.get("data", payload)}},
        upsert=True,
    )
```

**改动文件**: `src/storage/jjc_ranking_inspect_cache.py`
- 替换 `_match_detail_path()` + 文件 I/O 为 MongoDB 读写
- `_load_json()` → 废弃

**验证方式**:
1. 清空 `jjc_match_detail` 集合
2. 触发对局详情查询（点击某角色的某场对局）
3. 日志显示对局详情缓存未命中，调推栏 API
4. 查看 MongoDB `jjc_match_detail` 集合确认数据写入
5. 再次查询同一 `match_id`，日志应显示使用缓存

---

### 3.6 `jjc_ranking_cache` — 竞技排名缓存

**数据来源**: 推栏 ranking API。空库时缓存 miss，调推栏 API 获取。

```javascript
{
  // _id: ObjectId (自动) 或固定 key
  cache_key: "ranking",        // 固定 key，单文档覆盖写
  cache_time: 1714200000.0,
  data: { ... },               // 排名原始数据（大型嵌套对象）
  created_at: ISODate
}
// 索引:
//   {cache_key: 1} unique
//   {created_at: 1}  -- TTL: expireAfterSeconds: 7200 (2小时)
```

**迁移类**: 在 `JjcCacheRepo` 中增补 MongoDB 方法

```python
async def load_ranking_cache_mongo(self) -> dict | None:
    doc = await self.db.jjc_ranking_cache.find_one({"cache_key": "ranking"})
    if doc is None:
        return None
    if time.time() - doc.get("cache_time", 0) >= self.jjc_ranking_cache_duration:
        return None
    return doc.get("data")

async def save_ranking_cache_mongo(self, ranking_result: dict) -> None:
    await self.db.jjc_ranking_cache.update_one(
        {"cache_key": "ranking"},
        {"$set": {
            "cache_time": ranking_result.get("cache_time", time.time()),
            "data": ranking_result,
            "created_at": datetime.utcnow(),
        }},
        upsert=True,
    )
```

**改动文件**: `src/services/jx3/jjc_cache_repo.py`
- `load_ranking_cache()` → 内部切到 MongoDB
- `save_ranking_cache()` → 内部切到 MongoDB
- 不改变方法签名（这些方法目前是同步的，需要改为 `async`）

**验证方式**:
1. 清空 `jjc_ranking_cache` 集合
2. 执行 `/竞技排名` 命令查询排行榜
3. 日志显示 "竞技场排行榜文件缓存已过期"（message 可保留），调推栏 API
4. 查看 MongoDB `jjc_ranking_cache` 集合确认数据写入
5. 2 小时内再次查询，日志应显示 "使用缓存"
6. 修改 `cache_time` 超过 7200 秒，再查询应触发重新获取

---

### 3.7 `reminders` — 群提醒

**数据来源**: 用户在群内通过命令创建提醒。空库 = 无待提醒。

```javascript
{
  // _id: ObjectId (自动)
  reminder_id: "abc123def456...",  // uuid hex
  group_id: "123456",              // QQ 群号 (字符串)
  creator_user_id: "789012",       // 创建者 QQ 号
  mention_type: "user",            // "user" | "all"
  message: "记得打攻防",
  remind_at_str: "20260427203000", // YYYYMMDDHHMMSS 原格式
  remind_at: ISODate("2026-04-27T20:30:00Z"),  // 解析后时间，用于查询/排序
  status: "pending",               // "pending" | "done" | "canceled"
  created_at: 1714200000,          // unix timestamp (秒)
  done_at: null,                   // 完成时间或 null
  canceled_at: null                // 取消时间或 null
}
// 索引:
//   {reminder_id: 1} unique
//   {group_id: 1, status: 1}
//   {status: 1, remind_at: 1}      -- 用于启动时恢复 pending 提醒
```

**迁移类**: 新建 `src/storage/mongo_repos/reminder_repo.py`

```python
@dataclass(frozen=True)
class ReminderRepo:
    db: AsyncIOMotorDatabase

    async def load_by_group(self, group_id: int) -> list[dict]:
        """返回指定群所有 reminder 列表（兼容原 grouped dict 结构）"""
        cursor = self.db.reminders.find({"group_id": str(group_id)})
        return await cursor.to_list(length=None)

    async def load_all_pending(self) -> dict[str, list[dict]]:
        """返回 {group_id: [pending_reminders]} 用于启动恢复"""
        cursor = self.db.reminders.find({"status": "pending"})
        result = {}
        async for doc in cursor:
            gid = doc["group_id"]
            result.setdefault(gid, []).append(doc)
        return result

    async def insert(self, reminder: dict) -> None:
        await self.db.reminders.insert_one(reminder)

    async def find_by_id(self, reminder_id: str) -> dict | None:
        return await self.db.reminders.find_one({"reminder_id": reminder_id})

    async def update_status(self, reminder_id: str, status: str, ts_field: str) -> bool:
        result = await self.db.reminders.update_one(
            {"reminder_id": reminder_id, "status": "pending"},
            {"$set": {"status": status, ts_field: int(time.time())}},
        )
        return result.modified_count > 0

    async def cancel(self, reminder_id: str, group_id: int, user_id: int) -> dict | None:
        doc = await self.db.reminders.find_one_and_update(
            {
                "reminder_id": reminder_id,
                "group_id": str(group_id),
                "creator_user_id": str(user_id),
                "status": "pending",
            },
            {"$set": {"status": "canceled", "canceled_at": int(time.time())}},
        )
        return doc
```

**改动文件**: `src/plugins/jx3bot_handlers/reminder.py`
- `_load_reminders_unlocked()` → 改为调 `repo.load_all_pending()`
- `_save_reminders_unlocked()` → 改为 `repo.insert()` / `repo.update_status()`
- `create_reminder()` → 改为 `repo.insert()`
- `mark_reminder_done()` → 改为 `repo.update_status()`
- `cancel_reminder()` → 改为 `repo.cancel()`
- `get_group_pending_reminders()` → 改为 `repo.load_by_group()` + 内存过滤
- `find_pending_reminder()` → 改为 `repo.find_by_id()`
- `load_reminders()` → 改为 `repo.load_all_pending()`
- 移除 `FILE_LOCK`、`REMINDER_FILE` 常量

**这个迁移需要重构数据结构**：原格式是 `{group_id: [{reminder}, ...]}`，新格式是每 reminder 一条文档。`_restore_reminder_jobs()` 启动恢复逻辑需适配。

**验证方式**:
1. 清空 `reminders` 集合，重启机器人
2. 启动日志应显示 "提醒任务恢复完成，共恢复 0 条"（正常空库）
3. 在群内创建提醒: `/提醒 20260427203000 记得打攻防`
4. 查看 MongoDB `reminders` 集合确认新文档已写入，字段完整
5. 查询提醒列表: `/提醒列表`，应正确显示刚创建的提醒
6. 取消提醒: `/取消提醒`，MongoDB 文档 `status` 应变为 "canceled"
7. 创建一条马上到期的提醒，等待触发 → 检查机器人是否正常发送并标记为 "done"
8. 创建多条 pending 提醒后重启机器人，确认所有 pending 提醒被重新调度

---

### 3.8 `wanbaolou_subscriptions` — 万宝楼订阅

**数据来源**: 用户在群内通过命令订阅外观。空库 = 无订阅。

```javascript
{
  // _id: ObjectId (自动)
  user_id: "123456789",       // QQ 号
  item_name: "五红·黑发",
  price_threshold: 50000,     // 价格阈值 (金)
  group_id: "987654321",
  created_at: 1714200000.0,   // unix timestamp
  active: true
}
// 索引:
//   {user_id: 1}
//   {user_id: 1, item_name: 1} unique   -- 防止重复订阅
```

**迁移类**: 新建 `src/storage/mongo_repos/wanbaolou_sub_repo.py`

```python
@dataclass(frozen=True)
class WanbaolouSubRepo:
    db: AsyncIOMotorDatabase

    async def find_by_user(self, user_id: str) -> list[dict]:
        cursor = self.db.wanbaolou_subscriptions.find({"user_id": user_id, "active": True})
        return await cursor.to_list(length=None)

    async def add(self, user_id: str, item_name: str, price_threshold, group_id: str) -> bool:
        try:
            await self.db.wanbaolou_subscriptions.update_one(
                {"user_id": user_id, "item_name": item_name},
                {"$set": {
                    "price_threshold": price_threshold,
                    "group_id": group_id,
                    "created_at": time.time(),
                    "active": True,
                }},
                upsert=True,
            )
            return True
        except Exception:
            return False

    async def remove_by_index(self, user_id: str, index: int) -> dict | None:
        subs = await self.find_by_user(user_id)
        if index < 1 or index > len(subs):
            return None
        target = subs[index - 1]
        await self.db.wanbaolou_subscriptions.update_one(
            {"_id": target["_id"]},
            {"$set": {"active": False}},
        )
        return target

    async def count_all(self) -> int:
        return await self.db.wanbaolou_subscriptions.count_documents({"active": True})

    async def all(self) -> list[dict]:
        cursor = self.db.wanbaolou_subscriptions.find({"active": True})
        return await cursor.to_list(length=None)
```

**改动文件**: `src/plugins/wanbaolou/__init__.py`
- `load_subscriptions()` → 改为 `repo.all()` 按需
- `save_subscriptions()` → 不再需要全量保存，改为单条 `repo.add()`
- `add_subscription()` → 改为 `repo.add()`
- `get_user_subscriptions()` → 改为 `repo.find_by_user()`
- `remove_subscription()` → 改为 `repo.remove_by_index()`
- `get_all_subscriptions()` → 改为 `repo.all()`
- 移除 `SUBSCRIPTION_FILE`、`ensure_dir_exists()`、文件 I/O

**验证方式**:
1. 清空 `wanbaolou_subscriptions` 集合
2. 在群内添加订阅: `/订阅外观 五红·黑发 50000`
3. 查看 MongoDB `wanbaolou_subscriptions` 集合确认文档写入
4. 查询订阅: `/我的订阅`，应正确显示
5. 删除订阅: `/取消订阅 1`，文档 `active` 应变为 `false`
6. 添加多条订阅后查询，确认只显示 `active: true` 的
7. 重复订阅同一物品 → 应更新价格阈值而非新增

---

### 3.9 `group_configs` — 群组绑定配置

**数据来源**: 管理员在群内通过命令绑定群与服务器。空库 = 无绑定群，查询时返回空配置。

```javascript
{
  // _id: ObjectId (自动)
  group_id: "123456",           // QQ 群号 (字符串)
  servers: "电信一区",
  features: {
    server_open: true,          // 开服推送
    news: true,                 // 新闻推送
    skill_change: true,         // 技改推送
    welfare: true,              // 福利推送
    daily: true,                // 日常推送
    jjc_ranking: true           // 竞技排名推送
  },
  updated_at: 1714200000
}
// 索引: {group_id: 1} unique
```

**迁移类**: 改造现有 `GroupConfigRepo`

```python
@dataclass
class GroupConfigRepo:
    db: AsyncIOMotorDatabase
    _cache: dict[str, Any] | None = None  # 保留内存缓存
    _cache_version: int = 0                 # 替代 mtime

    async def load(self) -> dict[str, Any]:
        # 加载全部群配置为 {group_id: {servers, features}} 格式
        if self._cache is not None:
            return self._cache
        cursor = self.db.group_configs.find({})
        result = {}
        async for doc in cursor:
            gid = doc["group_id"]
            cfg = {"servers": doc.get("servers", "")}
            for feat, enabled in (doc.get("features") or {}).items():
                cfg[feat] = enabled
            result[gid] = cfg
        self._cache = result
        return result

    async def save(self, data: dict[str, Any]) -> None:
        # data = {group_id: {servers, 开服推送, ...}}
        for group_id, cfg in data.items():
            feature_map = {}
            for key in ("开服推送", "新闻推送", "技改推送", "福利推送", "日常推送", "竞技排名推送"):
                if key in cfg:
                    feature_map[key] = cfg[key]
            await self.db.group_configs.update_one(
                {"group_id": str(group_id)},
                {"$set": {
                    "servers": cfg.get("servers", ""),
                    "features": feature_map,
                    "updated_at": int(time.time()),
                }},
                upsert=True,
            )
        self._cache = data  # 刷内存缓存

    def invalidate_cache(self) -> None:
        self._cache = None
```

**改动文件**:
- `src/services/jx3/group_config_repo.py` → 改造为 MongoDB 读写
- `src/services/jx3/group_binding.py` → `load_groups()` 和 `get_server_by_group()` 改用 repo
- `src/services/jx3/singletons.py` → `GroupConfigRepo` 实例化改为 `GroupConfigRepo(db=get_db())`

**验证方式**:
1. 清空 `group_configs` 集合，重启机器人
2. 在未绑定群发送 `/竞技排名 角色名`，应提示"请先绑定服务器"
3. 管理员在群内绑定: `/绑定服务器 电信一区`
4. 查看 MongoDB `group_configs` 集合确认文档写入，`features` 字段完整
5. 查询绑定: `/查看绑定`，应显示刚绑定的服务器
6. 修改功能开关: `/设置推送 开服推送 关闭`，MongoDB 文档 `features.server_open` 应变为 false
7. 多个群绑定不同服务器，`group_configs` 中应有对应多条文档

---

### 3.10 `runtime_config` — 运行时配置

**数据来源**: 管理员通过 `/修改配置` 命令修改。空库时 `read_config_file()` 返回 `{}`。

```javascript
// 方案 A: 单文档
{
  _id: "runtime_config",
  config: {
    TOKEN: "xxx",
    TICKET: "yyy",
    SESSION_data: 720,
    calendar_time: 8,
    STATUS_check_time: 60
  },
  updated_at: 1714200000
}

// 方案 B (推荐): 键值文档，与当前代码风格一致
{
  // _id: ObjectId (自动)
  key: "TOKEN",
  value: "xxx",
  updated_at: 1714200000
}
// 索引: {key: 1} unique
```

推荐方案 A（单文档），因为当前使用场景是整读整写。

**迁移类**: 新建 `src/storage/mongo_repos/runtime_config_repo.py`

```python
@dataclass(frozen=True)
class RuntimeConfigRepo:
    db: AsyncIOMotorDatabase

    async def load(self) -> dict:
        doc = await self.db.runtime_config.find_one({"_id": "runtime_config"})
        if doc is None:
            return {}
        return doc.get("config", {})

    async def save(self, config: dict) -> None:
        await self.db.runtime_config.update_one(
            {"_id": "runtime_config"},
            {"$set": {"config": config, "updated_at": int(time.time())}},
            upsert=True,
        )
```

**改动文件**: `src/plugins/config_manager.py`
- `read_config_file()` → 改为 `await repo.load()`
- `write_config_file(content)` → 改为 `await repo.save(content)`
- 移除 `CONFIG_FILE`、文件 I/O

**验证方式**:
1. 清空 `runtime_config` 集合，重启机器人
2. 管理员发送 `/查看配置`，应正常响应（显示默认值或空）
3. 管理员修改配置: `/修改配置 SESSION_data=500`
4. 查看 MongoDB `runtime_config` 集合确认文档写入
5. 再次 `/查看配置`，应显示 `SESSION_data = 500`
6. 重启后发送 `/查看配置`，确认配置持久化正常

## 4. 整体迁移步骤

### 总进度

**阶段一：基础设施**

- [x] 4.1.1 安装 `motor` 依赖（`requirements.txt` 已添加，Docker build 通过）
- [x] 4.1.2 新建 `src/infra/mongo.py`（连接管理 + 索引创建，含容错处理）
- [x] 4.1.3 修改 `bot.py`（启动时初始化 MongoDB）
- [x] 4.1.4 ~~重构 `src/services/jx3/singletons.py`~~（延后至各集合迁移时随 repo 改造进行）
- [x] 4.1.5 `config.py` 添加 `MONGO_URI` 配置项 + `runtime_config.json` 配置实际连接串
- [x] **Demo 验证**: `GET /api/mongo/health` 返回 `connected: true`，ping 10ms，13 个集合已创建

**阶段二：逐集合迁移**

- [x] 4.2.1 `server_master_cache` → `server_resolver.py`（低风险） ✅
- [x] 4.2.2 `status_cache` → `status_monitor/storage.py`（低风险） ✅
- [x] 4.2.3 `jjc_ranking_cache` → `JjcCacheRepo`（低风险） ✅
- [x] 4.2.4 `kungfu_cache` → `JjcCacheRepo`（中风险） ✅
- [x] 4.2.5 `jjc_role_recent` → `JjcRankingInspectCacheRepo`（中风险） ✅
- [ ] 4.2.6 `jjc_match_detail` → `JjcRankingInspectCacheRepo`（中风险）
- [ ] 4.2.7 `runtime_config` → `config_manager.py`（低风险）
- [ ] 4.2.8 `wanbaolou_subscriptions` → `wanbaolou/__init__.py`（中风险）
- [ ] 4.2.9 `reminders` → `reminder.py`（高风险）
- [ ] 4.2.10 `group_configs` → `GroupConfigRepo` + `group_binding.py`（高风险）

**阶段三：清理收尾**

- [ ] 4.3.1 删除已迁移的 `data/cache/*.json` 文件
- [ ] 4.3.2 删除已迁移的顶级 JSON 文件（`groups.json`、`runtime_config.json`、`data/group_reminders.json`、`data/wanbaolou_subscriptions.json`）
- [ ] 4.3.3 更新 `README.md`：增加 MongoDB 依赖说明
- [ ] 4.3.4 更新 `docs/references/runbook.md`：增加 MongoDB 连接排查步骤
- [ ] 4.3.5 更新 `CLAUDE.md`：存储层描述调整为 MongoDB
- [ ] 4.3.6 移除所有过渡期 fallback 代码
- [ ] 4.3.7 更新 `docker-compose.yml`：移除已迁移文件的 volume 挂载（`groups.json`、`server_data.json` 等），移除 `runtime_config.json` 挂载（改用 MongoDB 或环境变量）

---

### 4.1 基础设施（阶段一）

**4.1.1 MongoDB 驱动选型与引入**

Python 连接 MongoDB 有两个主流库：

| 驱动 | 同步/异步 | 生态成熟度 | 适用场景 |
|------|-----------|-----------|----------|
| `pymongo` | 同步（有 `motor` 作为异步封装） | MongoDB 官方维护 | 同步项目直接使用 |
| `motor` | 异步（基于 `asyncio`，底层依赖 `pymongo`） | MongoDB 官方孵化 | 异步框架（NoneBot/FastAPI） |

本项目运行时基于 **NoneBot2 + FastAPI**，核心 I/O 路径全面使用 `asyncio`（`httpx.AsyncClient`、`aiofiles`、`APScheduler` async job）。因此选用 `motor`：

- API 与 `pymongo` 高度一致，学习成本低
- 原生 `async/await`，不阻塞事件循环
- 内置连接池管理，与 `httpx` 连接池模式一致
- `motor.motor_asyncio.AsyncIOMotorClient` 直接返回协程友好的集合对象

**安装方式**：在 `requirements.txt` 中添加 `motor>=3.0,<4.0`，然后：

```bash
# 本地开发
pip install -r requirements.txt

# 服务器 Docker（Dockerfile 第 42-46 行已包含 pip install -r requirements.txt）
docker compose up --build -d
```

`motor` 会自动拉取兼容版本的 `pymongo` 作为依赖（`motor>=3.0` 对应 `pymongo>=4.0`）。

**在项目中的集成位置**：

`motor` 属于外部适配层，按照项目分层约束放在 `src/infra/mongo.py`，与 `src/infra/http_client.py`（HTTP 适配）同级。上层 `services` 和 `storage/mongo_repos/` 通过 `get_db()` 获取 `AsyncIOMotorDatabase` 实例，不直接依赖 `motor` 的具体类型。

```python
# 调用链
bot.py 启动
  → await init_mongo(MONGO_URI)       # src/infra/mongo.py：建立连接、创建索引
    → 各 repo 通过 get_db() 获取 db   # src/storage/mongo_repos/*.py：封装 CRUD
      → services 调用 repo 方法       # src/services/jx3/*.py：业务编排
```

与现有 `cacheout.Cache`（内存 LRU）和 `SimpleCache`（dict TTL）的关系：
- `motor` 接管**持久化缓存/存储**层（文件 JSON 的替代）
- 内存缓存 `cacheout.Cache` / `SimpleCache` **保持不变**（热路径短路，减少 MongoDB 查询）
- 典型查询链路：内存缓存 → MongoDB → 外部 API

**4.1.2 新建 `src/infra/mongo.py`**

MongoDB 连接管理模块，提供：
- `init_mongo(uri: str) -> AsyncIOMotorDatabase`: 连接并创建索引（幂等）
- `get_db() -> AsyncIOMotorDatabase`: 获取 db 实例

关键实现点：
- 连接池 maxPoolSize=10
- 启动时调用 `_ensure_indexes(db)` 创建所有集合的索引（`create_index` 在已存在索引时是幂等的）
- TTL 索引使用 `expireAfterSeconds`
- 密码使用环境变量 `MONGO_URI`，不硬编码

**4.1.3 修改 `bot.py`**

在 `nonebot.init()` 之后、`load_from_toml` 之前插入：

```python
from config import MONGO_URI
from src.infra.mongo import init_mongo

@driver.on_startup
async def startup_mongo():
    await init_mongo(MONGO_URI)
    logger.info("MongoDB 初始化完成")
```

**4.1.4 重构 `src/services/jx3/singletons.py`**

将 `db` 注入到需要的 repo/service 实例中。改造策略：
- `GroupConfigRepo` 接收 `db` 而非 `path`
- `JjcCacheRepo` 接收 `db` 而非缓存文件路径
- `JjcRankingInspectCacheRepo` 接收 `db` 而非 `base_dir`
- 新实例化代码从 `get_db()` 获取 db

### 4.2 逐集合迁移（阶段二）

迁移顺序按风险从低到高：

| 步序 | 集合 | 迁移策略 | 风险 |
|------|------|----------|------|
| 1 | `server_master_cache` | 全新 repo，替换 `server_resolver.py` | 低 |
| 2 | `status_cache` | 全新 repo，替换 `status_monitor/storage.py` | 低 |
| 3 | `jjc_ranking_cache` | 在 `JjcCacheRepo` 中增加 MongoDB 方法 | 低 |
| 4 | `kungfu_cache` | 在 `JjcCacheRepo` 中增加 MongoDB 方法 | 中 |
| 5 | `jjc_role_recent` | 改造 `JjcRankingInspectCacheRepo` | 中 |
| 6 | `jjc_match_detail` | 改造 `JjcRankingInspectCacheRepo` | 中 |
| 7 | `runtime_config` | 全新 repo，替换 `config_manager.py` | 低 |
| 8 | `wanbaolou_subscriptions` | 全新 repo，替换 `wanbaolou/__init__.py` | 中 |
| 9 | `reminders` | 全新 repo，替换 `reminder.py` | 高 |
| 10 | `group_configs` | 改造 `GroupConfigRepo` + `group_binding.py` | 高 |

每一步执行流程：
1. 新建/改造 repo 类
2. 修改调用方代码，替换文件 I/O 为 repo 调用
3. 运行验证流程（见各集合的验证方式）
4. 确认正常后删除旧文件读写代码

### 4.3 清理收尾（阶段三）

具体条目见上方总进度「阶段三」，核心工作：
- 删除已迁移的旧 JSON 文件
- 更新项目文档（README / runbook / CLAUDE.md）
- 移除过渡期 fallback 代码

## 5. 风险与回滚

### 风险

| 风险 | 影响 | 应对 |
|------|------|------|
| MongoDB 连接失败 | 所有缓存/存储不可用 | 启动时检测连接，失败则阻止启动；增加连接重试 |
| TTL 索引删除延迟 | 过期数据可能被读 | 保留应用层 TTL 检查作为双保险 |
| `reminders` 结构变化 | 启动恢复逻辑走样 | 充分测试 `_restore_reminder_jobs()` |
| `group_configs` 是核心配置 | 出问题影响所有群功能 | 最后迁移，保留文件 fallback 至少一周 |

### 回滚方案

每个集合在迁移时保留旧文件读取代码作为 **fallback**：

```python
async def load_xxx(self, key):
    # 优先读 MongoDB
    doc = await self._load_from_mongo(key)
    if doc is not None:
        return doc
    # fallback 到旧文件
    return self._load_from_file(key)  # 旧逻辑
```

稳定运行 1-2 周后移除 fallback 代码。

## 6. 目录结构变更

迁移完成后 `data/` 目录仅保留：

```
data/
├── jjc_ranking_stats/       # 统计快照（暂保留，后续迭代迁移）
├── baizhan_images/           # 百战展报图片
│   ├── baizhan_data.json
│   └── baizhan_latest.png
└── wanbaolou_alias_cache.json  # 别名缓存（暂保留）

mpimg/                        # 静态图片服务（不变）
├── wanbaolou/
├── img/
│   └── baizhan/
└── ...

image_cache/                  # 图片下载缓存（不变）
```

`src/storage/mongo_repos/` 新增：

```
src/storage/mongo_repos/
├── __init__.py
├── server_master_repo.py
├── status_cache_repo.py
├── kungfu_cache_repo.py         (或直接在 JjcCacheRepo 中处理)
├── jjc_inspect_repo.py          (改造自 JjcRankingInspectCacheRepo)
├── jjc_ranking_repo.py          (或在 JjcCacheRepo 中处理)
├── reminder_repo.py
├── wanbaolou_sub_repo.py
├── group_config_repo.py         (改造自 GroupConfigRepo)
└── runtime_config_repo.py
```

## 7. 时间估算

| 阶段 | 内容 | 预估 |
|------|------|------|
| 阶段一 | 基础设施（mongo.py + bot.py 改造 + 索引创建 + singletons 改造） | 2-3 天 |
| 阶段二-1 | server_master_cache + status_cache + jjc_ranking_cache | 1.5 天 |
| 阶段二-2 | kungfu_cache + jjc_role_recent + jjc_match_detail | 2 天 |
| 阶段二-3 | runtime_config + wanbaolou_subscriptions | 1.5 天 |
| 阶段二-4 | reminders + group_configs | 2.5 天 |
| 阶段三 | 清理、文档、双写验证 | 1 天 |
| **合计** | | **10-12 天** |
