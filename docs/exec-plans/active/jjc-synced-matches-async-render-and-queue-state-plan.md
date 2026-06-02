# JJC 对局查询异步展示与排队状态文案计划

## 目标

- JJC 对局查询页中，赛季战绩 `role-indicator` 与本地已同步对局列表分开加载，哪个接口先返回就先展示对应区域，未返回的区域保留加载态。
- 页面触发同步使用固定优先级 `2`。当角色已经以不低于页面优先级排队时，更新按钮禁用并展示“已在排队”；当已有队列优先级低于页面请求，仍允许重新提交。
- 当不低于本页面优先级的同步请求已被 worker 领取为 `syncing` 时，页面继续展示更新中状态，避免从“已在排队”退回“当前没有本页面更新请求”。
- 页面明确说明对局数据来自异步同步，只展示已经同步落库且可查看的对局，列表不保证完整，可提交更新请求等待同步。

## 范围

- `public/jjc-synced-matches.html`
  - 拆分角色信息、赛季战绩和对局列表的渲染状态。
  - 调整同步状态和按钮文案，把 `status=queued && priority>=2` 识别为本页面已排队。
  - 补充 `status=syncing && priority>=2` 的正在更新展示和按钮禁用。
  - 增加异步同步说明文案。
- `src/services/jx3/jjc_ranking_inspect.py`
  - 抽出页面同步优先级常量。
  - 页面入队前检查已有队列；相同优先级已排队时返回现状，不刷新排队时间。
- `tests/test_jjc_ranking_inspect.py`
  - 覆盖相同优先级已排队时不重复入队。
  - 覆盖不同优先级已排队时仍调用入队。

## 验证

- 运行 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_ranking_stats_router`。
- 运行 `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/api/routers/jjc_ranking_stats.py`。
- 手工回归：打开 `/jx3/jjc-synced-matches.html`，查询一个已收录角色，观察战绩与对局列表可独立完成加载；同优先级排队时按钮显示“已在排队”并禁用。

## 风险与回滚

- 风险：前端状态拆分后，如果角色解析接口失败，两个子区域不应继续请求。控制方式：仍先解析角色身份，解析成功后才启动两个并行请求。
- 风险：已有非页面来源队列的 `queued` 状态不再展示为“已在排队”，可能看起来像没排队。控制方式：文案限定为“本页面更新请求”，并允许用户按页面优先级重新提交。
- 回滚：恢复 `searchRole()` 中 `Promise.all` 合并渲染和原 `enqueue_synced_role()` 直接入队逻辑。

## 执行记录

- 2026-05-29：已实现前端异步分区展示、页面同步优先级排队判断、相同优先级排队幂等返回和页面说明文案。
- 2026-05-29：已验证 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_ranking_stats_router`。
- 2026-05-29：已验证 `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/api/routers/jjc_ranking_stats.py`。
- 2026-06-02：已补充页面对 `status=syncing && priority>=2` 的展示，worker 领取后状态显示“正在更新”，按钮禁用；同时将页面排队判断调整为 `priority>=2`。
