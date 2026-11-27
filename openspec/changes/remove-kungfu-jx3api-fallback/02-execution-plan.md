# 移除心法查询 JX3API 兜底执行计划

最新交付状态：用户后续已授权创建PR及正式发布，两文件已部署并通过就绪/短时观察；详情以[06-delivery.md](06-delivery.md)为准，下文保留各阶段记录。

本计划依据 docs/PLANS.md 维护。2026-11-25 用户已确认方案和本执行计划，并明确要求开始实现；本地实现、双版本回归及独立增量 review 已完成，未部署。tasks.md 为本计划的 OpenSpec 入口，详细内容以本文为准。

## Purpose / Big Picture

所有心法查询只使用现有心法缓存、推栏和合法的本地当前赛季胜场证据。推栏失败、未匹配角色、身份缺失、心法为空或异常时，直接尝试本地胜场推断；推断失败返回明确的未知结果，不请求 JX3API，也不解析其竞技历史作为心法来源。普通竞技查询及区服解析等独立 JX3API 功能保持原有行为。

## Progress

- [x] 用户确认需求和方案范围。
- [x] 调查生产调用、服务装配、旧测试及兼容边界，形成执行计划。
- [x] 用户确认本执行计划。
- [x] T1：记录局部工作区基线，测试子 agent 先补行为回归并验证 RED。
- [x] T2：主 agent 修改服务流程、移除失效方法和专用依赖，调整调用方构造。
- [x] T3：运行定向回归、双版本检查和独立增量 review，修复实际问题。
- [x] T4：同步上下文、规格及验收记录，交付本地改动。

## Surprises & Discoveries

当前实际源码位于 WSL Ubuntu /home/songjingjing/codes/jx3bot，调查时分支 feat/jjc-safe-live-refresh、HEAD 53815bb；已有大量未提交修改，不能通过 reset、checkout 或覆盖整个文件恢复。本地 Windows 工作目录主要为历史诊断快照，不是实现目标。

get_user_kungfu 当前推栏查询后请求 defget_get，再调用 update_kungfu_cache 重复推栏查询，并从 JX3API history 提取心法。全 src 搜索显示 update_kungfu_cache 仅在这段即将删除的兜底中被调用；移除后不保留无调用的重复方法。token、ticket、jjc_query_url、defget_get 在 JjcRankingService 中仅供该外呼使用，Awaitable 注解也仅用于该依赖。

tests/test_jjc_ranking_history_win_kungfu.py 包含旧 JX3API 成功/失败路径与 prefer_cache 断言；不能只删除旧测试，需要改为验证新业务行为。其他测试和 benchmark 共用服务构造签名，需要机械调整，不能改变其原有业务断言。

openspec/AGENTS.md 当前不存在；遵循仓库 AGENTS.md、PROJECT_CONTEXT.md 和 docs/PLANS.md。生产部署状态不从当前 dirty 工作区推断。

## Decision Log

2026-11-25：用户已批准移除所有推栏失败后 JX3API 心法兜底；保留缓存与本地胜场规则。不清库、不迁移来源不明的缓存、不修改普通竞技查询，不执行提交、推送、部署或重启。

执行时删除 update_kungfu_cache：其仅有的生产调用也在移除范围内；不保留忽略 jjc_data 的兼容空壳。若编码前重新扫描发现新增调用，先明确来源并纳入等价收敛，不能静默保留 history 解析。

本地也无可用心法时，返回 server/name/kungfu=None/found=False/cache_time，并给出固定的无结果原因；不复用 JX3API 错误消息，不把 found=False 写为成功心法，不覆盖已有有效心法缓存。已有调用者使用 kungfu/found 判断，测试须验证排名仍保留未知角色与其同步资格。本地读取异常沿用既有 helper 的处理边界，不新增重试或延长预算。

## Outcomes & Retrospective

本地实现完成：新增行为测试先验证原实现 RED（6项/10个失败含子用例），最终新行为与历史胜场47项在双版通过；完整定向回归Python3.13/3.9各372项通过、无失败/错误/跳过，全部修改的Python文件双版py_compile通过，git diff --check通过。独立增量review无可操作问题。详细证据见03-test-plan.md、04-review.md、05-acceptance.md。未提交、推送、部署或重启；change保留到后续交付归档，不冒充生产验收。

## Context and Orientation

业务规则归 src/services/jx3/jjc_ranking.py。共享对象装配位于 src/services/jx3/singletons.py；推栏底层、异步心法刷新和本地胜场仓储是需要回归的既有能力，本需求不重写其选取算法、身份校验、赛季边界、worker 或存储结构。

JjcRankingService.get_user_kungfu 由排名统计兼容路径调用；prefer_cache=True 时先尝试已有缓存。当前新的缓存统计和后台心法查询已经使用独立查询服务，也必须证明不会因装配调整而回归。定时统计和 QQ 显式 tag、缓存心法选项均属于覆盖入口。

## Plan of Work

### T1：基线和行为测试先行

主 agent 在实施前重新读取 git status、相关文件 diff 和调用清单，将本次可能修改文件的原始字节与哈希保存在 change/evidence 的私有或被忽略目录，不复制运行配置和凭据。记录既有相关回归失败，避免与本次引入问题混淆。

依据 docs/PLANS.md 的测试先行约定，由测试子 agent 负责 tests/test_jjc_kungfu_no_jx3api_fallback.py 新用例，并调整 tests/test_jjc_ranking_history_win_kungfu.py 中旧契约。主 agent 此阶段不同时修改相同测试文件。测试使用 fake cache、AsyncMock、固定榜单与受控推栏结果，不连接生产 Mongo 或上游；有意义的 RED 必须来自仍访问 JX3API或仍采用其心法，而不是签名删除或依赖导入失败。

覆盖缓存直接命中、推栏成功、推栏空心法及异常、榜单失败/异常/无匹配、缺 gameRoleId/zone、上述失败后的本地胜场命中与未命中。用调用即抛错的 JX3API transport 并显式验证未调用，防止异常被吞掉而测试假通过。提供与推栏/本地心法不同的 JX3API 历史值，验证其永不进入结果或缓存。保留并回归本地证据的赛季、身份、胜场与来源字段断言。

### T2：收敛服务与装配

主 agent 修改 get_user_kungfu：保留 prefer_cache、随机等待、榜单与推栏成功资料/缓存预热；删除 defget_get 请求、JX3API history 提取和二次 update_kungfu_cache。推栏未成功后直接调用 _get_cached_match_detail_win_kungfu，命中用 _save_cached_match_detail_win_kungfu_result 保存并返回；未命中返回前述未知结构，不污染有效缓存。按实际匹配状态区分榜单无角色、身份缺失、无心法和异常日志，避免找到角色后仍记录未匹配。

删除无调用的 update_kungfu_cache 和 JjcRankingService 专用 token、ticket、jjc_query_url、defget_get 字段以及只被它们使用的 Awaitable import。singletons.py 删除对应构造参数和无其他引用的 jx3api_get.get import；保留 cfg.TOKEN/TICKET 的全局配置及其他功能装配。

逐个调整包含这些参数的测试与 benchmark：test_jjc_ranking_stats_repo、test_jjc_kungfu_refresh_integration、test_jjc_weapon_quality、test_jjc_ranking_kungfu_cache、jjc_role_query_integration_fixtures、test_jjc_ranking_explicit_tag、test_jjc_ranking_inspect、test_jjc_ranking_equipment_generation、test_jjc_ranking_force_sync、test_jjc_ranking_history_win_kungfu、test_jjc_role_query_budget、test_jjc_foreground_recovery、benchmark_jjc_ranking_kungfu_cache、test_jjc_ranking_raw。删除旧依赖字段断言时用 transport 未外呼/结果来源等行为断言替代。新测试跨 T1/T2 的签名调整由主 agent 在测试子 agent 交付后统一完成。

### T3：验证和独立复核

先跑新增行为测试与历史胜场测试，再运行下述完整定向组。Python 3.9/当前虚拟环境各执行一次；若 3.9 依赖不兼容，记录实际错误并使用已验证的隔离依赖环境，不改产品绕过测试。基于真实差异由独立 review 子 agent 只读检查移除完整性、缓存正确性、未知角色入队、日志和 dirty 工作区保护；主 agent 整合复核。实现与 review 不并行编辑同一文件，不执行在线接口冒烟。

### T4：文档和交付

修改 PROJECT_CONTEXT.md 的心法来源与失败行为说明；在本 change 中同步测试、review、验收记录以及 specs/jjc-ranking/spec.md delta。验证通过后再同步已生效基线规格；change 的状态如实标注本地实现与未部署，不自动宣称生产行为已改变。交付实际文件、通过数量、失败/限制和本次增量 diff；归档按仓库流程完成，不混入其他 active change。

## Concrete Steps

所有命令在实际 WSL 仓库执行。实施前使用 git status --short --branch、git diff -- src/services/jx3/jjc_ranking.py src/services/jx3/singletons.py，以及 rg -n 'get_user_kungfu|update_kungfu_cache|defget_get|jjc_query_url' src tests 确认基线。

首轮命令：.venv/bin/python -m unittest tests.test_jjc_kungfu_no_jx3api_fallback tests.test_jjc_ranking_history_win_kungfu

完整定向回归：.venv/bin/python -m unittest tests.test_jjc_kungfu_no_jx3api_fallback tests.test_jjc_ranking_history_win_kungfu tests.test_jjc_ranking_kungfu_cache tests.test_jjc_kungfu_refresh tests.test_jjc_kungfu_refresh_integration tests.test_jjc_ranking_identity_recovery tests.test_jjc_ranking_raw tests.test_jjc_ranking_explicit_tag tests.test_jjc_ranking_force_sync tests.test_jjc_ranking_stats_repo tests.test_jjc_ranking_inspect tests.test_jjc_ranking_equipment_generation tests.test_jjc_weapon_quality tests.test_jjc_role_query_budget tests.test_jjc_foreground_recovery

用 /home/songjingjing/.cache/jjc-latency-py39/bin/python 对同组执行 Python 3.9 回归。对本次实际修改的 Python 文件执行 py_compile，并运行 git diff --check。仅因新增失败或发现受影响调用才扩大测试，不无意义重复全仓测试。

最终扫描 src 中 update_kungfu_cache、defget_get、jjc_query_url 应无本服务遗留，确认无 JX3API history 心法提取。检查 src/services/jx3/arena_recent.py 和 src/plugins/jx3bot_handlers/queries.py 等独立 JX3API 功能 diff 未被本次改变；确认所有服务构造仍能导入或被测试执行。不要把 singletons 的真实初始化连到生产库来验证装配。

## Validation and Acceptance

所有约定失败场景 JX3API 心法请求数为零；推栏失败后本地胜场命中仍返回原合法心法和来源，未命中明确为未知；旧 JX3API history 不再影响心法或缓存。缓存命中与推栏成功的武器、队友和近期预热保持原结果；未知心法不阻断身份有效角色同步。构造依赖完整调整，定向回归及 Python 3.9 验证通过，或明确列出环境阻塞与既有失败，不把未跑计为通过。

无数据库结构、索引、迁移、TTL、API 路由、前端、定时频率、外部请求预算和运行配置变更；不需要清库或数据回滚。新增未知角色比例可能升高是预期影响，既有缓存不追溯来源。局部回滚从实施前的文件基线仅逆转本次补丁；不得用 git restore/reset 擦除其他未提交工作。发布与重启需要后续用户明确指令。

## 实施记录（2026-11-25）

T1 基线保存于 /home/songjingjing/.cache/remove-kungfu-jx3api-fallback-20261125/before，原有dirty差异单独保留。测试子agent先验证原实现真实JX3API调用失败，再调整旧契约；主agent完成产品与装配修改。

T2 额外发现 test_jjc_ranking_inspect 的 WarmupJjcRankingService 使用 super().__init__，普通构造AST扫描不足，已同步删除其旧参数；benchmark不再访问已移除依赖。未改变其他测试业务断言。空字符串心法按未知处理，失败结果不写入心法缓存。

T3 初始无Mongo环境导致21错误/12跳过；首次临时动态端口被既有fixture的27029白名单拒绝。随后使用仅127.0.0.1:27029、新独占数据目录和本次自有进程；未复用生产或其他数据库。实施中途测试日志包含签名迁移失败，不作为最终结论。最终final-r2双版各372项全过，临时mongod进程已结束，私有日志保留。

T4 已同步PROJECT_CONTEXT与基线规格；change记录本地完成，未部署。后续需提交或生产发布时另按用户指令处理。
