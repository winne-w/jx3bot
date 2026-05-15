# JJC 定时统计预热页面缓存计划

## 状态

- 2026-05-14：已实现后端缓存预热、`role_indicator` 1 天 TTL、`force_refresh` 参数和前端刷新按钮；聚焦单测与编译检查已通过，待提交。

## 需求

每日 08:00 竞技排名统计任务已经会请求推栏 `role/indicator`、`3c/mine/match/history`、`3c/mine/match/detail` 来补全角色心法、武器和队友信息。当前这些结果主要写入 `role_jjc_cache`，不能完整复用到排行榜页面的下钻缓存。

目标：

1. 定时统计过程中已经拿到的推栏结果写入 Mongo，尽量复用到排行榜页面。
2. `role_indicator` 页面缓存时间从 600 秒延长到 1 天。
3. 排行榜页面角色弹窗提供主动刷新按钮，用户点击后绕过 `role_indicator` 缓存并写回最新结果。

## 非目标

- 不改变 JJC 心法统计口径。
- 不扩大定时任务请求量；优先复用定时任务已经请求到的结果。
- 不在统计快照 `summary/details` 中塞入推栏原始响应。
- 不改变推栏签名、请求头、URL 和接口限速策略。
- 不改变 `match/history` 最近战绩页面缓存 TTL，除非实施时明确补充并另行记录。

## 现状

- 定时统计入口：`src/plugins/status_monitor/jobs.py` 的 `push_daily_jjc_ranking()`。
- 定时统计逐个排行榜角色调用 `JjcRankingService.get_user_kungfu()`，内部通过 `get_kungfu_detail_by_role_info()` 请求：
  - `https://m.pvp.xoyo.com/role/indicator`
  - `https://m.pvp.xoyo.com/3c/mine/match/history`
  - `https://m.pvp.xoyo.com/3c/mine/match/detail`
- 页面角色指标缓存集合是 `jjc_role_indicator`，当前只由 `JjcRankingInspectService.get_role_indicator()` 写入，业务 TTL 为 600 秒。
- 页面对局详情缓存集合是 `jjc_match_detail`，当前只由 `JjcRankingInspectService.get_match_detail()` 写入。
- 定时统计请求到的 `match/detail` 当前只抽取 `weapon`、`kungfu_id`、`teammates` 写入 `role_jjc_cache`，不会写入 `jjc_match_detail`。

## 影响范围

- `src/services/jx3/kungfu.py`
  - 调整 `get_kungfu_detail_by_role_info()` 的返回结构，保留已请求到的原始 `role_indicator`、`match_history`、`match_detail` 或等价可缓存 payload。
  - 注意不要把大对象直接写入 `role_jjc_cache`，只作为调用方继续写页面缓存的中间结果。
- `src/services/jx3/jjc_ranking.py`
  - 在定时/手动排名统计查询角色心法时，将 `kungfu.py` 返回的可缓存结果写入页面缓存集合。
  - 保持已有 `role_jjc_cache` 写入逻辑不退化。
- `src/services/jx3/jjc_ranking_inspect.py`
  - `role_indicator` TTL 从 600 秒调整为 86400 秒。
  - 增加强制刷新参数，例如 `force_refresh: bool = False`；为真时跳过 `jjc_role_indicator` 读取，实时请求推栏并写回 Mongo。
  - 继续走端点互斥锁和现有错误处理。
- `src/storage/mongo_repos/jjc_inspect_repo.py`
  - 复用或补充保存方法：`save_role_indicator()`、`save_match_detail()`。
  - 若定时统计写入 `match_detail`，需复用 `_extract_snapshots()`，避免绕过详情快照拆表逻辑。
- `src/api/routers/jjc_ranking_stats.py`
  - 角色 indicator 接口增加 `force_refresh` 查询参数。
  - 保持默认读取缓存，按钮刷新时由前端传入强制刷新。
- `public/jjc-ranking-stats.html`
  - 在角色弹窗 indicator 区域增加刷新按钮。
  - 刷新时显示加载状态，调用 `force_refresh=true`，成功后替换当前 indicator 数据，失败时保留旧数据并提示错误。
- `docs/design-docs/database-design.md`
  - 更新 `jjc_role_indicator` 业务 TTL 说明为 1 天。
  - 说明定时统计可写入 `jjc_role_indicator` 与 `jjc_match_detail`。
- `docs/references/runbook.md`
  - 增加手工回归：定时统计后页面查看角色/对局是否命中缓存，刷新按钮是否绕过缓存。

## 数据写入策略

### `role/indicator`

- 定时统计拿到原始 `role/indicator` 后，解析出与页面一致的 3v3 indicator 结构。
- 使用 `identity_key` 作为 `jjc_role_indicator.cache_key`，优先为 `global:<global_role_id>`。
- 写入字段保持与现有 `save_role_indicator()` 一致：
  - `identity_key`
  - `server`
  - `name`
  - `game_role_id`
  - `global_role_id`
  - `zone`
  - `indicator`
  - `raw`
  - `cached_at`
- 若无法解析 `global_role_id` 或 `identity_key`，不写 `jjc_role_indicator`，只保留现有 `role_jjc_cache` 行为。

### `match/detail`

- 定时统计拿到最近胜场 `match/detail` 后，如响应 `code == 0` 且存在 `data`，写入 `jjc_match_detail`。
- 写入 payload 应与页面接口一致：
  - `match_id`
  - `detail`
- 写入必须走 `JjcInspectRepo.save_match_detail()`，保留装备/奇穴快照拆分。
- 如果响应为 `code=-1,msg=no data found,data=null`，可按现有页面逻辑写入 `unavailable=true` 终态缓存，避免页面重复请求不可用对局。
- 如果推栏返回其他错误，不写详情缓存。

### `match/history`

- 本次优先不把定时统计的 `match/history` 写入 `jjc_role_recent`，原因是定时统计只取 40 条用于心法判定，而页面近期战绩有自己的分页、过滤、缓存结构。
- 定时统计已写入的 `global_role_id` 可帮助页面减少身份解析请求；页面首次查看近期战绩仍按现有逻辑请求并写 `jjc_role_recent`。
- 如果后续要写 `jjc_role_recent`，需要单独确认页面分页语义、`cursor` 和 `max_recent_matches` 是否与定时统计的 `size=40` 兼容。

## 前端交互

- 角色弹窗 indicator 区域增加一个刷新按钮。
- 默认打开弹窗仍使用 1 天缓存。
- 点击刷新时：
  1. 按钮进入 loading/disabled 状态。
  2. 调用 indicator API，追加 `force_refresh=true`。
  3. 成功后替换 indicator 展示，并更新缓存状态。
  4. 失败时显示错误，不清空当前已展示数据。
- 刷新按钮只刷新 `role_indicator`，不自动刷新最近战绩列表和对局详情。

## API 设计

现有角色 indicator 接口增加查询参数：

```text
force_refresh=false
```

默认行为：

- `false`：读取 1 天内 `jjc_role_indicator` 缓存；未命中才请求推栏。
- `true`：跳过 `jjc_role_indicator` 缓存，实时请求推栏，成功后覆盖 Mongo 缓存。

响应结构不新增强依赖字段，继续返回现有 `cache.hit`、`cache.cached_at`、`cache.ttl_seconds`。`ttl_seconds` 调整为 `86400`。

## 实施步骤

1. 提取页面缓存写入辅助逻辑：
   - 在 service 层增加定时统计可调用的缓存写入方法，避免 handler 或 `kungfu.py` 直接依赖 Mongo 细节。
   - 复用 `JjcInspectRepo.save_role_indicator()` 与 `save_match_detail()`。
2. 调整 `kungfu.py`：
   - 在 `get_kungfu_detail_by_role_info()` 内保留已请求到的原始 `role_indicator`、`match_history`、`match_detail` 中间结果。
   - 返回给 `JjcRankingService` 时避免污染原有统计字段；可放在内部字段或独立对象中，调用方写缓存后不再写入 `role_jjc_cache`。
3. 调整 `JjcRankingService`：
   - 定时/手动统计查询角色心法后，把可缓存的 indicator/detail 写入页面缓存集合。
   - 写缓存失败只记录 warning，不中断统计。
4. 调整 `JjcRankingInspectService.get_role_indicator()`：
   - TTL 改为 86400 秒。
   - 增加 `force_refresh` 参数并在为真时跳过读取缓存。
5. 调整 API 路由：
   - 接收 `force_refresh`。
   - 透传给 service。
   - 保持 Python 3.9 类型注解兼容。
6. 调整前端：
   - 增加刷新按钮、loading、错误态。
   - 刷新后更新 indicator 数据和缓存状态。
7. 同步文档：
   - 更新数据库设计中 `jjc_role_indicator` TTL 和写入来源。
   - 更新 runbook 手工回归步骤。

## 验证

自动化验证：

```bash
python -m unittest tests.test_jjc_ranking_inspect
python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo
python -m py_compile src/services/jx3/kungfu.py src/services/jx3/jjc_ranking.py src/services/jx3/jjc_ranking_inspect.py src/api/routers/jjc_ranking_stats.py
```

建议新增或扩展测试：

- `force_refresh=False` 且缓存未过期时不请求推栏。
- `force_refresh=True` 时跳过缓存并写回新缓存。
- `role_indicator` TTL 返回 `86400`。
- 定时统计写入 `jjc_match_detail` 时调用 snapshot 拆分逻辑。
- 定时统计写缓存失败不影响统计结果返回。

手工验证：

1. 清理某个测试角色的 `jjc_role_indicator` 和最近胜场 `jjc_match_detail`。
2. 触发一次竞技排名统计。
3. 在 Mongo 中确认：
   - `jjc_role_indicator` 写入对应角色。
   - 若定时任务请求了最近胜场详情，`jjc_match_detail` 写入对应 `match_id`。
4. 打开排行榜页面点击该角色：
   - indicator 显示 `cache.hit=true`。
   - 最近对局中已缓存详情的对局展示缓存摘要。
5. 点击对局详情：
   - 若该 `match_id` 已由定时任务写入，详情接口返回 `cache.hit=true`。
6. 点击 indicator 刷新按钮：
   - 请求带 `force_refresh=true`。
   - 成功后 `cached_at` 更新，页面展示最新数据。

## 风险

- 定时统计本身已经串行且请求量大，新增 Mongo 写入会增加少量存储压力。
- `match/detail` 原始数据较大，必须走 snapshot 拆表，不能直接绕过 repo 写入。
- `role_indicator` TTL 延长到 1 天后，默认页面数据新鲜度下降，需要依赖主动刷新按钮满足实时查看需求。
- 若定时统计中间结果字段处理不当，可能把大对象写入 `role_jjc_cache`，需要测试覆盖字段隔离。

## 回滚

- 将 `role_indicator` TTL 恢复为 600 秒。
- 移除 API `force_refresh` 参数使用，前端隐藏刷新按钮。
- 停止定时统计写入 `jjc_role_indicator` 和 `jjc_match_detail`，保留原有 `role_jjc_cache` 行为。
- Mongo 中已经写入的 `jjc_role_indicator` / `jjc_match_detail` 可自然被业务 TTL 或后续清理脚本处理，不影响页面正确性。
