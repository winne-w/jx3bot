# JJC 排名统计快照迁移 MongoDB 计划

更新时间：2026-04-30

## 背景

当前 JJC 排名统计快照仍写入文件：

- `data/jjc_ranking_stats/<timestamp>/summary.json`
- `data/jjc_ranking_stats/<timestamp>/details/<range>/<lane>/<kungfu>.json`
- 兼容旧结构：`data/jjc_ranking_stats/<timestamp>.json`

这套结构解决了单个大 JSON 首屏过重的问题，但历史数据列表仍依赖扫描目录。随着快照数量增长，`/api/jjc/ranking-stats?action=list` 会越来越难以支持稳定分页、排序、过滤和多实例部署。

## 目标

- 将 JJC 排名统计快照迁移到 MongoDB，支持历史列表分页。
- 保留 summary/details 拆分结构，避免把所有明细塞进单个 Mongo 文档。
- API 优先读 Mongo，文件作为迁移期 fallback。
- 新生成统计优先写 Mongo，可短期保留文件双写作为回滚兜底。
- 提供历史文件到 Mongo 的一次性迁移脚本。

## 非目标

- 不调整 JJC 心法统计口径。
- 不重算历史快照中的心法、武器、队友数据。
- 不迁移图片、HTML、前端静态资源。
- 不立即删除 `data/jjc_ranking_stats/` 历史文件。

## 集合设计

### `jjc_ranking_stat_summaries`

存一条统计快照的首屏摘要与列表元数据。

建议字段：

```javascript
{
  "timestamp": 1777426656,
  "generated_at": 1777426660.123,
  "ranking_cache_time": 1777426656.848,
  "default_week": 12,
  "current_season": "xxx",
  "week_info": "第12周",
  "kungfu_statistics": {},
  "created_at": ISODate(),
  "updated_at": ISODate(),
  "source": "ranking_job",
  "schema_version": 1
}
```

建议索引：

- `timestamp` unique
- `generated_at` desc
- `ranking_cache_time` desc
- `(current_season, default_week)`

说明：

- `timestamp` 继续使用现有文件目录名，保持接口参数兼容。
- `kungfu_statistics` 只保存 summary 结构，不保存 `members` 明细。

### `jjc_ranking_stat_details`

存单个范围、分组、心法的成员明细。

建议字段：

```javascript
{
  "timestamp": 1777426656,
  "range": "top_200",
  "lane": "dps",
  "kungfu": "花间游",
  "members": [],
  "created_at": ISODate(),
  "updated_at": ISODate(),
  "schema_version": 1
}
```

建议索引：

- `(timestamp, range, lane, kungfu)` unique
- `timestamp`
- `(timestamp, range, lane)`

说明：

- `members` 仍可能较大，但按心法拆分后单文档体积可控。
- 如果后续某个心法明细接近 Mongo 单文档 16MB 限制，再拆成 member 分页集合；当前不先过度设计。

## 代码改造范围

- `src/storage/mongo_repos/jjc_ranking_stats_repo.py`
  - 新增 summary/detail 的保存、读取、分页列表、迁移 upsert 方法。
- `src/infra/mongo.py`
  - 增加两个新集合索引。
- `src/services/jx3/jjc_ranking.py`
  - `save_ranking_stats()` 新增 Mongo 写入路径。
  - 保留短期文件双写，便于回滚和对照。
- `src/api/routers/jjc_ranking_stats.py`
  - `action=list` 优先读 Mongo 分页。
  - `action=read` 优先读 Mongo summary。
  - `/details` 优先读 Mongo detail。
  - Mongo 未命中时回退读取文件。
- `scripts/migrate_jjc_ranking_stats_to_mongo.py`
  - 扫描现有文件结构并写入 Mongo。
- `docs/design-docs/database-design.md`
  - 补充新集合 schema、索引和迁移说明。
- `README.md`、`docs/references/runbook.md`
  - 如果接口增加分页参数，同步更新调用说明。

## API 兼容方案

### 列表接口

现有接口保持可用：

```text
GET /api/jjc/ranking-stats?action=list
```

兼容返回：仍可返回 timestamp 数组。

新增分页参数：

```text
GET /api/jjc/ranking-stats?action=list&page=1&page_size=20
```

建议分页返回结构：

```json
{
  "items": [1777426656, 1777330000],
  "page": 1,
  "page_size": 20,
  "total": 128,
  "has_more": true
}
```

兼容策略：

- 未传 `page/page_size` 时，短期仍返回旧格式数组。
- 传入分页参数时，返回分页对象。
- 前端改造完成后，再评估是否统一为分页对象。

### 读取摘要

```text
GET /api/jjc/ranking-stats?action=read&timestamp=<timestamp>
```

读取顺序：

1. Mongo `jjc_ranking_stat_summaries`
2. 文件 `summary.json`
3. 旧文件 `<timestamp>.json` 转 summary

### 读取明细

```text
GET /api/jjc/ranking-stats/details?timestamp=<ts>&range=<range>&lane=<lane>&kungfu=<name>
```

读取顺序：

1. Mongo `jjc_ranking_stat_details`
2. 文件 `details/<range>/<lane>/<kungfu>.json`
3. 旧文件 `<timestamp>.json` 抽取对应明细

## 迁移脚本方案

脚本：`scripts/migrate_jjc_ranking_stats_to_mongo.py`

输入：

- 默认扫描 `data/jjc_ranking_stats/`
- 支持可选 `--timestamp <ts>` 单个迁移
- 支持 `--dry-run`
- 支持 `--overwrite` 控制是否覆盖 Mongo 已有快照

处理逻辑：

1. 扫描新目录结构和旧单文件结构。
2. 对新结构读取 `summary.json`，写入 `jjc_ranking_stat_summaries`。
3. 对新结构遍历 `details/<range>/<lane>/*.json`，写入 `jjc_ranking_stat_details`。
4. 对旧单文件先构造 summary，再从 `members` 拆 detail 写入 Mongo。
5. 输出迁移统计：快照数、summary 写入数、detail 写入数、跳过数、失败列表。

幂等要求：

- 以 `timestamp` upsert summary。
- 以 `(timestamp, range, lane, kungfu)` upsert detail。
- 默认不覆盖已有文档，除非显式传 `--overwrite`。

## 实施阶段

### 阶段 1：Mongo repo 与索引

执行项：

- 新增 `JjcRankingStatsRepo`。
- 增加 summary/detail 保存和读取方法。
- 在 `src/infra/mongo.py` 增加索引初始化。
- 更新 `docs/design-docs/database-design.md`。

验收：

- Mongo 初始化能成功创建索引。
- repo 方法可被单测或脚本 dry-run 调用。

### 阶段 2：新数据双写

执行项：

- `save_ranking_stats()` 在生成统计后写 Mongo。
- 保留现有文件写入。
- 写 Mongo 失败时记录 warning，不影响原有文件落盘。

验收：

- 定时任务或手动生成统计后，文件与 Mongo 都有数据。
- Mongo summary 与文件 summary 关键字段一致。
- Mongo detail 与文件 detail 成员数量一致。

### 阶段 3：API 优先读 Mongo

执行项：

- `action=list` 支持分页参数并优先读 Mongo。
- `action=read` 优先读 Mongo summary。
- `/details` 优先读 Mongo detail。
- 保留文件 fallback。

验收：

- 旧调用不带分页参数仍兼容。
- 新分页调用能返回稳定分页结果。
- Mongo 缺失某个 timestamp 时仍可从文件读取。

### 阶段 4：历史数据迁移

执行项：

- 编写迁移脚本。
- 先执行 `--dry-run`，确认扫描数量和预期一致。
- 小批量迁移最近几个 timestamp。
- 全量迁移历史文件。
- 抽样对比文件与 Mongo 的 summary/detail。

验收：

- `action=list&page=1&page_size=20` 可以只查 Mongo 完成分页。
- 历史 timestamp 的 `read` 和 `details` 均可从 Mongo 读取。
- 迁移报告无失败，或失败项可单独重试。

### 阶段 5：收敛文件依赖

执行项：

- 观察一段时间后，决定是否保留文件双写。
- 如果保留文件作为备份，文档明确 Mongo 是 API 主数据源。
- 如果移除文件写入，需要先更新回滚方案和 runbook。

验收：

- API 主路径不再依赖扫目录。
- 运维文档说明清楚 Mongo 与文件的职责。

## 回滚策略

- 阶段 2 和阶段 3 均保留文件 fallback。
- Mongo 写入失败不阻塞原有文件落盘。
- 如果 Mongo 读取异常，API 可直接回退文件读取。
- 迁移脚本默认幂等，不删除文件。

## 风险与注意事项

- `members` 明细如果未来继续膨胀，单个 detail 文档可能接近 Mongo 16MB 限制，需要二次拆分。
- 旧 API 返回数组，新分页 API 返回对象，前端调用需要明确区分。
- 多实例部署时，迁移完成前仍可能存在“某实例有文件、某实例没有文件”的不一致，应尽快让 API 主读 Mongo。
- 数据库新增集合和索引必须同步数据库设计文档。

## 推荐顺序

1. 新增 repo 与索引。
2. 新生成统计双写 Mongo 和文件。
3. API 增加分页参数并优先读 Mongo。
4. 编写并执行历史文件迁移脚本。
5. 前端切到分页列表。
6. 稳定后评估是否取消文件双写。
