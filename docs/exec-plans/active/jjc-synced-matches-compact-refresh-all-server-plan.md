# JJC 对局查询紧凑列表、刷新按钮与全服候选计划

## 目标

- 已同步对局列表改为更紧凑的单行主信息展示，把双方心法图标放到胜负、心法、分数同一行，减少单条对局高度。
- 区分“刷新当前列表”和“加入后台同步队列”两个动作：刷新按钮只重新请求当前对局列表；后台同步按钮文案改为“加入同步队列”，排队/同步中时保持禁用状态。
- 服务器下拉默认提供“全部服务器”。选择全部服务器时不直接命中单个角色，而是按角色名返回本地候选列表，用户点击候选后再进入具体服务器角色。

## 范围

- `public/jjc-synced-matches.html`
  - 调整对局行 CSS 和 `renderMatchItem()` 图标位置。
  - 新增对局列表刷新按钮，绑定当前角色第一页列表重载。
  - 调整同步按钮文案：`加入同步队列`、`已在队列中`、`正在同步`。
  - 服务器选择默认增加“全部服务器”，允许空服务器提交查询。
- `src/api/routers/jjc_ranking_stats.py`
  - `GET /ranking-stats/synced-role` 允许空服务器，只要求角色名非空。
- `src/services/jx3/jjc_ranking_inspect.py`
  - 空服务器查询时跳过精确身份解析，直接返回候选列表。
- `src/storage/mongo_repos/role_identity_repo.py`
  - 候选查询支持空服务器，按同名和后缀名返回本地身份。
- `tests/test_jjc_ranking_inspect.py`
  - 覆盖空服务器查询返回本地候选且不调用精确身份解析。

## 验证

- 运行 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_ranking_stats_router tests.test_role_identity_repo`。
- 运行 `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/api/routers/jjc_ranking_stats.py src/storage/mongo_repos/role_identity_repo.py`。
- 运行页面内联 JS 语法检查：`node -e ...`。
- 手工回归：打开 `/jx3/jjc-synced-matches.html`，默认“全部服务器”输入角色名返回候选；点击候选进入具体角色；点击刷新图标只刷新当前对局列表；点击“加入同步队列”仍只提交后台同步。

## 风险与回滚

- 风险：空服务器查询可能返回多个历史身份，候选列表应只作为选择入口，不自动进入某个角色。
- 风险：新增列表刷新按钮和同步按钮文案可能影响用户理解，使用图标按钮和明确文案区分动作。
- 回滚：移除空服务器选项与后端空服务器候选逻辑；恢复原对局行布局和同步按钮文案。

## 执行记录

- 2026-06-02：创建计划，准备实现。
- 2026-06-02：已实现紧凑对局行、当前列表刷新按钮、同步队列文案和全部服务器候选查询。
- 2026-06-02：已验证 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_ranking_stats_router tests.test_role_identity_repo`，110 条通过。
- 2026-06-02：已验证 `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/api/routers/jjc_ranking_stats.py src/storage/mongo_repos/role_identity_repo.py`。
- 2026-06-02：已验证页面内联 JS 语法检查通过，输出 `ok 1`。
- 2026-06-02：已调用子 Codex agent review 当前 diff；结论为无 blocking/important 问题，抽象和简洁性可接受，无需修复循环。
- 2026-06-02：根据 code review 修复已解析角色加载对局仍使用原始输入的问题；为当前列表刷新增加角色快照校验，避免旧请求覆盖切换后的页面；将 queued 文案统一调整为同步队列语义；补充 `RoleIdentityRepo.find_synced_match_page_candidates(server="", name=...)` 真实 repo 单测，证明空服务器表示全服候选契约。
- 2026-06-02：已重新验证 `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_ranking_stats_router tests.test_role_identity_repo`，110 条通过；已重新验证 `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/api/routers/jjc_ranking_stats.py src/storage/mongo_repos/role_identity_repo.py`；已重新验证页面内联 JS 语法检查通过，输出 `ok 1`。
