# JJC 最新战绩受控刷新设计

## Context

需求动机见 `proposal.md`。本设计反映 2026-10-09 共享推栏预算回退后的边界；2026-10-20 用户授权继续修复、验证并拆分提交。预算历史保留在 `budget-brief.md`、`budget-report.md` 和 `budget-rollback.md`，其中已取消的机制不作为当前验收条件。

角色身份、完整历史分页与统计已有独立存储和同步链路。新能力复用本地身份，使用独立摘要、任务和 worker；沿用 Python 3.9+、既有 MongoDB 与 `src/utils/tuilan_request.py` 直连入口。列表 GET 不创建任务、不调用官方；旧详情、角色查询、机器人和历史 worker 保持直连行为。

## Goals / Non-Goals

目标是以有限业务调用检查正在查看的已知角色的近期 3v3 基础战绩，第一页可读后立即展示；相同角色共享任务，公开提交受来源、冷却和容量约束；故障时保留旧数据与完整历史能力。

不保证游戏结束后即时可见、不自动刷新所有角色、不为摘要补装备或回放、不将摘要充作完整统计，不新增登录、验证码或 WAF。不建立全部推栏调用的总预算、共享熔断或随机详情 ID 准入；不能据此承诺官方安全频率或全出口网络次数。

## Decisions

### 1. 本地读取与后台任务分离

`GET /api/jjc/ranking-stats/synced-role-matches` 获取原完整历史分页，并附加本地 `latest_matches` 和 `refresh`。功能关闭时 `refresh.state=disabled`，已有摘要仍可读取；摘要存储异常时原历史结果仍可返回。所有 GET 和轮询只读取 Mongo，不做隐式提交或官方回源。

页面首次读到可刷新状态时可自动提交一次 POST，手动刷新使用相同入口。`POST /api/jjc/ranking-stats/synced-role-refresh` 接收 `server`、`name`，先检查开关、参数和来源限制，再校验凭据、在线 worker 与本地身份。缺失本地身份返回 `identity_unavailable`，不按用户输入启动任意角色官方搜索。后台执行避免网页等待官方网络，并合并多个查看者的请求。

### 2. 最多两页历史业务调用

身份已有有效 SK01 时直接使用；否则只有 `role_id`、`zone`、`server` 均存在才调用一次 indicator，并要求返回的三个字段一致且 SK01 有效。身份不可靠则不继续历史请求。

history 每页 size=20、cursor 依次为 0 和 20。只接纳有效对局 ID、赛季开始至观察时间内的开始时间和 `pvp_type=3` 的记录。少于一页或遇到既有摘要边界时提前结束；满页且未遇边界时 `coverage_limited=true`，第二页后停止，不追赶完整历史。

业务层每个任务最多两次 history 调用和一次必要 indicator 调用，没有额外的业务重试循环。直连入口使用 `HttpClient(retries=2)`，一个逻辑调用可以包含多次网络尝试。任务期限在调用前检查，不能强制终止已在线程中执行的 HTTP 请求；任务有效期和页数上限不等于严格的 HTTP 总时限或“四次网络尝试”承诺。

### 3. 摘要先发布，与完整历史隔离

将新有效记录与先前仍可读摘要按 `match_id` 合并，按时间、ID 倒序截取最多 40 条。第一页即发布新快照；第二页失败时第一页已发布结果和旧摘要仍可读，整个任务保留上一成功检查时间。有效空结果仍保留旧摘要，任务成功结束时更新 `last_checked_at` 并进入冷却。

字段包含时间、胜负、MVP、心法、`total_mmr`、`mmr_delta` 和观察时间，沿用官方分数字段语义。摘要只写 `jjc_live_match_summaries`，不写完整参与者投影、`jjc_match_facts` 或完整历史水位。`recent_matches`、`pagination.total` 和历史翻页口径不变，页面两区允许同一对局分别出现。

### 4. 固定槽位和代际隔离

`JjcLiveRefreshRepo` 使用以下集合，写入采用 majority write concern：

| 集合 | 用途 |
|---|---|
| `jjc_live_refresh_slots` | 配置文档及预创建固定数值槽位；任务键部分唯一索引，排队和运行任务共同占槽 |
| `jjc_live_refresh_state` | 身份、赛季、3v3 的任务状态、generation、活动期限、冷却、成功检查时间和快照指针 |
| `jjc_live_match_summaries` | `(task_key, snapshot_id, match_id)` 唯一的不可变快照，保存 7 天并以 TTL 清理 |
| `jjc_live_source_limits` | 来源滚动时间窗口、CAS 版本及短期 TTL |
| `jjc_live_workers` | worker 心跳与有效期 |

任务键由身份 ID、赛季、比赛类型计算。同角色先原子取得 state admission，再领取过期空闲槽，不用 count-then-insert 判断容量。未取得槽位返回 `queue_full` 并短暂退避。槽位不以 TTL 删除，跨进程容量或冷却不一致时初始化失败。

任务有效期 120 秒，到期 queued/running 读为 `expired`，旧槽位可供后续提交复用。每代任务使用独立 generation；发布快照指针与写回状态同时校验 generation 和有效期，释放槽位也校验 generation。旧执行者即使在网络请求后恢复，也不能替换新指针或释放新槽位。未成为当前指针的快照最终由 TTL 清理。

默认容量 100，可配置范围 1–1000；默认角色冷却 120 秒，可配置为正值。成功完成时重新计算冷却；普通失败从 60 秒指数退避，最多 900 秒，有显式更长退避时尊重该值。失败不更新成功检查时间，不主动删除旧快照。

### 5. 来源限制仅控制公开提交

公开 POST 按每来源滚动 60 秒最多 6 次限频，由 Mongo 版本 CAS 控制。来源用 `JJC_LIVE_SOURCE_SECRET` 做 HMAC，存储散列和短期时间戳。默认使用真实连接 peer；仅当 peer 属于 `JJC_LIVE_TRUSTED_PROXIES` 时才从右向左解析最多 16 跳转发链，遇到非可信地址即停止。非可信客户端提供任意 `X-Forwarded-For` 不改变来源。

该窗口不覆盖 GET、旧详情查询或其他直连调用。来源限频、角色冷却和槽位共同限制刷新提交规模，不构成官方全出口预算。

### 6. 默认关闭与故障隔离

`JJC_LIVE_REFRESH_ENABLED` 默认 0；启用需要有效票据、签名密钥、设备 ID 和非空来源密钥。bot 托管独立 worker，每 5 秒心跳，心跳有效 20 秒；无在线 worker 时 POST 返回 `worker_unavailable`，不制造假排队。

启动阶段的配置检查、存储初始化或 worker 创建失败必须仅降级新功能并记录异常类型，不能阻断 bot 和既有历史能力。运行中 worker 异常由完成回调记录；停止时取消 worker，等待清理并使心跳失效。启动异常隔离是本轮必须修复和验证的问题，不能以文档更新代替回归测试。

POST 保持统一响应封装；提交状态包括 `disabled`、`queued`、`running`、`cooldown`、`queue_full`、`identity_unavailable`、`invalid_config`、`worker_unavailable`，执行结果可为 `success`、`expired`、`refresh_failed`。来源超限返回 HTTP 429、`rate_limited` 与 Retry-After；公开提交依赖异常返回 HTTP 503、`storage_unavailable` 和重试提示。上游错误归一化为任务失败，不向公开响应暴露凭据或原始错误。

回退后没有共享的 429 暂停、401/403 熔断、小时/日配额或保护开启时禁止直连机制。上游限流和鉴权失败可能引起当前任务失败和角色退避，不意味着全部推栏调用暂停。

### 7. 页面轮询兼容历史分页

`public/jjc-synced-matches.html` 分别渲染“近期战绩”和“已同步历史”，展示刷新状态、成功检查时间和覆盖有限提示。刷新期间保留已有列表，后台轮询仅更新摘要区，保留已加载历史页。

POST 返回 queued/running 后，每 3 秒 GET 本地列表，最多 10 次；达到上限提示稍后手动刷新，页面隐藏、离开或角色切换时停止。请求持有角色搜索 token 和刷新 generation，旧角色迟到响应不得覆盖新角色。功能关闭时刷新按钮仍可重新读取本地列表。

## Risks / Trade-offs

- 直连及内部重试仍可能增加外呼 → 区分业务调用和网络尝试，默认关闭新能力，离线使用官方 stub；不将来源限频描述为全出口保证。
- 线程内请求可能在任务取消后完成 → generation 和有效期隔离发布与完成，验证旧代不能改变当前结果。
- 两页上限及 7 天保留可能留下缺口 → 展示 coverage_limited，完整历史独立补齐，不推进历史水位。
- Mongo 原子性不能仅用 mock 证明 → 显式隔离测试库验证并发、容量、旧代写回、空结果和失败保留，禁止连接生产库。
- 首屏发布成功但后页失败 → 保留已发布快照，不更新成功检查时间，允许失败状态下继续展示数据。

## Migration Plan

保持新功能关闭，完成启动异常隔离修复、离线回归、真实隔离 Mongo 并发验证、浏览器交互及独立 review，如实记录未覆盖范围。增量创建集合和索引，不改写完整历史集合或水位，不清理历史预算集合。

部署后明确配置凭据、来源密钥和可信代理范围，检查 worker 在线与本地读取后再按需要启用。观察任务结果、等待和成功检查时间，不将离线验证视作官方凭据或真实数据验证。

回滚先设置 `JJC_LIVE_REFRESH_ENABLED=0` 并重启相关进程，停止新任务，保留摘要和历史数据。关闭后仍可读本地摘要与历史。本次回滚不重新引入预算保护，不删除生产历史数据。
