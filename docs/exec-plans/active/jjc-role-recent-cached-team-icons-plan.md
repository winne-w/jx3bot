# JJC 角色近期对局缓存心法图标计划

状态：开发中
更新时间：2026-05-07

## 执行状态

- 2026-05-07：用户确认进入开发阶段，按 `subagent-implementation` 拆分后端补水/测试与前端展示两个不重叠实现任务。
- 2026-05-07：已实现缓存详情摘要批量读取、角色近期列表摘要补水、前端双方心法图标展示和后端单测；计划保留在 active，等待代码提交后归档。
- 2026-05-07：验证已执行：`python -m unittest tests.test_jjc_ranking_inspect`、`python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py`、前端内嵌脚本 `new Function` 语法检查。

## 背景

竞技场统计页角色下钻已支持查看最近 3v3 对局列表，并可点击单局按需缓存和展示详情。当前角色近期列表只展示该角色本局心法、胜负、分段、分数和时间；如果某个 `match_id` 已经存在 `jjc_match_detail` 缓存，列表行没有直接展示双方 3 个心法打 3 个心法的信息。

## 目标

- 在查看某个角色的最近 3v3 对局列表时，如果该对局详情已经被缓存过，则在该行展示双方队伍各 3 个心法图标。
- 只使用已有缓存详情提取摘要，不因为列表渲染去请求未缓存的对局详情。
- 保持点击对局查看详情的现有行为不变。

## 非目标

- 不预热所有最近对局详情。
- 不改变 `jjc_match_detail`、`jjc_role_recent` 集合结构和索引。
- 不改动 JJC 排名统计 summary/details 快照结构。
- 不处理 2v2、5v5 以外的额外展示规则；本次只服务已有最近 3v3 列表。

## 涉及文件

- `src/storage/mongo_repos/jjc_inspect_repo.py`
  - 增加批量读取已缓存对局详情摘要的方法，按 `match_id` 查询 `jjc_match_detail`。
  - 摘要只返回前端需要的 `team1/team2.players[].kungfu_id/kungfu/role_name/server`、胜负和缓存时间。
- `src/services/jx3/jjc_ranking_inspect.py`
  - 在构建或返回角色近期列表时，用最近列表中的 `match_id` 批量查询详情缓存。
  - 对命中的行增加 `cached_detail_summary` 字段；未命中则不增加或置空。
  - 缓存命中 `jjc_role_recent` 时也执行同样的摘要补水，避免 600 秒角色缓存挡住新产生的详情缓存。
- `public/jjc-ranking-stats.html`
  - 在角色对局列表行中读取 `cached_detail_summary`。
  - 有缓存摘要时展示 `队伍A 3 图标 vs 队伍B 3 图标`，图标沿用现有 `https://img.jx3box.com/image/xf/{kungfu_id}.png`。
  - 没有缓存摘要时保持原样，不展示占位。
- `tests/test_jjc_ranking_inspect.py`
  - 增加 service 单测：已有详情缓存时 recent match 被补充双方心法摘要；无详情缓存时不影响原字段。

## 数据结构

角色近期列表每条对局新增可选字段：

```json
{
  "match_id": 123,
  "cached_detail_summary": {
    "match_id": 123,
    "cached_at": 1778000000,
    "team1": {
      "won": true,
      "players": [
        {"kungfu_id": 10021, "kungfu": "花间游", "role_name": "角色A", "server": "梦江南"}
      ]
    },
    "team2": {
      "won": false,
      "players": []
    }
  }
}
```

兼容策略：

- 该字段为可选字段，老前端或老缓存数据忽略不受影响。
- 从 `jjc_match_detail.data.detail.team1/team2.players_info` 派生，不写回数据库。
- `unavailable: true` 的缓存详情不产生摘要。

## 实施步骤

1. 在 `JjcInspectRepo` 增加批量摘要查询方法，过滤无效 `match_id` 和 unavailable 详情。
2. 在 `JjcRankingInspectService` 增加列表补水 helper，并在实时构建、角色近期缓存命中、分页加载返回前统一调用。
3. 在前端增加列表行心法对阵图标渲染函数和对应 CSS。
4. 增加后端单测覆盖缓存摘要补水。
5. 执行验证命令并做手工回归。

## 验证

自动化：

```bash
python -m unittest tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py
```

手工：

- 打开 `public/jjc-ranking-stats.html`。
- 点击一个角色，确认最近 3v3 对局列表正常展示。
- 对已点开并缓存过详情的对局，重新打开该角色列表，确认该行出现双方心法图标。
- 对未缓存详情的对局，确认列表不主动请求详情且无多余占位。
- 点击带图标或不带图标的对局，确认单局详情弹窗仍正常。

## 风险与回滚

- 风险：批量查详情增加一次 Mongo 查询。列表默认 20 条，按 `$in` 查询，开销可控。
- 风险：缓存详情字段来源存在历史格式差异。摘要提取只读 `team1/team2.players_info`，字段缺失时跳过对应图标。
- 回滚：移除 service 补水、repo 摘要查询和前端图标渲染，角色对局列表恢复原展示。
