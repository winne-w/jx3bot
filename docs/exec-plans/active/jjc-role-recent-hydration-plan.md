# JJC 角色近期列表返回前统一详情补水计划

状态：已实现/待提交
更新时间：2026-05-09

## 背景

当前 JJC 排名统计页角色下钻会调用 `jjc_role_recent` 接口返回最近 3v3 对局列表。列表项里的对战心法展示依赖 `cached_detail_summary`，该摘要来自本地 `jjc_match_detail` 对局详情缓存。

现象上存在这样的问题：

1. 某次打开角色近期列表时，只能看到当时已经存在详情缓存的对局心法。
2. 后续用户再点开其他对局，虽然生成了新的 `jjc_match_detail` 缓存，但旧的角色近期列表缓存里不会自动带上这场对局的心法摘要。
3. 结果是即使详情缓存已经存在，角色近期列表仍可能要等 `jjc_role_recent` 缓存过期后，才重新展示完整的对战心法。

用户确认的修复方向是：

- `jjc_role_recent` 接口每次返回时，都基于当前 `recent_matches.match_id`，从本地 `jjc_match_detail` 缓存补充对战心法摘要。
- 不区分 `recent_matches` 主体数据来自上游实时接口，还是来自 `jjc_role_recent` 本地缓存。
- 只读本地对局详情缓存，不为了列表展示额外请求对局详情上游接口。

## 目标

- 统一 `jjc_role_recent` 的返回口径：所有返回路径在出参前都执行一次详情缓存补水。
- 让“某场详情缓存晚于角色近期列表缓存生成”的情况，在下一次请求 `jjc_role_recent` 时立即生效。
- 保持列表主体数据来源、TTL 和详情按需拉取策略不变。

## 非目标

- 不修改 `jjc_role_recent` TTL。
- 不主动预热或批量请求未缓存的对局详情。
- 不修改 `jjc_match_detail` 的 Mongo 结构。
- 不在本次计划内解决前端页面内存缓存是否重新请求接口的问题；该问题只作为联调观察项记录。

## 涉及文件

- `src/services/jx3/jjc_ranking_inspect.py`
  - 统一梳理 `get_role_recent` 的所有返回路径。
  - 确保每个会返回 `recent_matches` 的路径，在出参前都执行 `_hydrate_recent_matches_with_cached_details(...)`。
  - 如果存在漏掉的异常/分页/缓存分支，补齐补水调用点。
- `src/storage/mongo_repos/jjc_inspect_repo.py`
  - 复核批量读取 `jjc_match_detail` 摘要的方法是否满足当前补水口径。
  - 如有必要，仅做只读摘要提取层面的兼容修正，不改集合结构。
- `tests/test_jjc_ranking_inspect.py`
  - 增加或收敛单测，覆盖“recent 来自本地缓存”和“recent 来自上游实时构建”两条路径都能补水。
  - 覆盖“列表缓存生成后新增详情缓存，再次请求 recent 时能看到补水结果”。
- `docs/exec-plans/index.md`
  - 登记本计划。

## 设计规则

`jjc_role_recent` 返回流程统一分成两阶段：

1. 先确定 `recent_matches` 主体数据来源。
   - 可能来自 `jjc_role_recent` 本地缓存。
   - 可能来自上游实时拉取后组装。

2. 再基于 `recent_matches.match_id` 统一做一次本地详情缓存补水。
   - 批量查询 `jjc_match_detail`。
   - 只为命中的对局补充 `cached_detail_summary`。
   - 未命中的对局保持原样，不报错、不预热、不额外请求上游详情接口。

本次修复的正确性前提是“返回前重新补水”，而不是“把补水结果反写回 `jjc_role_recent`”。如果后续为了性能选择回写，也只能作为优化，不能作为正确性依赖。

## 实施步骤

1. 复核 `get_role_recent` 现有所有返回分支和 helper 调用链，列出会返回 `recent_matches` 的路径。
2. 在 service 层把”返回前补水”收敛为明确规则，避免遗漏某个分支只返回旧列表数据。
3. 复核 `batch_load_cached_detail_summaries` 的摘要字段和 unavailable 过滤逻辑，确保补水只读取本地缓存。
4. 补齐单测，分别验证：
   - recent 来自缓存时的补水
   - recent 来自上游实时构建时的补水
   - recent 初次生成后、详情缓存后补，再次请求时的补水
5. 执行后端测试和语法检查。
6. 手工联调确认：只要前端重新请求了 `jjc_role_recent`，就能看到最新已缓存的对战心法。

## 实现状态

- 步骤 1-3：已完成。`get_role_recent` 三条返回路径（缓存命中 / 首页实时 / 翻页）均已调用 `_hydrate_recent_matches_with_cached_details`；`batch_load_cached_detail_summaries` 已过滤 unavailable 文档；缓存写入使用 `copy.deepcopy` 确保不反写补水结果。
- 步骤 4：已完成。单测覆盖 10 条用例，含缓存命中补水、staleness 清理、实时构建后不反写缓存、详情缓存后补再次请求即生效（`test_role_recent_late_hydration_when_detail_cached_after_initial_request`）。
- 步骤 5：已完成。`python -m unittest tests.test_jjc_ranking_inspect` 10/10 通过，py_compile 无语法错误。
- 步骤 6：待手工联调。

## 验证

自动化：

```bash
python -m unittest tests.test_jjc_ranking_inspect
python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_inspect_repo.py
```

手工：

- 首次打开某角色近期列表，确认未缓存详情的对局没有 `cached_detail_summary`。
- 打开其中一场对局详情，生成 `jjc_match_detail` 缓存。
- 再次请求 `jjc_role_recent` 接口，确认该场对局出现对战心法摘要。
- 验证 recent 主体来自本地缓存和来自实时请求两种情况下，返回结果口径一致。
- 观察网络请求，确认列表页本身没有为了补心法去额外请求详情上游接口。

## 风险与回滚

- 风险：当前后端代码可能已经在部分路径做了补水，本次修改如果处理不当，容易出现重复补水或分支判断混乱。
  规避方式：以“统一返回前补水”为唯一规则，避免分散调用点继续膨胀。
- 风险：问题根因可能混有前端页面级缓存，导致后端修复后若前端不重新请求接口，现象仍可能复现。
  处理方式：将前端是否真正重新请求 `jjc_role_recent` 作为联调观察项，单独验证，不与本次后端计划混写。
- 回滚：移除本次 service/repo 补水收敛改动，恢复现有 recent 返回逻辑。

