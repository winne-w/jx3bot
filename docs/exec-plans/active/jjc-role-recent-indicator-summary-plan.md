# JJC 角色 indicator 指标接口与缓存计划

状态：修复中
更新时间：2026-05-12

## 背景

竞技场排行榜统计页点击用户后，会打开最近 3v3 对局列表。弹窗顶部当前展示的场次、胜率、评分、最佳、当前段位等指标，现状主要来自 `/api/jjc/ranking-stats/role-recent` 的 `summary` 字段，而该字段由 `3c/mine/match/history` 返回的最近对战窗口计算或最近一局字段推导，因此它表达的是“最近窗口摘要”，不是推栏角色画像中的赛季指标。

用户要求这组顶部指标改为从推栏 `role/indicator` 接口请求并缓存；`role-recent` 可以删除 `summary` 字段，新增独立后端接口承载 indicator 指标。

## 目标

- 排行榜页面点击用户查看最近对战列表时，弹窗顶部指标改为请求新增的 JX3Bot `role/indicator` 接口，并使用推栏 `role/indicator` 的 3v3 指标。
- 指标字段覆盖：场次、胜率、评分、最佳、当前段位。
- 后端缓存 indicator 指标 600 秒，避免同一角色短时间重复请求 `role/indicator`。
- `/api/jjc/ranking-stats/role-recent` 删除 `summary` 字段，只返回角色、身份、分页和最近对局列表。
- 最近对局列表仍由 `3c/mine/match/history` 提供，分页和对局详情点击行为保持不变。

## 非目标

- 不改变排行榜 summary/details 快照结构。
- 不改动对局详情缓存、装备/奇穴快照拆分逻辑。
- 不新增主动预热对局详情。
- 不用最近对战列表重新计算顶部指标作为兜底。
- 不把 indicator 原始响应塞进 `role-recent`，避免列表接口承担两个外部数据源的展示职责。

## 失败策略

- `role/indicator` 请求失败、返回非 dict、缺少 3v3 指标、或关键字段无法解析时，不回退到 `match/history` 统计。
- 首次加载需要 indicator 指标而失败时，新增的 JX3Bot indicator 接口返回错误，例如 `indicator_unavailable`，前端展示指标加载失败，不展示由最近对局推导出的替代数据。
- 已有未过期 indicator 指标缓存时，允许直接使用缓存；没有缓存则失败即失败。
- 最近对局接口请求成功但 indicator 失败时，最近对局列表仍可展示；顶部指标区域单独展示失败状态，避免列表接口被指标失败阻断。
- 缓存过期后如实时请求失败，不使用已过期缓存作为兜底，避免展示明显滞后的指标。

## 涉及文件

- `src/services/jx3/jjc_ranking_inspect.py`
  - 增加 `indicator` 指标查询、缓存命中和响应规整逻辑。
  - 在角色身份解析得到 `game_role_id + zone + server` 后，请求或读取缓存的 indicator 指标。
  - 新增 `role_indicator_ttl_seconds = 600` 配置，过期判断由 service/repo 业务逻辑完成。
  - `_build_role_recent_payload()` 删除 `summary` 输出；最近列表只负责 `recent_matches` 与分页。
  - 保留对 `match/history` 的请求，用于列表内容。
- `src/storage/mongo_repos/jjc_inspect_repo.py`
  - 新增 indicator 缓存读写方法，按角色身份优先使用 `identity_key` 或 `global_role_id` 作为缓存键。
  - 缓存内容保存推栏 `role/indicator` 原始响应、规整后的 3v3 指标、`cached_at`。
  - 读取时按 `ttl_seconds=600` 判断有效期；Mongo TTL 索引不作为本次过期语义来源。
- `src/api/routers/jjc_ranking_stats.py`
  - 保持 `/ranking-stats/role-recent` 路由签名不变，但响应删除 `summary`。
  - 新增 `GET /api/jjc/ranking-stats/role-indicator`，参数复用角色下钻所需的 `server/name/game_role_id/global_role_id/role_id/zone`，返回缓存或实时请求到的 indicator 数据。
- `public/jjc-ranking-stats.html`
  - 打开角色弹窗时并行或串行请求 `role-recent` 与 `role-indicator`。
  - 顶部卡片改为读取 `role-indicator` 返回的指标字段。
  - 字段标签调整为：场次、胜率、评分、最佳、当前段位。
  - 当 indicator 接口返回失败错误时，只在顶部指标区域展示失败状态，不影响最近对局列表渲染。
- `tests/test_jjc_ranking_inspect.py`
  - 增加 role-recent 不再返回 summary、indicator 缓存命中、缓存未命中实时请求、indicator 失败不回退、实时结果写缓存等 service 单测。
- `docs/design-docs/database-design.md`
  - 新增 Mongo 集合 `jjc_role_indicator` 的结构和索引说明。

## 数据结构

`/api/jjc/ranking-stats/role-recent` 成功响应删除 `summary` 字段。保留结构示例：

```json
{
  "player": {"server": "梦江南", "name": "角色名"},
  "identity": {},
  "identity_key": "global:xxx",
  "pagination": {},
  "recent_matches": []
}
```

新增 `GET /api/jjc/ranking-stats/role-indicator` 成功响应：

```json
{
  "player": {"server": "梦江南", "name": "角色名"},
  "identity": {},
  "indicator": {
    "source": "indicator",
    "type": "3c",
    "total_matches": 123,
    "win_rate": 56.1,
    "score": 2400,
    "best_score": 2600,
    "grade": 12
  },
  "raw": {},
  "cache": {"hit": true, "cached_at": 1778000000.0, "ttl_seconds": 600}
}
```

字段映射以 `role/indicator` 实际返回为准，实施时需要在代码中集中封装解析函数：

- `total_matches`: 3v3 指标中的总场次。
- `win_rate`: 3v3 指标中的胜率；如接口只返回胜场/总场次，则由 indicator 数据本身计算。
- `score`: 当前评分。
- `best_score`: 最佳评分。
- `grade`: 当前段位。
- `source`: 固定为 `indicator`，便于前端和日志确认口径。

indicator 缓存落 MongoDB，不落文件。原因：

- 仓库约束要求运行时缓存统一走 `src/storage/`，当前优先使用 MongoDB repo，不新增裸 JSON 文件缓存。
- 角色身份已在 Mongo 的 `role_identities` / `role_jjc_cache` 中维护，indicator 缓存按同一身份键关联更容易处理转服、改名和同名角色。
- 多实例部署时 Mongo 缓存可共享，文件缓存无法稳定共享。

新增集合：`jjc_role_indicator`。

缓存策略：

- TTL：600 秒。
- 写入：实时请求推栏 `role/indicator` 成功并解析出有效 3v3 指标后写入。
- 读取：同一 `cache_key` 命中且 `time.time() - cached_at <= 600` 时直接返回。
- 过期：过期缓存不作为失败兜底；缓存过期后实时请求失败则接口返回失败。
- TTL 实现：业务逻辑判断，不依赖 MongoDB TTL 索引。`cached_at` 可建普通索引用于排查或后续清理。

```json
{
  "cache_key": "global:<global_role_id>",
  "identity_key": "global:<global_role_id>",
  "server": "梦江南",
  "name": "角色名",
  "game_role_id": "...",
  "global_role_id": "...",
  "zone": "...",
  "indicator": {},
  "raw": {},
  "cached_at": 1778000000.0
}
```

索引计划：

- `cache_key` unique。
- `cached_at` 普通索引；过期仍由 repo 业务 TTL 判断，避免 float TTL 误判。

## 实施步骤

1. 在 `JjcInspectRepo` 增加 `jjc_role_indicator` 缓存读写方法，并补充数据库文档。
2. 在 `JjcRankingInspectService` 增加 indicator 3v3 指标解析函数，字段缺失时返回结构化错误。
3. 新增 service 方法 `get_role_indicator()`：解析身份、按 600 秒 TTL 读 Mongo 缓存、缓存 miss 或过期时请求推栏 `role/indicator`、规整字段、写缓存。
4. 调整 `_build_role_recent_payload()` 删除 `summary`，只返回 recent match 列表与分页。
5. 在 API router 新增 `GET /api/jjc/ranking-stats/role-indicator`。
6. 修改前端顶部卡片为调用新接口，展示场次、胜率、评分、最佳、当前段位，并处理 indicator 错误态。
7. 增加单测覆盖缓存命中、缓存写入、indicator 失败不回退、`role-recent` 不再返回 `summary`。
8. 执行自动化验证和手工回归。

## 2026-05-12 排查补充

线上反馈：

- 排行榜页面点击角色查看近期对局时，未观察到 `role-indicator` 请求。
- 直接调用 `/api/jjc/ranking-stats/role-indicator` 时，每次都会请求推栏，没有命中后端缓存。

本地复现结论：

- `role-indicator` 已发起实时请求，但欧闲闲样本的推栏返回字段位于 `indicator[type=3c].metrics[]` 与 `indicator[type=3c].performance` 内。
- 当前 `_parse_3v3_indicator` 只读取 `indicator[type=3c]` 顶层字段，解析结果为 `indicator_3c_empty_fields`。
- 解析失败时不会写入 `jjc_role_indicator`，因此后续调用仍会继续请求推栏，表现为“没有缓存”。

修复项：

1. 扩展 3v3 indicator 解析逻辑，支持真实推栏结构：
   - `performance.total_count/win_count/mmr/grade`
   - `metrics[]` 中 `pvp_type=3` 的 `total_count/win_count/level`
2. 增加 `get_role_indicator` 缓存命中、实时写缓存、失败不写缓存的单测。
3. 调整前端弹窗加载流程：打开角色弹窗后立即触发 indicator 请求，避免近期列表失败或页面缓存路径导致 indicator 不发起。

### 统一解析方案设计

问题复盘：

- 排名统计链路已经在 `src/services/jx3/kungfu.py` 中处理过推栏 `role/indicator` 的 `3c` / `3d` 差异。
- 本计划实现 `role-indicator` API 时没有先盘点既有 indicator 解析逻辑，导致在 `src/services/jx3/jjc_ranking_inspect.py` 中重复写了一套只认 `3c` 的解析。
- 结果是遇到 `type=3d`、但 `metrics[].pvp_type=3` 的真实返回时，后端误判为 `indicator_3c_missing`，前端无法展示数值，且失败结果不写缓存，造成每次都请求推栏。

设计目标：

- 推栏 `role/indicator` 的 3v3 定位规则只维护一份。
- 排名统计心法判断与角色弹窗 indicator 指标展示共用同一个 3v3 indicator 选择入口。
- 业务模块只表达各自字段映射和展示/缓存策略，不重复判断 `3c`、`3d`、`metrics[].pvp_type`。

方案：

1. 新增 `src/services/jx3/indicator_utils.py` 作为推栏 indicator 纯解析工具模块。
2. 在该模块中提供：
   - `find_3v3_indicator(indicators)`：统一识别 `type in {"3c", "3d"}`，并兼容 `metrics[].pvp_type == 3`。
   - `find_3v3_metrics(indicator)`：统一筛出 3v3 metrics，缺少 `pvp_type` 时按历史兼容策略保留。
   - `select_best_3v3_metric(indicator, require_items=False)`：保留排名统计“按胜场优先、场次次之”选择心法 metric 的规则。
3. `src/services/jx3/kungfu.py` 改为调用共享 helper，不再本地维护 `3c` / `3d` 判断。
4. `src/services/jx3/jjc_ranking_inspect.py` 的 `_parse_3v3_indicator` 改为调用共享 helper，再在本模块内完成指标字段映射：
   - 场次/胜场优先读取 `performance`，再读取 3v3 metric。
   - 评分、段位读取 `performance.mmr` / `performance.grade`。
   - 胜率由 `win_count / total_count` 计算。
5. 测试补齐：
   - `3c + metrics/performance` 样本。
   - `3d + metrics[].pvp_type=3` 样本。
   - 缓存命中后不再调用推栏。
   - 解析失败不写缓存。
   - 共享 helper 的 `3c` / `3d` / `pvp_type=3` 识别规则。

后续约束：

- 新增或修改任何推栏 `role/indicator` 3v3 解析逻辑时，必须优先复用 `src/services/jx3/indicator_utils.py`。
- 不允许在 service、router、前端或脚本中重新散写 `type == "3c"` / `type == "3d"` / `pvp_type == 3` 的组合判断；确有新字段形态时先扩展共享 helper 和测试。

## 验证

自动化：

```bash
python -m unittest tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py src/api/routers/jjc_ranking_stats.py
```

前端语法检查：

```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('public/jjc-ranking-stats.html','utf8'); const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]); scripts.forEach((s,i)=>new Function(s)); console.log('scripts ok', scripts.length)"
```

手工：

- 打开 `public/jjc-ranking-stats.html`。
- 点击一个有完整身份字段的榜单角色，确认弹窗顶部展示场次、胜率、评分、最佳、当前段位。
- 重复点击同一角色，确认后端命中 indicator 摘要缓存，不重复请求外部接口。
- 将缓存 `cached_at` 改成超过 600 秒前，确认下一次请求会重新请求推栏并刷新缓存。
- 模拟 indicator 失败或返回缺字段，确认 indicator 接口失败且前端顶部指标区域不展示最近对战推导的旧摘要。
- 确认 `/api/jjc/ranking-stats/role-recent` 响应不再包含 `summary` 字段。
- 点击加载更多，确认分页只追加对局列表，不改变顶部 indicator 指标。

## 风险与回滚

- 风险：`role/indicator` 字段名与预期不一致。实施时先记录受控样本字段，解析函数只认明确字段，缺失即失败。
- 风险：不回退会让部分角色顶部指标无法展示。该行为符合本次要求，前端需要给出清晰失败态，最近对局列表仍可展示。
- 风险：新增 Mongo 集合需要同步数据库文档和部署环境索引。
- 回滚：删除新增 `role-indicator` API、`jjc_role_indicator` 缓存读写和前端指标请求，恢复最近对战窗口统计口径。
