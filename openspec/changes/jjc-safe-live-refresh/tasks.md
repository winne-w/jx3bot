# JJC 最新对局刷新收尾计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

让已知角色通过独立刷新任务查看最新基础战绩，同时保留历史分页和统计口径。2026-10-09 用户取消共享推栏预算桶，并授权继续清理、验证和验收。官方请求恢复已提交直连实现，不再增加统一额度、并发许可或共享暂停。

## Progress

- [x] 恢复直连并删除预算桶实现与运行时配置，保持票据和有效默认凭据。
- [x] 清理未启用的 query_guard、查询租约、预算错误文案及只为预算添加的 HTTP 改动。
- [x] 检查并修复最新摘要、禁用状态读取、失败保留和 worker 生命周期问题。
- [x] 完成隔离真实 Mongo 的去重、容量、租约、空结果、失败和来源限制测试。
- [x] 完成路由、同步 worker、详情兼容测试与 Python 3.9 语法检查。
- [x] 完成桌面/手机浏览器刷新、轮询、错误和角色切换回归。
- [x] 完成独立只读 review，修复重要发现。
- [x] 更新 proposal/design/spec/test-plan/review/acceptance，记录证据与线上未验证范围。

## Surprises & Discoveries

历史 tasks 曾全部勾选完成但包含已删除预算功能，不代表回退后的验收；本轮勾选依据当前 test-plan/review/acceptance 的实际证据。扩大测试曾停滞，独立运行已有同步 worker 的 7 项测试通过；本轮分组运行并限制总时间。`openspec/AGENTS.md` 在当前仓库不存在，以 PROJECT_CONTEXT.md 和 docs/PLANS.md 为依据。

## Decision Log

2026-10-09 用户决定不保留预算桶；最新刷新任务容量、角色冷却和 POST 来源频率属于刷新任务机制，继续保留。用户“继续”授权按已经列出的收尾范围实施，保留其他无关未提交改动。线上 Mongo 历史集合不删除。测试使用临时隔离 Mongo 和官方 stub，不连接生产服务。

2026-10-20 用户在未提交内容梳理后要求“按照你整理出来的进行操作”，授权先拆分提交页面布局与入口一致性调整，再修复最新战绩 worker 初始化失败、完成必要验证并收敛规格后提交刷新功能。授权覆盖本轮修复、文档同步、验证和分批 commit，不包含 push、线上部署或归档。proposal、design、spec 按直连回退后的实际边界重写，预算 brief/report/rollback 保留为历史档案。业务调用限制为最多两页 history 和一次必要 indicator；现有 HTTP 内部重试不受此次数约束，不再承诺总网络尝试最多四次。

## Outcomes & Retrospective

页面布局已独立提交为 `7d5bee8`。第二批完成 worker 初始化/就绪异常隔离、分页互斥和迟到响应防护；98 项分组离线测试、7 项隔离 Mongo、4 项 Node 竞态及 20 项浏览器检查通过。独立 review 的 P2 分页问题已修复并复查。验收依据见 test-plan.md、review.md、acceptance.md；本批达到本地提交标准，push、线上部署和 change 归档不在本轮范围内。

## Context and Orientation

`jjc_live_refresh.py` 处理已知身份和两页基础战绩；`jjc_live_refresh_repo.py` 管理任务状态、槽位、不可变快照和来源窗口；`jjc_live_refresh_runtime.py` 管理 bot 中 worker。`jjc_ranking_stats.py` 提交 POST 并在 GET 返回本地摘要。`jjc-synced-matches.html` 分区显示并最多轮询 10 次。直连实现位于 `src/utils/tuilan_request.py`，完整历史同步不改动。

## Plan of Work

先删除回退残留，针对 review 和测试发现补回归测试并修复；用独立 Mongo 检查原子性和 generation，再验证前端竞态和降级。将新行为同步回 change 的当前规划，历史 budget 文档仅保留回退记录。最后写真实验证记录和验收限制。

## Concrete Steps

离线分组执行 `.venv/bin/python -m unittest tests.test_tuilan_request tests.test_jjc_live_refresh tests.test_jjc_ranking_stats_router`、`tests.test_jjc_ranking_inspect`、`tests.test_jjc_sync_worker_runtime`。在 /tmp 临时启动 Mongo，显式设置 `JJC_TEST_MONGO_URI` 执行 `tests.test_jjc_live_refresh_mongo`，官方 client 全部使用 stub。用现有 Playwright 浏览器检查桌面和手机页面，所有 API 通过本地 stub 提供。执行 `openspec validate jjc-safe-live-refresh --strict` 并写验收。

## Validation and Acceptance

要求同角色跨进程只占一个槽、队列容量有界、过期 generation 无法覆盖或释放新任务、空结果进入冷却、失败保留已发布摘要、关闭刷新仍可读取历史摘要、页面保留已有列表并拒绝迟到角色响应。共享预算相关代码和运行时参数不再存在。线上凭据有效性和真实官方响应不属于离线证明范围。

2026-10-20 独立 review 发现刷新 GET 与加载更多并发会漏掉中间页；真实浏览器和 Node 先复现，再补双向互斥及历史响应的 generation/token/角色检查。分组测试避免历史路由 import stub 污染详情 logger；不把一次合跑失败掩盖为整仓测试通过。
