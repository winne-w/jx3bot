# JJC 排名历史列表按赛季周次筛选计划

状态：已完成并归档
更新时间：2026-05-23

## 执行状态

- 2026-05-22：已完成后端 `with_meta` 列表模式、路由参数、repo/router 单测。
- 2026-05-22：已完成前端历史选择器，支持赛季、周次、全部/结算/日常快照和具体快照切换，并保留旧 timestamp 数组 fallback。
- 2026-05-22：已同步 README API 示例和 runbook HTTP API/页面手工回归说明。

## 背景

`public/jjc-ranking-stats.html` 当前在页面顶部只展示“可用日期”下拉框。下拉数据来自：

```text
GET /api/jjc/ranking-stats?action=list
```

现有接口未分页时只返回 `timestamp` 数组，前端再把时间戳格式化成日期时间。随着历史快照变多，用户需要在很多时间点里判断“这是哪个赛季、第几周、是不是结算榜”，使用成本较高。

Mongo 迁移后，`jjc_ranking_stat_summaries` 已经保存列表所需的关键元数据：

- `current_season`
- `default_week`
- `week_info`
- `ranking_cache_time`
- `generated_at`

因此本次优先利用现有 summary 字段增强历史列表，不新增集合、不重算历史快照。

## 目标

- 历史快照选择不再只显示时间，改为按赛季、周次、结算状态组织。
- 用户可以快速筛选：
  - 赛季
  - 第几周
  - 全部 / 结算 / 日常快照
  - 具体快照时间
- 保持现有详情读取链路不变，选择快照后仍通过 `timestamp` 调用 `action=read` 和 `/details`。
- 保持旧版 `action=list` timestamp 数组返回兼容，避免影响外部调用或旧调试参数。

## 非目标

- 不改变 JJC 排名统计口径。
- 不调整 `calculate_season_week_info()` 的周次计算规则。
- 不新增 Mongo 集合。
- 不对历史快照做批量回填或重算。
- 不恢复 URL `timestamp` 直达历史快照能力；页面仍按此前计划默认加载最新快照，用户通过页面控件切换历史数据。

## 现状入口与数据流

当前页面加载流程：

1. `loadDateList()` 请求 `listApiUrl`，默认是 `/jx3bot/api/jjc/ranking-stats?action=list`。
2. `renderDateList(timestamps)` 对 timestamp 数组倒序排序。
3. 页面选择最新 timestamp。
4. `loadStats(timestamp)` 请求 `action=read&timestamp=<timestamp>`。
5. 心法明细展开时用 `currentStatsTimestamp` 请求 `/ranking-stats/details`。

本次调整后：

1. `loadDateList()` 优先请求带元数据的列表。
2. 前端基于元数据构建赛季、周次、类型、快照四个选择控件。
3. 用户切换任意筛选项时，页面在内存中重算可选快照。
4. 最终仍调用 `loadStats(selectedTimestamp)` 读取统计摘要。

## API 设计

### 列表接口兼容

保留旧接口行为：

```text
GET /api/jjc/ranking-stats?action=list
```

未传分页参数和新参数时，继续返回旧格式：

```json
[1777426656, 1777340250]
```

新增元数据模式：

```text
GET /api/jjc/ranking-stats?action=list&page=1&page_size=100&with_meta=1
```

返回：

```json
{
  "items": [
    {
      "timestamp": 1777426656,
      "generated_at": 1777426660.123,
      "ranking_cache_time": 1777426656.848,
      "default_week": 5,
      "current_season": "暗影千机",
      "week_info": "第5周 结算",
      "is_settlement": true,
      "snapshot_kind": "settlement",
      "snapshot_label": "暗影千机 · 第5周 · 结算 · 2026/05/18 08:00"
    }
  ],
  "page": 1,
  "page_size": 100,
  "total": 20,
  "has_more": false
}
```

说明：

- `with_meta=1` 只影响列表项形态，不影响 `action=read` 和 `/details`。
- `is_settlement` 第一版从 `week_info` 是否包含 `结算` 派生。
- `snapshot_kind` 固定为：
  - `settlement`
  - `daily`
- `snapshot_label` 可由后端生成，也可前端生成。为降低后端中文展示耦合，优先只返回结构化字段，前端生成展示文案；如测试更易维护，可保留后端 helper 生成但不作为唯一事实来源。

### 查询参数

`src/api/routers/jjc_ranking_stats.py` 增加：

```python
with_meta: bool = Query(False, description="list 模式是否返回快照元数据")
```

路由调用 repo：

```python
repo.list_timestamps(page=..., page_size=..., with_meta=with_meta)
```

兼容策略：

- `with_meta=false` 且未分页：返回 `List[int]`。
- `with_meta=false` 且分页：返回现有分页对象，`items` 仍是 `List[int]`。
- `with_meta=true`：返回分页对象，`items` 是快照元数据对象列表。即使未传分页参数，也按 `page=1&page_size=100` 的方式返回，避免一次性拉过多历史数据。

## 存储与查询设计

修改 `src/storage/mongo_repos/jjc_ranking_stats_repo.py`：

- `list_timestamps()` 增加 `with_meta: bool = False` 参数。
- Mongo projection 在元数据模式下包含：
  - `timestamp`
  - `generated_at`
  - `ranking_cache_time`
  - `default_week`
  - `current_season`
  - `week_info`
- 排序继续按 `timestamp desc`。
- 通过 helper 将 Mongo 文档规范化为列表 item。

建议 helper：

```python
def _build_history_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    week_info = str(doc.get("week_info") or "")
    is_settlement = "结算" in week_info
    return {
        "timestamp": doc["timestamp"],
        "generated_at": doc.get("generated_at"),
        "ranking_cache_time": doc.get("ranking_cache_time"),
        "default_week": doc.get("default_week"),
        "current_season": doc.get("current_season"),
        "week_info": week_info,
        "is_settlement": is_settlement,
        "snapshot_kind": "settlement" if is_settlement else "daily",
    }
```

索引：

- 复用现有 `idx_timestamp` 和 `idx_current_season_default_week`。
- 本次不新增索引，因为第一版仍按 `timestamp desc` 分页并在前端做筛选。
- 如果后续历史量明显增大，再评估后端增加 `season/week/kind` 过滤参数与对应复合索引。

数据库文档：

- 不新增字段，不需要更新 `docs/design-docs/database-design.md` 的字段表。
- 如实现时新增了持久化字段，例如 `is_settlement`，必须同步更新数据库设计文档和索引说明。

## 前端交互设计

替换当前单一“可用日期”选择区。

建议控件：

```text
赛季：[暗影千机 v]
周次：[第5周 v]
类型：[全部 / 结算 / 日常快照]
快照：[结算 · 2026/05/18 08:00 v]
```

快照展示文案：

```text
暗影千机 · 第5周 · 结算 · 2026/05/18 08:00
暗影千机 · 第5周 · 周五 08:00 · 2026/05/22 08:00
暗影千机 · 第4周 · 结算 · 2026/05/11 08:00
```

控件行为：

- 页面初始化选择最新快照。
- 赛季下拉默认选中最新快照的赛季。
- 周次下拉默认选中最新快照的周次。
- 类型默认 `全部`。
- 切换赛季时，周次选项重建，并选中该赛季最新周。
- 切换周次或类型时，快照选项重建，并选中当前过滤条件下最新快照。
- 切换最终快照时调用 `loadStats(timestamp)`。
- 无可用快照时显示“暂无匹配快照”，不发起 read 请求。

排序规则：

1. 赛季按最新快照时间倒序。
2. 周次按 `default_week` 数字倒序；缺失周次放最后。
3. 同一周内结算快照优先。
4. 同类型内按 `timestamp` 倒序。

兼容缺失字段：

- `current_season` 为空：展示为“未知赛季”。
- `default_week` 为空：展示为“未知周次”。
- `week_info` 为空：类型按 `daily` 处理，快照文案只展示时间。
- 后端仍返回 timestamp 数组时，前端回退到旧下拉逻辑，避免部署前后 API/静态资源版本短暂不一致导致页面不可用。

## 涉及文件

- `src/storage/mongo_repos/jjc_ranking_stats_repo.py`
  - 增加元数据列表模式和 item 规范化 helper。
- `src/api/routers/jjc_ranking_stats.py`
  - 增加 `with_meta` query 参数。
  - 元数据模式下调用 repo 并返回分页对象。
- `public/jjc-ranking-stats.html`
  - 替换历史日期选择 UI。
  - 新增历史快照元数据状态、分组、过滤和 fallback 逻辑。
  - `loadStats()`、详情懒加载继续使用 `currentStatsTimestamp`。
- `tests/test_jjc_ranking_stats_repo.py`
  - 增加 `with_meta` 列表返回结构测试。
  - 覆盖结算和日常快照派生。
  - 覆盖字段缺失兼容。
- `tests/test_jjc_ranking_stats_router.py`
  - 增加 `with_meta=True` 路由参数透传和响应测试。
- `README.md`
  - 如果正式暴露 `with_meta` 参数，补充 API 示例。
- `docs/references/runbook.md`
  - 补充手工回归清单：赛季、周次、类型、快照筛选。

## 实施步骤

### 1. 后端列表元数据

- 在 repo 增加 `with_meta` 参数。
- 元数据模式下查询 summary 元字段。
- 构造结构化 item。
- 保持旧 timestamp 数组和现有分页对象兼容。

验证：

```bash
python -m unittest tests.test_jjc_ranking_stats_repo
python -m py_compile src/storage/mongo_repos/jjc_ranking_stats_repo.py
```

### 2. API 参数透出

- 在 `get_ranking_stats()` 增加 `with_meta` 参数。
- `action=list` 时把参数传入 repo。
- `with_meta=true` 默认使用分页对象返回，避免无分页元数据模式一次性返回过大列表。

验证：

```bash
python -m unittest tests.test_jjc_ranking_stats_router
python -m py_compile src/api/routers/jjc_ranking_stats.py
```

### 3. 前端历史选择器

- `listApiUrl` 默认改为带 `page/page_size/with_meta` 的列表接口。
- 将 `renderDateList()` 拆为：
  - `normalizeHistoryItems(data)`
  - `buildHistoryGroups(items)`
  - `renderHistoryControls(items)`
  - `selectHistorySnapshot(timestamp)`
- 新增赛季、周次、类型、快照四个控件。
- 对旧 timestamp 数组保留 fallback。

验证：

```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('public/jjc-ranking-stats.html','utf8'); const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]); scripts.forEach((s)=>new Function(s)); console.log('scripts ok', scripts.length)"
```

### 4. 文档与回归

- README 补充 `with_meta` 列表示例。
- runbook 补充页面筛选回归步骤。

验证：

```bash
git diff --check -- src/storage/mongo_repos/jjc_ranking_stats_repo.py src/api/routers/jjc_ranking_stats.py public/jjc-ranking-stats.html README.md docs/references/runbook.md docs/exec-plans/active/jjc-ranking-history-selector-plan.md
```

## 自动化测试用例

repo 测试：

- `with_meta=False` 未分页仍返回 `[timestamp]`。
- `with_meta=False` 分页仍返回 `items: [timestamp]`。
- `with_meta=True` 返回 `items: [{timestamp, current_season, default_week, week_info, is_settlement, snapshot_kind}]`。
- `week_info` 包含 `结算` 时 `is_settlement=True`。
- `week_info` 为空或不含 `结算` 时 `is_settlement=False`。
- 字段缺失时不抛异常。

router 测试：

- `with_meta=True` 调用 repo 时带上 `with_meta=True`。
- 未传 `with_meta` 时旧测试保持不变。
- repo 返回空分页时仍成功返回空列表结构。

前端静态检查：

- 内嵌脚本可通过 `new Function` 语法检查。
- 搜索确认不引入 URL `timestamp` 写入逻辑。

## 手工回归

需要在可访问 Mongo 和 API 的本地或测试环境执行：

- 打开 `public/jjc-ranking-stats.html`，确认默认加载最新快照。
- 确认顶部历史选择器展示赛季、周次、类型、快照。
- 切换赛季后，周次和快照选项随之更新。
- 切换周次后，快照列表只展示对应周次。
- 类型选“结算”时，只展示 `week_info` 包含“结算”的快照。
- 类型选“日常快照”时，不展示结算快照。
- 选择某个历史快照后，页面统计内容和顶部“赛季/榜单时间”同步变化。
- 展开心法明细，确认详情接口使用当前快照 timestamp。
- 通过 `list_api` 调试参数返回旧 timestamp 数组时，页面仍可回退为日期选择并正常加载。

## 风险

- 风险：历史数据中 `week_info` 口径不一致，导致结算识别不准确。
  - 缓解：第一版以“包含结算”作为保守判断；无法识别的归为日常快照。
- 风险：前端控件变多，移动端布局拥挤。
  - 缓解：控件使用 flex wrap，单个 select 设置最小宽度和最大宽度。
- 风险：默认拉取 `page_size=100` 仍无法覆盖全部历史。
  - 缓解：第一版满足近期快照查看；如历史超过 100 条，再增加“加载更多”或后端过滤参数。
- 风险：静态页面和 API 部署版本不一致。
  - 缓解：前端保留 timestamp 数组 fallback。

## 回滚方案

- 后端回滚：
  - 移除 `with_meta` 参数和 repo 元数据模式。
  - 旧 `action=list` 返回不变，外部兼容风险低。
- 前端回滚：
  - 恢复单一 `date-select` 和旧 `renderDateList(timestamps)`。
  - `loadStats()`、`details` 读取链路不变，回滚范围集中在历史选择 UI。
- 文档回滚：
  - 移除 README 中 `with_meta` 示例。
  - 移除 runbook 中新增筛选回归步骤。

## 待确认点

- 第一版是否只展示最近 100 条历史快照，还是需要立即支持后端分页“加载更多”。
- “结算”是否只按 `week_info` 包含 `结算` 判断；如果存在其他结算标记来源，需要在实现前补充。
- UI 文案是否采用“日常快照”，还是更偏业务语境的“非结算”。
