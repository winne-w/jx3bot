# JJC 排名统计快照迁移 MongoDB 计划

更新时间：2026-05-21

状态：已实现，待提交。已完成 Mongo repo/索引、生成统计写入 Mongo、HTTP API 仅读 Mongo、历史数据迁移和一次性迁移脚本清理。代码提交前，本计划继续保留在 active。

## 背景

迁移前 JJC 排名统计快照写入文件：

- `data/jjc_ranking_stats/<timestamp>/summary.json`
- `data/jjc_ranking_stats/<timestamp>/details/<range>/<lane>/<kungfu>.json`
- 兼容旧结构：`data/jjc_ranking_stats/<timestamp>.json`

这套结构解决了单个大 JSON 首屏过重的问题，但历史数据列表仍依赖扫描目录。随着快照数量增长，`/api/jjc/ranking-stats?action=list` 会越来越难以支持稳定分页、排序、过滤和多实例部署。

## 目标

- 将 JJC 排名统计快照迁移到 MongoDB，支持历史列表分页。
- 保留 summary/details 拆分结构，避免把所有明细塞进单个 Mongo 文档。
- API 仅读 Mongo，不再回退文件。
- 新生成统计只写 Mongo，不再写入 `data/jjc_ranking_stats/` 文件。
- 历史文件已迁移到 Mongo；一次性迁移脚本已删除。

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
  - `save_ranking_stats()` 写入 Mongo summary/detail。
  - 移除运行时统计文件写入。
- `src/api/routers/jjc_ranking_stats.py`
  - `action=list` 读 Mongo 分页。
  - `action=read` 读 Mongo summary。
  - `/details` 读 Mongo detail。
  - Mongo 未命中时直接返回 `not_found`。
- `docs/design-docs/database-design.md`
  - 补充新集合 schema、索引和已清理脚本说明。
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

读取来源：Mongo `jjc_ranking_stat_summaries`。Mongo 未命中时返回 `not_found`。

### 读取明细

```text
GET /api/jjc/ranking-stats/details?timestamp=<ts>&range=<range>&lane=<lane>&kungfu=<name>
```

读取来源：Mongo `jjc_ranking_stat_details`。Mongo 未命中时返回 `not_found`。

## 实施阶段

### 阶段 1：Mongo repo 与索引

执行状态：已完成。

执行项：

- 新增 `JjcRankingStatsRepo`。
- 增加 summary/detail 保存和读取方法。
- 在 `src/infra/mongo.py` 增加索引初始化。
- 更新 `docs/design-docs/database-design.md`。

验收：

- Mongo 初始化能成功创建索引。
- repo 方法可被单测或脚本 dry-run 调用。

### 阶段 2：新数据写入 Mongo

执行状态：已完成。

执行项：

- `save_ranking_stats()` 在生成统计后写 Mongo。
- 不再写入 `data/jjc_ranking_stats/` 文件。
- 写 Mongo 失败时记录 warning。

验收：

- 定时任务或手动生成统计后，Mongo 有 summary/detail 数据。
- 不再新增 `data/jjc_ranking_stats/<timestamp>/` 运行时统计文件。
- Mongo 写入失败会记录 warning。

### 阶段 3：API 读 Mongo

执行状态：已完成。

执行项：

- `action=list` 支持分页参数并读 Mongo。
- `action=read` 读 Mongo summary。
- `/details` 读 Mongo detail。
- 移除文件 fallback。

验收：

- 旧调用不带分页参数仍兼容。
- 新分页调用能返回稳定分页结果。
- Mongo 缺失某个 timestamp 时返回 `not_found`。

### 阶段 4：历史数据迁移与脚本清理

执行状态：已完成。

执行项：

- 历史文件已迁移到 Mongo。
- 删除 JJC ranking stats 一次性迁移脚本和测试。
- 删除已完成的旧文件到 Mongo 一次性迁移脚本。

验收：

- `action=list&page=1&page_size=20` 可以只查 Mongo 完成分页。
- 历史 timestamp 的 `read` 和 `details` 均可从 Mongo 读取。
- 代码库不再保留已完成的一次性文件迁移脚本。

## 当前验证记录

2026-05-22 已执行：

```bash
python -m unittest tests.test_jjc_ranking_stats_repo tests.test_jjc_ranking_stats_router
python -m py_compile src/storage/mongo_repos/jjc_ranking_stats_repo.py src/infra/mongo.py src/services/jx3/jjc_ranking.py src/api/routers/jjc_ranking_stats.py jjc_query.py tests/test_jjc_ranking_stats_repo.py tests/test_jjc_ranking_stats_router.py
```

结果：通过。review 后补充 strict Mongo 读写错误传播、CLI 等待 Mongo 写入任务完成，并在 API 读取路径增加 Mongo 命中/未命中日志；历史数据已迁移后删除一次性迁移脚本。

### 阶段 5：收敛文件依赖

执行项：

- 移除运行时文件双写。
- 移除 API 文件 fallback。
- 文档明确历史文件仅作为迁移输入，不再作为运行时数据源。

验收：

- API 主路径不再依赖扫目录。
- 运维文档说明清楚 Mongo 与文件的职责。

## 回滚策略

- 运行时主数据源为 Mongo。
- 历史文件不再作为 API fallback。
- Mongo 写入失败会记录 warning；需通过日志定位后用临时运维脚本或手工补写。

## 风险与注意事项

- `members` 明细如果未来继续膨胀，单个 detail 文档可能接近 Mongo 16MB 限制，需要二次拆分。
- 旧 API 返回数组，新分页 API 返回对象，前端调用需要明确区分。
- 多实例部署时，迁移完成前 Mongo 可能缺少部分历史快照，应先完成迁移再切线上入口。
- 数据库新增集合和索引必须同步数据库设计文档。

## 推荐顺序

1. 新增 repo 与索引。
2. 新生成统计写入 Mongo。
3. API 增加分页参数并只读 Mongo。
4. 执行历史文件迁移。
5. 前端切到分页列表。
6. 移除文件双写与 API 文件 fallback。
7. 删除一次性迁移脚本。
