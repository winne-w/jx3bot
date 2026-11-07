# 排名统计队首同步 TDD 执行计划

本计划遵循 docs/PLANS.md，随实现、验证及评审持续更新。

## Purpose / Big Picture

用户已于 2026-11-07 确认 design.md，要求按 TDD 细化并实现，完成后调用子 agent 审阅方案、计划及实现。本次将该指令作为按已确认方案推进 TDD 的执行授权；用户随后明确授权开发、测试、review、commit 与生产发布，均已执行。

每轮统计对有效成员重新请求最近 14 天对局同步；新批次位于所有未领取任务之前，运行中任务在释放后合并重排。

## Progress

- [x] 用户确认业务方案及 TDD 推进方式。
- [x] 细化单文档 CAS、请求标识、排序、测试及交付边界。
- [x] 写失败测试并记录 Red。
- [x] 实现 repo 状态转换和排序，使核心测试 Green。
- [x] 实现统计运行上下文、unknown 成员及保存补偿幂等。
- [x] 真实隔离 Mongo 并发/排序测试与相关回归。
- [x] 同步数据库、项目上下文、运行手册及规格。
- [x] 完成后调用子 agent 独立评审；修复发现并复测。
- [x] 写本地验收结果。
- [x] 选择性提交、独立快照验证与生产基线候选验证。
- [x] 完成生产发布、线上冒烟与原暂停状态恢复。
- [x] 更新规格基线、归档 change 与提交发布记录。

## Surprises & Discoveries

现有 ranking 即时入口与快照保存入口使用 cache_time 作为批次 ID；同一缓存上的下一轮统计不能依赖该值区分。即时入口要求心法成功，unknown 补偿仅在缓存路径生成。排序在 worker、位置计算、列表及 Mongo 索引四处，需要同步。syncing 请求不能提前更新当前同步使用的 season/queue_mode/until。

## Decision Log

主 agent 顺序承担测试与实现，避免共享 repo/统计链路并行编辑；用户要求的子 agent 安排在实现完成后，独立只读评审，不修改源码。

使用单文档 CAS 及四个调度字段，不引入新集合、事务、通用队列框架或全局计数器：ranking_request_order（最后接受请求，保留用于同轮幂等）、ranking_pending（syncing 时最新请求参数）、queue_front_order（当前队首批次）、queue_front_rank（原始排名）。请求顺序为固定宽度 time_ns 加随机 run ID 的字符串，同一轮贯穿即时与补偿，较小顺序请求不可覆盖较大请求。缺字段视为普通任务。

排序统一为 queue_front_order DESC、queue_front_rank ASC、priority DESC、queued_at ASC、identity_key ASC、_id ASC；最新排名批次在前，同批次排名稳定；普通任务两个 front 字段均为空，沿用优先级与 FIFO。位置计算按相同词典序统计前置任务，处理 Mongo null/missing 语义。索引在 identity 与 legacy 集合分别新增，保留旧索引用于兼容回滚。

ranking 请求以 status 和“ranking_request_order 为空或小于本请求”作为原子条件，状态变化时重读，已接受同轮/较新请求时不再写。真实 Mongo 64 并发暴露相等值 CAS 的重试耗尽后已采用这一更小的原子单调条件。syncing 仅写 request_order 和 pending，不改租约或当前执行参数。其他非 disabled 状态直接 queued、清 next_sync_after、设置本轮参数和 front，保留 fail_count/error 审计。priority 用 max(原值, 1)，不下调人工值。

成功/失败/中断释放共用小型 repo 私有 CAS helper：读取 pending，合并结果与待排参数，比较最新 request_order 及有效租约条件后一次原子写入。无 pending 时保留原状态机；正常成功/失败清当前 front，中断重排保留 front。pending 存在时 queued、清等待、转用新参数并清 pending。过期租约按角色逐条使用同一 helper，避免 update_many 丢掉待请求；错误 worker 不得释放。请求并发到达可使 CAS 重试，不能清除新请求。

## Outcomes & Retrospective

已完成两轮核心 Red/Green，并补充入口及人工优先级竞态 Red/Green。Python 3.13.2 与 Python 3.9.25 各 388 项回归通过，独立评审后各补 3 项定向用例通过，累计 391 项，其中 9 项真实隔离 Mongo；三路初评及两路复评通过，两个 P3 已闭环。不触碰现有身份恢复、离线任务、武器白名单等无关改动。独立提交快照与生产候选均验证通过，生产382项通过；5文件发布、QQ/API/索引及4worker验收通过，单角色队首请求由真实worker完成。详见deployment.md。

## Context and Orientation

src/storage/mongo_repos/jjc_sync_repo.py 负责 identity 主队列及 legacy fallback。src/services/jx3/jjc_ranking.py 负责排名统计、成员即时入队与快照保存补偿。src/infra/mongo.py 初始化排序索引。src/plugins/jx3bot_handlers/jjc_ranking.py 与 src/plugins/status_monitor/jobs.py 仅扩充传递 payload 的条件，以确保两类入口在心法开关关闭时仍传递 _sync_request。tests/test_jjc_sync_worker_queue.py 使用轻量内存集合；新增 tests/test_jjc_ranking_force_sync.py 以行为测试覆盖请求和重排，tests/test_jjc_ranking_force_sync_mongo.py 验证真实 Mongo 原子性。运行服务已有 lease_owner/expiry CAS，本次沿用且不扩大成租约体系重构。

## Plan of Work

第一轮 Red：覆盖 pending/cooldown/exhausted/failed/queued 对 priority 0/1/100 的新请求强制 queued；disabled 不变；同轮无效重放、旧轮延迟、新轮重新触发；syncing 参数不被改动，成功/失败后补排一次、过期旧租约拒绝、中断/租约恢复。排序测试使用普通 priority=1000、旧排名批次、新排名批次及同批次不同排名，验证领取/位置/分页一致。

第一轮 Green：新增 queue 请求私有方法并替换 enqueue_ranking_member 的 priority 跳过。身份建档仍通过 RoleIdentityRepo，已找到 identity 后失败不再退回另一个 legacy 身份。关联元数据更新与请求调度参数分离。替换六个释放分支的写入点并覆盖过期恢复，保持原返回接口。

第二轮 Red：统计服务同轮两入口共享 run context，重复 cache_time 的下一轮生成不同请求；unknown 有效角色即时入队；分组成员去重且保留原始 rank。保存失败不得撤销即时已入队请求；失败入口不伪造成功。

第二轮 Green：在 get_ranking_kungfu_data 的局部上下文生成 run context，仅通过返回 payload 的 _sync_request 传给 save_ranking_stats，再经显式 sync_request 参数传入保存补偿；不写入统计 summary，避免修改复用的 ranking_result/cache 对象。直接调用低层保存入口而没有上下文时，在该调用生成独立上下文。以 seen 身份键去重，并由 repo 做最终幂等；移除即时入口对 found/kungfu 的限制。unknown 明细在兼容路径也保留，用于补偿。

第三轮：为真实 Mongo 新增隔离测试；配置只接受 loopback:27029，随机 jjc_sync_front_test_ 数据库，清理只针对该随机库。验证并发请求、领取唯一性、请求与释放交错、租约恢复、Mongo null 排序、索引 explain。回归现有同步、dispatcher、身份关联、统计及角色查询。

## Concrete Steps

在仓库用 .venv/bin/python -m unittest tests.test_jjc_ranking_force_sync 记录失败，再修改实现直至通过。每次测试应由缺失行为失败，不接受导入错误当作 Red。统计测试使用 fixture/AsyncMock，不访问真实推栏或生产 Mongo。

回归命令：.venv/bin/python -m unittest tests.test_jjc_sync_worker_queue tests.test_jjc_match_data_sync tests.test_jjc_ranking_stats_repo tests.test_jjc_ranking_history_win_kungfu tests.test_jjc_ranking_kungfu_cache tests.test_jjc_ranking_inspect。真实 Mongo：JJC_TEST_MONGO_URI=mongodb://127.0.0.1:27029/ .venv/bin/python -m unittest tests.test_jjc_ranking_force_sync_mongo。类型语法用 Python 3.9 ast.parse(feature_version=(3,9)) 和 py_compile 校验相关文件，最后 git diff --check。

更新 docs/design-docs/database-design.md 的字段/索引/状态转换；更新 PROJECT_CONTEXT.md 与 docs/references/runbook.md 的行为及部署回滚手册；将通过验收的规格合并至 openspec/specs/jjc-ranking/spec.md。不修改路由或页面交互，列表后端排序保持与 worker 一致。

完成后调用只读子 agent，提供需求/方案/tasks/test-plan/本次 diff 与测试结果，要求检查正确性、并发、优先级、幂等、回滚、过度设计及更简洁替代。发现问题由主 agent 修复并执行相关复测，必要时复评。

## Validation and Acceptance

test-plan.md 的状态、幂等、排序和竞态用例全部通过。必须有真实隔离 Mongo 证据，不以 fake 代替 Mongo 原子性证明。当前环境不能验证生产吞吐和真实上游时延，生产有界冒烟与启动验收通过，吞吐和真实千人统计耗时不作已验证承诺。

已授权并完成的部署步骤：暂停消费者并停旧 bot/worker，发布同版及新增索引，启动后用两轮统计观察排序和重排。回滚先停消费者，将 ranking_pending 物化为普通 queued 任务，清 front/pending 后回退代码；保留 request_order 审计及已有数据，不删队列、身份或比赛。

实际 Python 3.9 命令使用已有隔离环境 `/tmp/jjc-kungfu-python39/bin/python`；首次误选空环境的导入失败不算业务测试失败，改用已具备依赖的环境后同一回归集通过。

复评新增用例：test_request_retries_if_worker_claims_between_read_and_update、test_new_request_competes_with_worker_claim、test_new_client_and_repo_restore_persisted_pending_after_consumer_restart。两版本各补测3项通过，生产代码未变，未重复整跑已通过的388项。消费者重建验证为新client/repo级别，不宣称OS完整进程或上游集成。测试用Mongo已关闭，日志保留；本地验收完成，实现已提交并发布，change归档，完整证据见deployment.md。
