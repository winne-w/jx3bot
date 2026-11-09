# JJC 排名角色弹窗后端缓存统一 24 小时计划

## 背景

排名统计页面角色弹窗同时请求近期对局列表和赛季战绩 indicator。当前 indicator 后端缓存为 24 小时，近期对局列表后端缓存为 10 分钟，用户要求后端缓存统一改成 24 小时；前端页面内存缓存仍保留 10 分钟，避免同一页面会话内长时间不重新请求后端。

## 目标

- 将 `role-recent` 后端业务 TTL 从 600 秒调整为 86400 秒。
- 保留排名页面前端 `roleRecentCache` 内存有效期 600000 毫秒。
- 保持 `role-indicator` 现有 86400 秒 TTL 不变。
- 同步数据库设计文档与索引初始化中的 `jjc_role_recent.cached_at` 过期声明。

## 涉及文件

- `src/services/jx3/jjc_ranking_inspect.py`
- `src/services/jx3/singletons.py`
- `src/infra/mongo.py`
- `public/jjc-ranking-stats.html`
- `docs/design-docs/database-design.md`

## 实施步骤

1. 修改 inspect service 默认 `role_recent_ttl_seconds` 为 86400。
2. 修改 singletons 装配值为 86400，确保运行实例使用新 TTL。
3. 保持前端角色近期对局内存缓存判断为 600000 毫秒。
4. 修改 Mongo 索引初始化和数据库设计文档中的 `jjc_role_recent` TTL 说明为 86400 秒。
5. 运行 Python 编译检查，并用文本检索确认后端/数据库旧的 600 秒口径不再用于角色近期对局缓存。

## 验证方式

- `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/services/jx3/singletons.py src/infra/mongo.py`
- `rg -n "role_recent_ttl_seconds=600|role_recent_ttl_seconds: int = 600|expireAfterSeconds=600|TTL 600" src public docs/design-docs`

## 执行状态

- 2026-05-25：已将后端 `role-recent` TTL、singletons 装配值、Mongo 索引初始化和数据库设计文档统一调整为 24 小时；索引初始化补充 `expireAfterSeconds` 差异检测，确保同名 TTL 索引配置变更可被重建。
- 2026-05-25：根据用户补充要求，排名页前端 `roleRecentCache` 内存缓存保留 600000 毫秒；后端与数据库缓存仍为 86400 秒。
- 2026-05-25：已通过 Python 编译检查；已确认 `src`、`public`、`docs/design-docs` 中不再存在后端/数据库角色近期对局缓存的 600 秒旧口径。

## 回滚

将后端 TTL、singletons 装配值、Mongo 索引初始化和数据库设计文档恢复为 600 秒；前端内存缓存已保持 600000 毫秒，无需额外回滚。
