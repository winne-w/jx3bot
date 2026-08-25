## Context

现有 `jjc_match_detail` 保存每场完整详情，是历史对局的主事实；`jjc_match_participants` 将每场 3v3 拆成最多六条玩家记录，主要服务按 `global_id` 的角色对局分页和玩家最高分统计。玩家投影已超过八百万条，现有索引也没有面向双方任意心法组合的访问路径。若直接在该集合上实时按对局分组、重建两队、计算平均分并分页，常见查询会反复扫描和分组大量玩家行。

本变更跨 storage、service、API、静态页面和 Mongo 数据迁移，且必须保持现有完整详情、角色对局列表和奇穴展示行为不变。行为合同见 `specs/jjc-matchup-statistics/spec.md`。

## Goals / Non-Goals

**Goals:**

- 为任意 0～3 心法组合对阵提供稳定、可索引的查询路径。
- 在不舍入的前提下按双方三人平均游戏分过滤，并返回原始胜场和胜率。
- 让统计与唯一对局分页由同一套方向匹配规则产生，避免口径漂移。
- 复用现有详情接口查看装备和奇穴，不复制完整详情数据。
- 使新旧对局投影都可幂等生成、核验和重建。

**Non-Goals:**

- 不计算或展示“优势方”、置信区间、显著性或样本充分性结论。
- 不汇总奇穴选择率；首版只支持逐场打开详情查看奇穴。
- 不改变 `jjc_match_detail` 的事实地位，不替换 `jjc_match_participants` 的角色查询职责。
- 不支持超过 90 天的单次查询，不引入离线报表仓库或新的数据库依赖。
- 不删除或重写完整历史详情、装备快照和奇穴快照。

## Decisions

### 1. 新增每场一条的 `jjc_match_facts` 统计投影

每场可解析的 3v3 对局写一条事实文档，以 `match_id` 为唯一业务键。文档只保存统计和列表所需摘要：

```text
match_id, match_time, season_id, map, duration
match_type, detail_available, schema_version, projected_at
team1/team2:
  won
  players[{role_name, server, kungfu_id, kungfu, game_score, score_source}]
  kungfu_ids
  combo_keys
  score_sum, score_count, score_complete, score_avg
any_team_combo_keys
matchup_keys
min_team_score_sum, max_team_score_sum
```

`game_score` 沿用现有玩家投影口径：优先取 `total_score`，缺失时取 `score`。事实投影不要求玩家具备 `global_id`，避免玩家身份缺失导致三人分数或心法被无故丢弃。装备、奇穴、指标数组和完整 replay 不进入本集合。

选择该模型是因为统计、分页和摘要天然以“对局”为单位。备选方案一是在 `jjc_match_participants` 上每次分组六行，但八百万级玩家行和缺少组合索引使它不适合作为主读路径；备选方案二是直接聚合 `jjc_match_detail`，但完整文档体积大且嵌套数组难以建立所需索引。

### 2. 用多重集合子组合和无方向对阵键检索

每支三人队伍根据排序后的心法 ID 生成所有非空 1～3 人子多重集合键，最多七个不同键。生成过程按玩家位置选组合后排序并去重，因此两个相同心法仍保留数量语义。

文档同时保存：

- `team1.combo_keys`、`team2.combo_keys`：用于最终方向判断。
- `any_team_combo_keys`：双方组合键的并集，服务单边为空的查询。
- `matchup_keys`：team1 每个非空子组合与 team2 每个非空子组合组成的规范化无方向键，最多 49 个。

双方都非空时先以规范化 `matchup_key` 定位候选；仅一边非空时以 `any_team_combo_keys` 定位；双方为空时使用时间索引。候选记录必须再根据两队 `combo_keys` 计算正向与反向布尔值，索引键只负责缩小范围，不作为最终统计方向。

备选的“两条方向记录/场”会让分页去重和历史存储翻倍；单场一条加运行时方向标记能更直接地保证唯一对局分页。

### 3. 双向命中产生两个统计方向，但事实与分页不重复

对非空或单边为空查询定义：

```text
forward = team1 contains A AND team2 contains B
reverse = team2 contains A AND team1 contains B
```

空配置的 `contains` 恒为真。只命中一个方向时产生一个方向样本；同时命中两个方向时，同一事实产生两个方向样本，配置 A 与 B 各贡献一胜一负。分页始终以事实文档为单位，因此同一 `match_id` 只出现一次，并在摘要中返回实际命中的方向。

双方配置都为空时没有可解释的配置方向。该模式只用于浏览全量：`orientation_sample_count=0`，双方胜场和胜率为 `null`，但仍返回唯一对局、缺失分数和分页数据。

### 4. 使用三人分数总和执行平均分区间判断

每队仅在恰有三名玩家且三人的 `game_score` 都存在时设置 `score_complete=true`。保存整数 `score_sum`，`score_avg` 仅用于响应展示。双方都落入 `[score_min, score_max)` 等价于：

```text
min_team_score_sum >= score_min * 3
max_team_score_sum < score_max * 3
```

这样不会因平均分显示为一位小数而改变边界归属。匹配时间和配置但任一队分数不完整的事实进入 `missing_score_match_count`，不进入有效统计、分页总数或列表。

### 5. 单个 POST 查询接口同时返回统计和分页

新增 `POST /api/jjc/matchups/search`，请求体包含：

```json
{
  "start_time": 0,
  "end_time": 0,
  "score_min": 0,
  "score_max": 0,
  "team_a_kungfu_ids": [],
  "team_b_kungfu_ids": [],
  "page": 1,
  "page_size": 20
}
```

路由只做参数解析和统一错误响应；service 负责心法 ID 校验、规范化、方向规则和响应结构；repo 负责索引候选和 Mongo 聚合。Mongo 聚合使用同一候选条件和 `$facet` 分支计算缺失分数、有效统计、分页总数和当前页，避免统计与列表使用不同条件。

响应 `data` 包含 `normalized_filters`、`statistics`、`items`、`page`、`page_size`、`total` 和 `has_more`。`statistics` 对有方向模式返回 `match_count`、`orientation_sample_count`、`team_a_wins`、`team_b_wins`、双方胜率、`bidirectional_match_count` 和 `missing_score_match_count`；双方为空时方向相关值按规格返回 0 或 `null`。响应不增加优势判断字段。

时间与分数均采用左闭右开区间。自定义范围最长 90 天，分页大小限制为 20、50、100，排序固定为 `match_time DESC, match_id DESC`。首版使用页码分页以符合用户交互和现有 API 风格；90 天上限、组合键候选和 100 条页大小限制共同控制 `skip` 成本。

### 6. 使用三个面向查询形态的索引

除 `match_id` 唯一索引外，新增：

```text
matchup_keys, match_time DESC, match_id DESC
any_team_combo_keys, match_time DESC, match_id DESC
match_time DESC, match_id DESC
```

每个复合索引只包含一个数组字段，避免 MongoDB 平行数组复合多键索引限制。分数完整性和两个分数总和范围在组合与时间候选之后过滤；Mongo 对多个范围字段无法同时高效利用复合索引，强行加入会增加写放大而收益有限。实现完成后用常见 7 天组合执行 `explain`，若候选扫描仍过大，再依据真实执行计划评估索引顺序，不提前增加推测性索引。

### 7. 新增独立页面并复用详情接口

新增 `public/jjc-matchups.html`。筛选区提供时间快捷项与自定义范围、分数上下限、双方 0～3 心法标签和交换按钮；摘要区只显示原始统计；列表区提供 20、50、100 页大小并展示双方三名玩家分数、平均分、心法、胜负、地图和时长。

首次打开默认选择最近 7 天且双方配置为空，分数区间保持空白；只有填写合法分数上下限后才允许查询，不对用户未选择的分段作默认猜测。

查询状态写入 URL，刷新或分享后可恢复。点击对局继续调用现有 `/api/jjc/ranking-stats/match-detail?match_id=...`，复用现有完整详情行为查看装备和奇穴。若现有弹窗代码无法低风险共享，执行计划只在本页封装最小适配，不为本需求发起无关前端重构。

### 8. 在业务层编排两个独立可重建投影

完整详情保存成功后，业务层分别调用现有玩家投影 service 和新的对局事实投影 service；storage 之间不互相调用，保持 `services -> storage` 依赖方向。两种投影任一失败都不回滚 `jjc_match_detail`，而是记录 `match_id`、来源、投影版本和错误。

历史事实从 `jjc_match_detail` 读取必要字段构建，不能仅依赖 `jjc_match_participants`，因为后者会跳过缺少 `global_id` 的玩家。回填脚本默认 dry-run，只有 `--apply --yes` 才写入，支持批大小、断点、版本核验和失败计数。相同构建纯函数同时供实时投影与回填使用，避免两套口径。

## Risks / Trade-offs

- [统计投影写入失败造成短暂漏数] → 完整详情优先保存，投影失败记录结构化日志；回填与版本核验可幂等修复。
- [每场最多 49 个对阵键增加存储和索引体积] → 3v3 固定规模使键数有明确上限，文档不包含装备、奇穴和 replay；上线前抽样测量 BSON 与索引体积。
- [热门单心法对阵在 90 天范围候选较多] → 默认 7 天、最长 90 天，以组合键和时间先过滤；用目标数据 `explain` 验证，目标为常见 7 天查询统计加首屏分页不超过 2 秒。
- [历史详情字段缺失导致事实不完整] → 保留心法、分数完整性标记；缺分对局单独计数，不推测或填充历史分数。
- [心法名称变化导致查询漂移] → 查询和组合键只使用稳定心法 ID，名称仅作快照展示；未知 ID 在入口拒绝。
- [双方为空没有有意义的胜率方向] → 明确作为全量浏览模式，方向统计返回 0/null，不按 team1/team2 建立任意方向。
- [页码较深时 skip 成本上升] → 页面上限 90 天和每页 100；先保持现有交互一致，真实数据证明需要时再演进游标分页。

## Migration Plan

1. 创建 `jjc_match_facts` 集合索引并发布事实构建、repo 与双投影写入，暂不开放新页面入口。
2. 运行历史回填 dry-run，记录可解析、缺分、跳过和失败数量；抽样对照 `jjc_match_detail` 的双方心法、分数与胜负。
3. 在确认统计后使用 `--apply --yes` 分批幂等回填，再运行版本、缺失和构建失败核验。
4. 对常见单心法、双心法、完整三心法、单边为空和双方为空查询执行 `explain` 与响应耗时检查。
5. 开放 API 和独立页面，完成分页、交换双方、URL 恢复和现有详情弹窗冒烟。
6. 若需回滚，先隐藏页面和路由并停止新事实投影调用；完整详情和玩家投影未改变。新增事实集合可保留供修复后重新启用，无需破坏性删除。
