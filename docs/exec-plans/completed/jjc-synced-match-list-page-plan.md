# JJC 已同步对局列表页面方案

状态：已完成，已归档
更新时间：2026-05-29

## 背景

当前 `public/jjc-ranking-stats.html` 已支持在竞技排名中点击个人，展示角色 indicator 指标、近期对局列表和对局详情。这个入口的“近期对局”来自推栏 `match/history`，并通过 `jjc_role_recent` 做 1 天缓存；点击单局详情时再读写 `jjc_match_detail`。

本需求要新增一个独立页面，用昵称 + 服务器搜索角色，查看“已经同步到本地”的对局列表。该页面的展示形态应尽量复用竞技排名个人下钻的视觉和交互，但对局来源必须改为本地同步数据，不再实时拉取 `match/history`。同时，原本页面里的“刷新对局”语义要从“重新拉取近期对局”改为“把该角色加入同步队列”。

本方案需要和 `docs/exec-plans/completed/jjc-identity-backed-sync-queue-plan.md` 保持兼容：若该计划已落地，以 `role_identities._id` / `jjc_sync_identity_queue.identity_id` 作为队列主关联；若执行时发现线上仍处于旧队列，先完成身份队列改造或在本计划中增加兼容桥接，不直接新增第二套主键语义。

## 目标

- 新增一个页面，用于按 `server + name` 查询 `role_identities` 中已有角色，并展示该角色已经同步到本地的 3v3 对局。
- 页面展示效果与竞技排名点击个人后的弹窗/面板保持一致：顶部展示 indicator 卡片，下面展示对局列表，点击对局仍打开现有对局详情弹窗。
- indicator 数据沿用排行榜个人下钻口径：优先读本地 `jjc_role_indicator` 缓存；本地没有或已过期时调用 `role/indicator` 接口并回写缓存。
- 对局列表只取本地同步下来的数据：只返回 `jjc_sync_match_seen.status='detail_saved'` 且本地 `jjc_match_detail` 存在可用详情，并且详情玩家 `global_id` 等于目标角色 `identity.global_id` 的对局，不调用 `match/history` 补列表。
- 对局列表状态文案不再显示“缓存时间”，改为展示该角色同步状态、角色最近一次同步时间，以及列表中每场对局的详情同步状态和详情保存时间。
- 页面中的“刷新对局”按钮改成“加入同步队列”；从该入口入队时优先级固定为 `2`。
- 搜索入口只能搜出 `role_identities` 已存在的角色；没有身份记录时返回明确的未收录状态，不走实时排行榜兜底创建身份。

## 非目标

- 不新增实时查询推栏战局历史的入口；本页面不是“查最新战绩”，只展示本地同步结果。
- 不改变竞技排名页面原有个人下钻入口的默认行为，除非抽取共用渲染组件时需要做无行为差异的重构。
- 不在本页面手工同步单场对局详情；单场详情仍由现有同步 worker 或现有详情 API 负责。
- 不重建历史身份数据，不处理 `role_identities` 缺失角色的自动发现。
- 不变更同步 worker 的调度排序语义，只新增本入口固定 priority=2 的入队调用。

## 业务规则

1. 搜索规则
   - 输入 `server` 与 `name` 后，后端只查询 `role_identities`。
   - 查询优先使用 `normalized_server + normalized_name`；若命中多条，按身份强度排序：`global_id` > `global` > `game_role` > `name`，再按 `last_seen_at/updated_at` 取最新。
   - 若没有命中，返回 `role_identity_not_found`，前端展示“该角色尚未被同步收录”。
   - 搜索成功后返回身份字段，包括 `identity_id`、`identity_key`、`server`、`name`、`zone`、`game_role_id`、`global_id`、`global_role_id`。

2. indicator 规则
   - 复用或抽取 `JjcRankingInspectService.get_role_indicator()` 的缓存和刷新逻辑。
   - 与排行榜入口不同的是，本页面身份解析不能回退实时排行榜；如果当前 identity 缺少调用 indicator 所需的 `zone + game_role_id/role_id`，返回 `indicator_params_missing`，但不影响本地对局列表展示。
   - `force_refresh=true` 仅用于 indicator 刷新按钮，不影响本地对局列表来源。

3. 对局列表规则
   - 以后端本地 Mongo 查询为准，不调用 `match/history`、`person-history` 或排行榜接口。
   - 对局候选来自 `jjc_sync_match_seen`：
     - 必须 `status='detail_saved'`。
     - 必须能按稳定身份关联到目标 identity：只允许 `identity.global_id == jjc_match_detail.data.detail.team*.players_info.global_id`。
     - 不允许使用服务器名、昵称、`global_role_id`、`role_id/game_role_id` 兜底匹配对局，避免转服、改名或同名历史造成串号。
     - 必须存在 `jjc_match_detail.match_id` 且 `data.unavailable != true`。
   - 列表按 `match_time` 或详情中的 `basic_info.start_time/detail.match_time` 倒序分页。
   - 每条对局返回现有 `renderRoleRecentMatchItem()` 所需字段：`match_id`、`won`、`kungfu`、`avg_grade`、`total_mmr`、`mmr_delta`、`mvp`、`start_time`、`duration`、`cached_detail_summary`。
   - 附加返回 `sync` 字段：`status`、`detail_saved_at`、`match_time`、`source_identity_id`、`source_identity_key`。

4. 同步状态规则
   - 角色级状态从同步队列读取：`status`、`queued_at`、`queue_mode`、`queue_source`、`priority`、`last_synced_at`、`latest_seen_match_time`、`history_exhausted`、`last_error`。
   - 页面顶部或对局列表工具栏展示“同步状态”和“最后同步时间”，替代原“对局列表缓存于/刚更新于”。
   - 若角色在队列中不存在，但 `role_identities` 存在，展示“未加入同步队列”，并允许点击加入同步队列。

5. 入队规则
   - 新增后端方法 `enqueue_synced_match_role(server, name)` 或通用 `enqueue_identity_from_search(identity_id, priority=2, source='synced_match_page')`。
   - 入队前再次校验 identity 存在；禁止因入队创建仅 name 级新身份。
   - 入队写入/更新队列候选时 priority 固定为 `2`，`queue_source='synced_match_page'`，`queue_mode='incremental_or_full'`。
   - 对已 `syncing` 的角色不抢租约，只返回当前状态；对 `queued/pending/cooldown/exhausted/failed` 的角色置为 `queued` 或复用现有 `enqueue_identity/enqueue_role` 语义。

## API 设计

新增路由建议放在 `src/api/routers/jjc_ranking_stats.py`，因为这是面向 JJC 页面展示的查询入口；入队动作可调用 `jjc_match_data_sync_service`，但路由仍保持薄层。

1. `GET /api/jjc/ranking-stats/synced-role`
   - 参数：`server`、`name`
   - 行为：只查 `role_identities` 和同步队列状态，不触发外部请求。
   - 返回：
     - `player`
     - `identity`
     - `sync_status`
     - `message`（未命中时为 `role_identity_not_found`）

2. `GET /api/jjc/ranking-stats/synced-role-matches`
   - 参数：`server`、`name`、`page=1`、`page_size=20`
   - 行为：先按身份表解析角色，再读取本地已同步对局。
   - 返回：
     - `player`
     - `identity`
     - `sync_status`
     - `pagination`
     - `recent_matches`
     - `cache` 字段废弃或仅保留兼容空对象；前端改读 `sync_status`

3. `POST /api/jjc/ranking-stats/synced-role-sync`
   - 参数：JSON 或 query 均可；建议 JSON：`server`、`name`
   - 行为：校验 `role_identities` 命中后加入同步队列。
   - 固定写入：`priority=2`、`source='synced_match_page'`、`mode='incremental_or_full'`
   - 返回：`queued`、`identity`、`sync_status`

现有 `GET /api/jjc/ranking-stats/role-indicator` 和 `GET /api/jjc/ranking-stats/match-detail` 继续复用；若实现时发现 `role-indicator` 会回退实时排行榜，应给本页面新增 `identity_only=true` 或新 service 方法，避免搜索未收录角色时被动创建身份。

## 前端设计

- 新增 `public/jjc-synced-matches.html`，不改排名页首屏。
- 页面主体是一个工具型页面：
  - 顶部搜索栏：服务器、角色名、搜索按钮。
  - 搜索成功后展示与排名个人下钻一致的角色标题、indicator 卡片、对局列表、对局详情弹窗。
  - 对局列表工具栏按钮文案改为“加入同步队列”；按钮点击后调用入队 API，并刷新角色同步状态。
  - 对局列表状态文案改为：
    - `同步状态：queued/syncing/cooldown/exhausted/...`
    - `最后同步：<last_synced_at 或 detail_saved_at>`
  - 未命中身份时展示空态，不显示“刷新/入队”按钮。
- 为减少复制，可先抽取排名页中角色指标卡片、对局列表 item、对局详情弹窗的纯函数到同页面内复用；若抽公共 JS 文件会扩大影响，第一版可接受少量复制，但行为需保持一致。
- 新页面通过 README 暴露路径：`GET /public/jjc-synced-matches.html`。

## 存储与索引

本计划不新增集合，扩展现有 repo 查询能力。

- `role_identities`
  - 复用 `idx_normalized_server_name`。
  - 如搜索多身份需要稳定排序，可在 repo 内排序，不新增索引。

- `jjc_sync_match_seen`
  - 已有 `idx_match_id`、`idx_status_match_time`、`idx_source_identity_key`。
  - 若活跃身份队列计划已落地，补充文档与索引：`idx_source_identity_id`。
  - 本页面查询按 `jjc_match_detail.data.detail.team*.players_info.global_id` 取候选，再用 `jjc_sync_match_seen.match_id + status='detail_saved'` 校验该对局已完成同步保存。

- `jjc_match_detail`
  - 复用 `idx_match_id`、`idx_detail_match_time`、`idx_detail_team1_server_role_name`、`idx_detail_team2_server_role_name`。
  - 查询只依赖 `players_info.global_id`；若线上数据量导致查询变慢，再补充 team1/team2 玩家 `global_id` multikey 索引，并同步更新 `src/infra/mongo.py` 与数据库设计文档。

## 模块改动

- `src/storage/mongo_repos/role_identity_repo.py`
  - 新增 `find_best_by_name_with_id(server, name)` 或复用 `resolve_best_identity_with_id()`，保证返回 `_id`。

- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 新增按 identity 读取队列状态方法。
  - 新增 `list_saved_matches_for_identity(...)` 或更底层的 `list_match_seen_by_identity(...)`。
  - 新增本页面入队封装，或扩展现有 `enqueue_identity()` 调用链。

- `src/storage/mongo_repos/jjc_inspect_repo.py`
  - 新增批量读取 `jjc_match_detail` 并构造本地对局列表的方法，复用 `_build_cached_detail_summary()`。
  - 必须保留 `get_match_detail()` 读取详情时的快照 hydrate 逻辑。

- `src/services/jx3/jjc_ranking_inspect.py`
  - 新增 `resolve_synced_role()`、`get_synced_role_matches()`、`enqueue_synced_role()`。
  - 新方法只能走本地 identity + 本地 match detail，不调用 `_build_role_recent_payload()`。
  - 可复用 `_hydrate_recent_matches_with_cached_details()` 和 indicator 方法，但要避免 identity 缺失时回退外部排行榜。

- `src/services/jx3/jjc_match_data_sync.py`
  - 若入队职责更适合放在同步 service，新增 `enqueue_existing_identity(...)`，固定 priority 由调用方传入并校验。

- `src/api/routers/jjc_ranking_stats.py`
  - 新增上述 API，保持统一 `success_response/error_response`。
  - 注意 Python 3.9 类型注解兼容，不使用 `dict[str, Any] | None` 这类写法。

- `public/jjc-synced-matches.html`
  - 新增页面。
  - 可复用排名页 CSS/函数，避免引入构建链。

- 文档
  - `README.md`：补充新 API 和新页面路径。
  - `docs/references/runbook.md`：补充手工回归。
  - `docs/design-docs/database-design.md`：如新增字段/索引，记录 `source_identity_id`、新增索引和同步状态展示口径。

## 实施步骤

1. 后端本地身份解析
   - 增加只读 identity 查询方法，确认未命中不触发外部接口。
   - 单测覆盖：命中、多身份排序、未命中。

2. 后端本地对局列表
   - 增加按 identity 查询已保存对局的 repo/service 方法。
   - 只按 `identity.global_id` 匹配详情玩家 `global_id`；没有 `global_id` 时返回空列表。
   - 单测覆盖：只返回 `detail_saved`，过滤 `detail_unavailable/failed/discovered`，缺详情时过滤。

3. 同步状态与入队
   - 增加同步状态读取与入队方法。
   - 入队固定 `priority=2`，source 固定 `synced_match_page`。
   - 单测覆盖：队列不存在时创建候选并排队、已 queued 时幂等、syncing 时不抢租约、identity 未命中时拒绝。

4. API 路由
   - 增加 3 个接口，保持统一响应格式。
   - `py_compile` 验证路由与 service 类型注解。

5. 前端页面
   - 新增 `public/jjc-synced-matches.html`。
   - 搜索、indicator、对局列表、加入同步队列、详情弹窗完整串联。
   - 文案从“缓存”切到“同步状态/最后同步”。

6. 文档联动
   - 更新 README、runbook、database design（如涉及索引/字段）。
   - 保持本计划在 active，进入实现阶段后逐项记录执行状态。

## 验证计划

自动化：

```bash
python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_sync_repo tests.test_jjc_sync_router tests.test_jjc_match_detail_hydration
python -m py_compile src/api/routers/jjc_ranking_stats.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_inspect_repo.py src/storage/mongo_repos/jjc_sync_repo.py src/storage/mongo_repos/role_identity_repo.py
```

手工回归：

- 打开 `/public/jjc-synced-matches.html`，输入一个 `role_identities` 已存在且有同步对局的角色，确认能展示 indicator 与本地对局列表。
- 断开或屏蔽推栏 `match/history`，确认页面对局列表仍可读取本地数据；indicator 缓存未过期时仍可展示。
- 输入不存在于 `role_identities` 的角色，确认不触发实时排行榜查询、不新增身份，并展示未收录空态。
- 输入已收录但缺少 `global_id` 的角色，确认对局列表为空且不使用昵称/服务器兜底。
- 点击“加入同步队列”，确认队列中该角色 `priority=2`、`queue_source=synced_match_page`、状态进入 queued 或保持 syncing。
- 点击列表中单场对局，确认复用现有对局详情弹窗，且详情来自本地 `jjc_match_detail`。
- 对 `detail_unavailable` 或 `failed` 的对局，确认不会混入列表。

## 线上反馈修复记录

2026-05-26：

- 部署环境静态 HTML 页面通过 `/jx3/<page>.html` 暴露，不带 `/jx3bot` API 前缀，也不带本地开发态 `/public` 前缀；API 仍通过 `/jx3bot/api/...` 暴露。
- `public/jjc-synced-matches.html` 中跳转“同步队列”的链接应指向 `/jx3/jjc-sync-queue.html`，并保留 URL 参数覆盖能力，方便本地开发或代理路径不同的环境调试。
- README 与 runbook 需要明确区分“页面路径”和“接口路径”：页面路径示例为 `/jx3/jjc-synced-matches.html`、`/jx3/jjc-sync-queue.html`，接口路径示例为 `/jx3bot/api/jjc/...`。
- 点击“加入同步队列”后，页面应展示 POST 入队接口返回的 `sync_status`，再刷新本地对局列表；若状态未变为 `queued/syncing`，应把当前状态展示出来，便于判断是 disabled、identity 缺失还是后端入队失败。

2026-05-27：

- 页面口径明确为“按稳定 `global_id` 匹配角色参与过的本地已同步对局”，不再等同于“该角色作为 source identity 发现的对局”。
- 后端查询只使用 `role_identities.global_id` 匹配 `jjc_match_detail.data.detail.team*.players_info.global_id`，再与 `jjc_sync_match_seen.status='detail_saved'` 做交集校验后去重返回。
- 取消服务器名、昵称、`global_role_id`、`role_id/game_role_id` 兜底匹配；身份未收录或身份缺 `global_id` 时不返回对局列表。
- 匹配结果中的胜负、心法、分数仍以 `global_id` 命中的目标玩家所在队伍和目标玩家字段为准。
- 本次修复不新增集合；如后续线上数据量导致详情玩家 `global_id` 查询过慢，再补充 team1/team2 玩家 `global_id` multikey 索引并同步数据库设计文档。

2026-05-29：

- 已随提交 `99b01e6` 落地并归档到 `completed/`。

## 风险与回滚

- 风险：只按 `global_id` 查询会漏掉历史详情中尚未回填 replay `global_id` 的对局。处理方式是先通过 replay 回填详情玩家 `global_id` 和 `role_id`，不回退昵称/服务器兜底。
- 风险：indicator 复用现有方法时可能回退实时排行榜，违背“只能搜 role_identities 有的角色”。实施时应增加 identity-only 路径或新方法，并用单测锁住。
- 风险：队列身份主键处于迁移期，priority=2 入队可能写到旧队列。实施前先确认 active 身份队列计划状态；若未完成，先完成或在同一实现中补兼容。
- 回滚：删除新页面和新增 API；保留新增 repo 只读方法不影响现有入口。若新增索引导致问题，可按 MongoDB 索引名回滚删除，业务仍回到原排名页与同步队列页面。
