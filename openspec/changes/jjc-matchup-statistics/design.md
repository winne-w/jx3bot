## Context

现有 `jjc_match_detail` 保存每场完整详情，是历史对局主事实；`jjc_match_participants` 将每场 3v3 拆成最多六条玩家记录，主要服务按 `global_id` 的角色对局分页和玩家最高分统计。线上玩家投影已超过八百万条，现有索引没有面向双方心法组合的访问路径。直接在玩家投影或完整详情上实时重建两队、计算平均分、统计并分页，会反复扫描和分组大量记录。

当前 `JjcInspectRepo.save_match_detail()` 捕获 Mongo 写入异常并返回 `None`，无法证明主事实保存成功；排行榜 inspect、排名预热和同步 worker 又会在不同阶段补 replay、`global_id` 或 `match_time`。本变更必须先形成可验证的保存成功契约和统一派生编排，才能避免事实投影先于主事实或使用未补齐数据。

本变更跨 storage、service、API、静态页面和 Mongo 数据迁移，且必须保持现有详情、角色对局列表与奇穴展示行为不变。行为合同见 `specs/jjc-matchup-statistics/spec.md`。

## Goals / Non-Goals

**Goals:**

- 为任意 0～3 心法组合对阵提供稳定、可索引的查询路径。
- 在不舍入的前提下按双方三人平均游戏分过滤，并返回原始胜场和胜率。
- 让统计与唯一对局分页由同一套方向匹配规则产生。
- 确保所有主详情保存入口只在确认持久化成功后更新派生投影。
- 复用现有详情接口查看装备和奇穴，不复制完整详情大字段。
- 使实时投影、历史回填、失效清理和一致性核验使用同一构建规则。

**Non-Goals:**

- 不计算或展示优势方、置信区间、显著性或样本充分性结论。
- 不汇总奇穴选择率；首版只支持逐场打开详情查看奇穴。
- 不替换 `jjc_match_participants` 的角色查询职责。
- 不保证事实集合变化期间 offset 页码的跨请求快照一致性。
- 不支持超过 14 天的单次查询，不引入离线报表仓库或新的数据库依赖。
- 不删除或重写完整历史详情、装备快照和奇穴快照。

## Decisions

### 1. 新增每场一条的 `jjc_match_facts` 统计投影

每场结构有效的 3v3 对局写一条轻量事实，以 BSON 整数 `match_id` 为唯一业务键：

```text
match_id, active, invalid_reason, match_time, map, duration, match_type
schema_version, source_cached_at, source_hash
team1/team2:
  won
  players[{role_name, server, kungfu_id, kungfu, game_score, score_source}]
  kungfu_ids, combo_keys
  score_sum, score_count, score_complete, score_avg
any_team_combo_keys
min_team_score_sum, max_team_score_sum
```

首版不在事实中持久化 `season_id`：查询已经以绝对 `match_time` 为边界，重复保存赛季会与 active `jjc-match-season` 的玩家列表语义形成两套归属。未来若组合统计增加赛季选择器，再复用统一赛季规则新增字段。

`game_score` 沿用现有口径：先规范化 `total_score`，无有效值时再规范化 `score`。布尔值、负数、超过 1000000、非有限数和非整数数值无效；JSON 整数、值为整数的有限浮点数及规范十进制整数文本可转换，`0` 是有效分数，不能用 truthiness 判缺失。两者都无有效值时才视为分数缺失。事实不要求玩家具有 `global_id`，避免身份缺失导致三人心法和分数被跳过。装备、奇穴、指标数组和 replay 不进入该集合。

选择每场一条是因为统计、分页和摘要天然以对局为单位。备选方案一是在 `jjc_match_participants` 上每次分组六行，但其规模和索引不适合作为主读路径；备选方案二是聚合 `jjc_match_detail`，但完整文档大且嵌套数组难以索引。

### 2. 明确定义事实准入与失效

构建纯函数先规范化并校验：

| 条件 | 处理 |
|---|---|
| `match_id`、`match_time` 不能转为正整数 | 对可定位的规范 `match_id` 写失效 tombstone；无法定位 ID 时跳过并计错 |
| 显式对局类型存在且不为 3 | 写失效 tombstone |
| `team1/team2` 不存在或任一队不是恰好三名玩家 | 写失效 tombstone |
| 任一玩家 `kungfu_id` 不能转为正整数 | 写失效 tombstone |
| `team1.won` 与 `team2.won` 不满足异或 | 写失效 tombstone |
| 以上结构有效但任一 `game_score` 缺失 | 保留事实，`score_complete=false` |
| 结构及六人分数完整 | 保留事实，`score_complete=true` |

实际发生时间由同一纯函数按以下优先级提取：外层保存 payload 的 `match_time/matchTime/start_time/startTime/time`，详情的同名字段，最后是 `basic_info` 的同名字段；只接受可精确转换的正整数。高优先级命中后不再被低优先级覆盖，多个来源冲突时记录所选来源和值；绝不回退到 `cached_at`、`projected_at` 或当前时间。

`unavailable`、非 3v3 或后来变成结构非法的详情不会物理删除版本水位，而是以相同 CAS 规则把该 `match_id` 更新为 `active=false` 的 tombstone，只保留失效原因、源版本、源摘要和投影审计字段，并清除队伍组合、分数和列表摘要字段。所有查询只读取 `active=true`。这样较旧有效回填不能因“目标不存在”而恢复已失效事实。结构非法不进入 `missing_score_match_count`；该计数只面向结构有效但玩家分数不完整的 active 事实。

### 3. 规范化心法 ID 与无歧义组合键

所有事实和查询把心法 ID 规范化为正整数；Mongo 中 `kungfu_ids` 保存整数数组。单一页面目录由服务端维护，第一版把现有前端名称→图标 ID 常量迁入 Python 元数据模块，并通过 `GET /api/jjc/matchups/meta` 返回；`config.KUNGFU_META` 的名称和类别合并进同一响应。历史事实中格式合法但未列入当前目录的正整数 ID 仍允许查询，避免退役心法被目录更新阻断。

组合键采用版本化且无碰撞的规范字符串：先将组合内整数升序排列，再编码为 `v1:<count>:<id1>,<id2>,...`，例如双奶秀为 `v1:2:10080,10080`。队伍按三个玩家位置生成所有非空 1～3 人子多重集合并去重，每队最多七个 `combo_keys`；`any_team_combo_keys` 是双方并集，最多十四个。

最初方案另存每场最多 49 个双方 `matchup_keys`，但按百万级对局会放大为数千万索引项。首版删除该字段，只索引最多十四个 `any_team_combo_keys`。双方非空查询先以 A、B 中字典序较小的组合键锚定候选，再检查候选是否包含另一组合键，并用 `team1/team2.combo_keys` 计算真实方向；当 A=B 时只需一个等值锚点，再由方向条件确认双方都包含该组合。

### 4. 双向命中产生两个方向样本，事实与分页不重复

对至少一边非空的查询定义：

```text
forward = team1 contains A AND team2 contains B
reverse = team2 contains A AND team1 contains B
```

空配置的 `contains` 恒为真。只命中一个方向时产生一个方向样本；双向命中时同一事实产生两个方向样本，A 与 B 各贡献一胜一负。分页以事实为单位，一场只出现一次；摘要保持主事实的 `team1/team2` 顺序，并返回 `matched_orientations`。

有方向模式满足：

```text
total = match_count
orientation_sample_count = match_count + bidirectional_match_count
team_a_wins + team_b_wins = orientation_sample_count
win_rate = wins / orientation_sample_count * 100
```

胜率四舍五入到一位小数。零方向样本时双方胜场为 0、胜率为 `null`。双方配置都为空时只浏览全量，方向样本和双向命中为 0，双方胜场与胜率为 `null`。

### 5. 使用三人分数总和精确筛选平均分

每队仅在三人的 `game_score` 都存在时设置 `score_complete=true`。保存整数 `score_sum`，`score_avg` 只用于展示。双方平均分都落入 `[score_min, score_max)` 等价于：

```text
min_team_score_sum >= score_min * 3
max_team_score_sum < score_max * 3
```

这样不会因显示为一位小数而改变边界。分数参数限定为 `0..1000000` 内整数，乘三不会接近 BSON int64 边界。时间与配置命中但任一队分数不完整的事实计入 `missing_score_match_count`，不进入有效统计、总数和分页。

### 6. 固化 API 与页面输入输出合同

新增：

- `GET /api/jjc/matchups/meta`：使用统一响应封装，`data` 返回 `kungfus[{id,name,category,icon_id,display_order}]`、`time_presets=[1,3,7,14]`、`page_sizes=[20,50,100]` 和 `limits{max_days:14,score_min:0,score_max:1000000,max_team_kungfus:3,max_page:100000}`。心法按 `display_order ASC, id ASC` 返回。
- `POST /api/jjc/matchups/search`：统一统计和分页。

请求字段：

| 字段 | 类型 | 必填/默认 | 约束 |
|---|---|---|---|
| `start_time` | int | 必填 | 正整数 Unix 秒 |
| `end_time` | int | 必填 | 大于 start，范围不超过 14 天 |
| `score_min` | int | 必填 | `0..1000000` |
| `score_max` | int | 必填 | `score_min < score_max <= 1000000` |
| `team_a_kungfu_ids` | list[int] | `[]` | 最多 3 个正整数，保留重复 |
| `team_b_kungfu_ids` | list[int] | `[]` | 最多 3 个正整数，保留重复 |
| `page` | int | `1` | `1..100000` |
| `page_size` | int | `20` | 仅 20、50、100 |

为保证项目统一错误结构，路由接收 FastAPI `Request`，在函数内调用并捕获 JSON 解析异常，再显式校验对象和字段，避免损坏 JSON 或 Pydantic 在进入路由前返回未包装的 422。所有新增注解使用 Python 3.9 兼容的 `Optional`、`List`、`Dict`、`Union`。

响应 `data` 包含 `normalized_filters`、`statistics`、`items`、`page`、`page_size`、`total` 和 `has_more`。`normalized_filters` 回显绝对时间、分数和页码，并将双方心法 ID 各自升序规范化、保留重复。合法范围内的越界页返回成功空列表且统计不变。摘要保持源队伍顺序，`matched_orientations` 使用 `forward/reverse` 数组表达方向。响应不增加优势判断字段。

### 7. 使用一个组合索引和一个时间索引

除覆盖 active 与 tombstone 的 `match_id` 唯一索引外，为 `active=true` 文档新增两个 partial indexes：

```text
any_team_combo_keys, match_time DESC, match_id DESC
match_time DESC, match_id DESC
```

前者只含一个数组字段，符合 MongoDB 多键索引限制。双方非空时从规范化 A、B 组合键中选择字典序较小者作为确定性索引锚点，以 `any_team_combo_keys = anchor` 和时间范围取候选，再在后续阶段检查另一组合键和真实方向；A=B 时只使用一个锚点。单边非空时锚定该组合键，双方为空时使用时间索引。交换 A/B 仍选中同一锚点，不改变结果或访问路径。

Mongo 流水线固定为“`active=true` partial index 候选 `$match` → 与索引一致的 `$sort` → 另一组合键、方向和最终条件 → `$facet`”。`$facet` 只在候选已缩小和排序后计算缺分数、统计、总数及当前页，分页分支不重复排序。分数范围无法与数组、时间和排序同时全部由一个复合索引满足，因此在组合与时间候选之后过滤。多键索引是否能在目标 Mongo 消除阻塞排序仍以 `explain` 为准，不由文档假定。

实现门禁使用目标 Mongo 的 `explain("executionStats")` 验证索引命中、是否存在阻塞 `SORT`、`keysExamined/docsExamined`、执行时间和 `$facet` 内存；同时从真实详情抽样外推事实文档、索引项数与存储体积。常见 7 天查询目标为 2 秒内，14 天或双方为空查询目标为 5 秒内。若单次 `$facet` 未达到门禁，必须先拆分统计/分页聚合或增加按日预聚合；全部规格形态达到门禁后才开放页面，而不是删减已确认的查询能力。

### 8. 页码分页保持现有交互，并明确一致性边界

首版保留页码分页和 20/50/100 页大小，`page` 上限为 100000，排序固定为 `match_time DESC, match_id DESC`。上限用于避免无法安全传给 Mongo 的极端 `$skip` 和无界深页请求；合法范围内超过末页仍返回空列表。事实集合不变时，该顺序保证确定和不重复；同步或回填插入新事实时 offset 后续页可能变化，页面允许反映最新数据，用户刷新后从最新总数重新浏览。本需求不增加查询快照集合或游标协议。

快捷时间在用户发起查询时转换成绝对 Unix 秒并写入 URL；自定义日期按 `Asia/Shanghai` 日界转换，用户选择的结束日期包含全天，API 的排他 `end_time` 取结束日期次日 00:00。这样分享链接不会随打开日期滑动，但数据库后补事实仍可能改变结果，这是最终一致系统的正常行为。

### 9. 新增独立页面并复用现有详情接口

新增 `public/jjc-matchups.html`。筛选区从 meta API 加载心法目录，提供时间快捷项、自定义范围、分数上下限、双方 0～3 心法标签和交换按钮；摘要区只显示原始统计；列表区显示双方三名玩家分数、平均分、心法、胜负、地图和时长。

首次打开默认最近 7 天、双方配置为空、分数区间空白；合法分数填写前禁用查询。查询状态以绝对时间写入 URL。点击对局继续调用现有 `/api/jjc/ranking-stats/match-detail?match_id=...` 查看装备和奇穴。若现有弹窗代码无法低风险共享，执行计划只在新页封装最小适配，不做无关重构。

### 10. 统一主详情保存成功契约与派生编排

`JjcInspectRepo.save_match_detail()` 固化为成功返回 `True`，非法 `match_id` 或 Mongo 写入失败抛出异常，不再静默返回。新增业务层统一持久化编排：先保存 `jjc_match_detail`，只在收到 `True` 后分别尝试身份投影、玩家投影和事实投影；每个派生失败独立记录日志，不阻断其他派生，也不回滚主事实。

入口矩阵：

| 入口 | 当前保存/补齐时点 | 新事实处理 |
|---|---|---|
| inspect 缓存 miss 实时详情 | replay 补齐后保存 | 统一保存成功后投影 |
| inspect 缓存 hit 后台 replay 补齐 | 更新主详情后再投影 | 统一保存成功后覆盖 |
| inspect `no data found` | 保存 unavailable 并清玩家投影 | 统一保存成功后按源版本写失效 tombstone |
| 排名统计预热 | replay 补齐后直接保存 | 改走统一编排；unavailable 写失效 tombstone |
| 同步 worker | inspect 先保存，随后补 occurrence `match_time`、replay 并重新投影 | 补齐后再次走统一主详情保存编排，避免只投影未落库的临时 payload |

`src/services/jx3/singletons.py` 创建一个事实 repo、事实投影 service 和统一保存编排，并注入 ranking、inspect、sync 所需链路；`src/api/__init__.py` 显式注册新 router。相关测试逐个证明每个入口的主事实成功、失败、unavailable 和最终补齐行为。

### 11. 用源版本和摘要防止回填旧写覆盖

active 事实与 tombstone 都保存 `source_cached_at` 和 `source_hash`。统一编排保证：只要规范化源摘要变化，就为该对局分配严格大于已保存版本的 `source_cached_at`；只补 replay、装备、奇穴或身份字段而规范摘要不变时可沿用版本。`source_hash` 覆盖 active/invalid 状态、失效原因及除投影审计字段外的全部事实来源字段，包括 match ID/time、地图、时长、类型、双方胜负，以及六名玩家的角色名、服务器、心法 ID/名称和分数字段。

规范源摘要使用键排序、紧凑分隔符和 UTF-8 的 canonical JSON 序列化，再计算 SHA-256；实时、回填、active 和 tombstone 共用同一函数。CAS 真值表固定为：目标不存在时写入；本次 `source_cached_at` 较新时写入；较旧时跳过；时间相同且 hash 不同时记冲突且不写；时间与 hash 都相同时，仅当本次 `schema_version` 更高才重建派生字段，否则为幂等 no-op。tombstone 与 active 记录在同一唯一 `match_id` 文档上切换，因此失效版本水位不会因清理丢失。

历史回填从 `jjc_match_detail` 读取必要字段，按规范化整数 `match_id` 升序保存水位；默认 dry-run，只有 `--apply --yes` 写入。输出可写入、缺分、结构跳过、待失效、旧版本跳过、冲突和异常数量。只读核验比较主事实与事实的源 hash，报告缺失、孤儿、应失效、hash 不一致和 schema 过期记录。

## Risks / Trade-offs

- [主详情保存契约变化影响既有调用方] → 先用调用入口测试锁定现状，再统一改为明确结果；所有保存入口迁入编排后才开放新事实投影。
- [派生投影失败造成短暂漏数] → 主事实优先，结构化记录 `match_id/source/schema/error`，回填与核验幂等修复。
- [组合多键索引仍可能较大] → 已由最多 49 键降到最多 14 键；上线前抽样外推并以目标 Mongo 存储和缓存压力为门禁。
- [热门单心法或双方为空候选较多] → 默认 7 天、最长 14 天，按真实 `explain` 和 `$facet` 内存决定是否开放高成本形态。
- [历史详情字段异常] → 严格区分结构非法与仅缺分；不推测心法、时间、胜负或分数。
- [当前心法目录不含历史 ID] → 页面选项使用单一服务端目录，但 API 接受任意格式合法的正整数历史 ID。
- [页码期间事实变化导致 offset 漂移] → 规格明确只保证固定事实集下稳定；刷新查询获取最新总数，不新增复杂快照协议。

## Migration Plan

1. 先收敛 `save_match_detail()` 成功契约和统一持久化编排，用单元测试覆盖所有入口；此阶段不创建事实集合。
2. 新增事实纯构建、源 hash、CAS upsert/clear、索引和事实投影 service，完成 Python 3.9 编译与 repo/service 测试。
3. 发布双投影写入但暂不开放新 API 页面，运行历史回填 dry-run，抽样估算 BSON、索引项和总存储。
4. 核对 dry-run 后使用 `--apply --yes` 分批回填，再运行缺失、孤儿、应失效、hash 和 schema 核验。
5. 在目标 Mongo 对单心法、双心法、完整组合、单边空、双方空以及 7/14 天范围执行 `explain` 和响应耗时检查；性能门禁不通过的查询形态不开放。
6. 注册 meta/search API 和独立页面，完成参数错误包装、统计恒等式、分页、交换双方、URL 恢复及现有详情弹窗冒烟。
7. 若需回滚，先隐藏页面和路由并停止事实投影调用；完整详情和玩家投影继续工作。事实集合可保留供修复后重新启用，无需破坏性删除。
