# JJC 排名查询预热角色近期对局缓存计划

## 背景

竞技排名统计在为榜单角色补心法时，会通过 `get_kungfu_detail_by_role_info()` 请求推栏：

- `role/indicator`：获取角色 indicator、`global_role_id`、`role_id` 等身份信息。
- `3c/mine/match/history`：获取最近对局列表，用于最近胜场心法多数投票。

当前排名服务只把 indicator 预热进统计页可读的 `jjc_role_indicator` 缓存，并把心法画像写入 `role_jjc_cache`。`match_history` 的近期对局列表没有写入 `jjc_role_recent`，所以统计页点开角色时仍可能重新请求近期对局。

## 目标

排名查询已经获取到某角色近期对局列表时，同步写入统计页角色近期对局缓存，使 `/api/jjc/ranking-stats/role-recent` 和 `public/jjc-ranking-stats.html` 能直接命中缓存。

## 非目标

- 不改变单局详情 `jjc_match_detail` 的缓存策略。
- 不扩大对局详情预热范围，仍只保留现有最新胜场详情预热逻辑。
- 不改变同步队列、对局详情投影或已同步对局页面读取逻辑。

## 设计

1. 在 `src/services/jx3/kungfu.py` 中保留 `match_history` 成功响应中已经过滤为 `dict` 的 `matches` 列表到 `_cache_warmup.role_recent.raw_matches`。
   - 只在 `match_history` 请求成功且 `data` 为列表时写入。
   - 空列表不写入缓存，避免用“空成功”覆盖页面已有可用缓存。
   - 复用当前最多 40 条的请求结果，避免新增外部请求；`40` 来自 `get_kungfu_detail_by_role_info()` 中现有 `get_match_history(size=40, cursor=0)` 调用，后续若调整请求 size，`request_size` 必须跟随真实请求参数写入。
   - 在 warmup payload 中记录 `request_size: 40`，避免分页判断与请求 size 隐式耦合。
   - `raw_matches` 只包含 `dict` 条目，非字典条目在 `kungfu.py` 已过滤；归一化纯函数仍需防御非字典输入，便于直接单测和未来调用。
   - 不在 `kungfu.py` 中做页面结构转换，避免把统计页近期对局展示规则散落到心法判定函数里。
2. 在 `src/services/jx3/jjc_ranking.py` 的 `_warmup_inspect_cache_from_kungfu_detail()` 中处理新的 `_cache_warmup.role_recent`。
   - 将推栏 match history 条目转换为 `JjcRankingInspectService._build_role_recent_payload()` 当前返回的 `recent_matches` 结构。
   - 转换逻辑不直接调用 `_build_role_recent_payload()`，因为该方法会重新请求 `match_history`。实现时新增一个共享的纯函数（优先放在 `src/services/jx3/jjc_ranking_inspect.py` 模块级或拆到小工具模块），让 live path 和 warmup path 复用同一套字段归一化规则。
   - 归一化规则必须与 live path 保持一致：
     - 只保留 `pvpType/pvp_type/type == 3` 或未明确标识类型的 3v3 兼容数据；明确非 3 的条目过滤掉。
     - `match_id` 兼容 `match_id/matchId/matchID/id`。
     - `match_time/start_time/end_time/duration/avg_grade/total_mmr/mmr_delta/mvp/won` 按 live path 现有 helper 规则提取。
     - `kungfu` 使用 `kungfu_pinyin_to_chinese` 翻译成中文，避免缓存命中和实时查询展示不一致。
     - 按 `match_time` 或 `start_time` 倒序排序。
     - 只截取 `JjcRankingInspectService.max_recent_matches` 当前默认等价的前 20 条，避免缓存命中时比实时查询多返回 40 条。
   - 归一化纯函数签名显式接收 `kungfu_pinyin_to_chinese` 和 `max_recent_matches`，不从 service 实例或模块全局隐式取值。
   - 只写第一页缓存，缓存 key 仍为 `server + name`，集合仍为 `jjc_role_recent`。
   - 缓存 payload 至少包含 `player`、`identity`、`identity_key`、`pagination`、`recent_matches`。
   - 分页规则必须兼容页面实时查询：
     - warmup 仍复用 `get_match_history(size=40, cursor=0)` 的 40 条原始数据，不改变心法多数投票与武器/队友预热逻辑。
     - 推栏 `cursor` 语义按现有 live path 处理为 raw offset：实时路径请求 `size=max_recent_matches,cursor=0` 后，用 `cursor + total_returned` 作为下一页 cursor。
     - 因此 warmup 写入页面第一页缓存时，必须只取 `raw_matches[:max_recent_matches]` 作为第一页 raw 输入，再归一化成 `recent_matches`。不要用 raw 40 条全部参与页面第一页展示，否则无法与 live path 的 raw cursor 对齐。
     - 当前 `max_recent_matches=20`，所以 raw 40 条 warmup 数据写入页面第一页缓存时，第一页只消费 raw offset `0..19`，`next_cursor=20`。
     - `has_more` 使用第一页 raw 是否满页判断：`len(raw_matches) >= max_recent_matches`。
     - `next_cursor` 使用第一页已消费的 raw offset：`max_recent_matches`。不要使用 `len(raw_matches)`，否则会从 cursor 40 开始跳过 20-39；也不要使用 `len(recent_matches)`，否则当 raw 前 20 条被过滤后会重复读取已经消费的 raw 区间，极端情况下可能返回 `0` 导致前端重新请求第一页。
     - 若 `has_more=False`，`next_cursor=None`。
     - 当前 cache-hit 主要消费 `recent_matches`，但保留完整字段便于后续复用。
   - `identity` 结构由 warmup path 明确构造，至少包含：`server`、`name`、`game_role_id`、`role_id`、`zone`、`global_role_id`、`global_id`、`source: "ranking_warmup"`、`identity_hints`。`identity_hints` 保存上述非空 ID 字段。
   - `identity_key` 优先使用 `global_id:<global_id>`，其次 `global:<global_role_id>`；两者都缺失时使用 `None` 并保留 `identity`，不构造临时字符串 key。
   - 调用 `save_role_recent()` 时使用 live path 一致的包装形式：`{"cached_at": cached_at, "data": payload}`，不依赖 repo 对未包装 payload 的 fallback。
3. 更新 `public/jjc-ranking-stats.html` 的空列表展示与加载更多兼容逻辑。
   - 当 `recent_matches` 为空但 `pagination.has_more=True` 时，不应渲染“暂无最近 3v3 对局数据”作为持久占位，避免后续 append 真正对局后同时显示“暂无”和对局列表。
   - 可改为渲染轻量加载提示，或在 append 模式插入新对局前删除 `.modal-empty`。
   - append 模式必须保证列表从空展示状态加载到真实对局时，面板中只保留真实对局和加载更多按钮。
4. 不新增集合、不改索引；`jjc_role_recent` 已存在并由 `JjcInspectRepo.save_role_recent()` 维护。

## 涉及文件

- `src/services/jx3/kungfu.py`
- `src/services/jx3/jjc_ranking.py`
- `src/services/jx3/jjc_ranking_inspect.py`
- `public/jjc-ranking-stats.html`
- `tests/test_jjc_ranking_history_win_kungfu.py` 或新增/补充相关单测

## 验证

1. 单测覆盖：
   - `get_kungfu_detail_by_role_info()`：mock `role/indicator` + `match_history` 成功时，`_cache_warmup.role_recent.raw_matches` 包含成功返回且已过滤为 dict 的列表，并包含 `request_size`；空列表不生成 role recent warmup。
   - 近期对局归一化纯函数：覆盖 3v3 过滤、非 3 过滤、字段别名、心法中文翻译、倒序排序、截断到 20、缺少 `kungfu/won/grade` 时优雅降级。
   - `_warmup_inspect_cache_from_kungfu_detail()`：补全 `FakeWarmupInspectRepo.save_role_recent()`，验证 role recent 写入 `save_role_recent()`，且 payload 结构与 live path 兼容。
   - `identity_key` 缺失场景：`global_id/global_role_id` 都没有时 payload 中 `identity_key is None`，仍可保存 `recent_matches`。
   - 分页兼容场景：当 `raw_matches=40` 且 `max_recent_matches=20` 时，缓存第一页只使用 `raw_matches[:20]`，payload 应为 `has_more=True` 且 `next_cursor=20`，后续“加载更多”从 cursor 20 继续，而不是 cursor 40。
   - 过滤场景：当 raw 前 20 条包含非 3v3 或非法类型导致 `recent_matches` 少于 20 条时，`next_cursor` 仍应为 20，确保 cursor 表示已消费 raw offset，而不是展示条数。
   - 空展示场景：当 raw 前 20 条全部被过滤但 raw 数量达到 20 时，`has_more=True` 且 `next_cursor=20`，不得返回 `next_cursor=0`。
   - 前端空展示加载更多场景：`recent_matches=[]` 且 `has_more=True` 时，首屏不应留下会与后续真实对局共存的“暂无最近 3v3 对局数据”占位；点击加载更多并 append 数据后，列表中只能出现真实对局与加载更多按钮。
   - 流水线测试：`kungfu.py` 产出 `_cache_warmup.role_recent` 后，`jjc_ranking.py` 消费并写入 `jjc_role_recent`。
2. 语法检查：
   - `python -m py_compile src/services/jx3/kungfu.py src/services/jx3/jjc_ranking.py src/services/jx3/jjc_ranking_inspect.py`
3. 手工回归：
   - 运行一次竞技排名统计。
   - 打开统计页，点开已参与排名预热的榜单角色，确认近期对局正常展示。
   - 通过服务端日志或浏览器网络面板确认 `/ranking-stats/role-recent` 返回缓存命中，不再为第一页额外请求实时近期对局。
   - 点击“刷新对局”仍可绕过缓存并更新 `jjc_role_recent`。

## 风险与回滚

- 风险：推栏 match history 字段变体导致部分字段为空。缓解：转换逻辑抽成与 live path 共用的纯函数，并覆盖字段别名单测。
- 风险：排名统计请求较多时写入 `jjc_role_recent` 次数增加。缓解：只复用已经拿到的数据，不增加外部请求；写入失败只记录 warning，不影响排名结果。
- 风险：近期列表缓存按 `server + name` 保存，角色改名或转服场景可能与旧缓存混淆。缓解：沿用现有 `jjc_role_recent` key 策略，不引入新行为；TTL 仍由 `role_recent_ttl_seconds` 控制。
- 风险：排名统计循环中新增 Mongo 写入量。缓解：写入发生在已有 warmup 阶段，失败降级为 warning；需确认排名统计当前按角色顺序 await warmup，避免额外并发放大。
- 回滚：移除 `_cache_warmup.role_recent` 生成和 `_warmup_inspect_cache_from_kungfu_detail()` 中对应保存逻辑即可。

## 状态

- 2026-05-29：原始 warmup 方案已实现/已验证。
- 2026-05-29：补充分页方案调整：warmup 仍请求 40 条，但页面缓存第一页只消费 raw 前 20 条，`next_cursor` 按已消费 raw offset 返回 20，避免加载更多跳过或重复中间对局。
- 2026-05-29：补充分页与前端空展示方案已更新；相关代码与测试待实现/待验证。整体计划状态：待实现补充项。
- 2026-05-29：补充分页方案已实现：jjc_ranking.py 只消费 raw_matches[:max_recent] 作为第一页，has_more 基于 raw 长度 >= max_recent，next_cursor 使用 max_recent。前端 empty placeholder 在 has_more=true 时不渲染，append 前移除 .modal-empty。新增分页单测（40条raw、过滤全空场景）已覆盖。
- 2026-06-02：用户确认验证 OK，计划归档到 completed，整体计划状态：已实现/已验证/待提交。
