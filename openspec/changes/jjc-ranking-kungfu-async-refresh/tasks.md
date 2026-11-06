## Purpose / Big Picture

以TDD实现[修订设计](design.md)：心法归角色画像，独立简单队列持续更新，统计只读本地并登记，条件发布与至少一次恢复保障正确性。用户于2026-11-06确认方案并授权开发，随后授权提交/发布/开启开关；实现、独立复核及生产发布完成，首轮预热与后续快照验收继续按实际覆盖观察。

## Progress
- [x] 7.1 RED：混合缓存/缺失、后台关闭、无安全身份、单人失败继续及共享client并发测试先失败；真实Mongo补按角色领取与旧token fencing。
- [x] 7.2 GREEN：统计按排名直接查询缺失，结果写回角色，查询/发布复用后台实现；前后台共享串行client；覆盖发布成功但确认失败恢复。
- [x] 7.3 回归：双Python、真实Mongo、冷热集成与独立subagent实现审核，修复问题并同步当前规格。
- [x] 7.4 发布：仅本次运行文件增量备份发布，保留线上其他改动与两开关；验证实际冷角色直接成功/二次命中，记录回滚和健康证据。


### 0. 基线与契约

- [x] 0.1 主执行者记录HEAD及已有身份恢复/离线统计改动，核验现有相关测试基线、实际渲染模板与入口；准备隔离Mongo和可控时钟，不覆盖既有修改。
- [x] 0.2 测试子agent先建立脱敏indicator/history/榜单fixtures，固定原基础判定、身份ID匹配、响应错误结构；主执行者核对单消费者部署前提、共享请求构造边界和repo契约。此阶段不先行实现业务代码。

### 1. RED → GREEN → REFACTOR：角色心法与基础规则

- [x] 1.1 RED：测试子agent新增 `test_jjc_kungfu_policy.py`、`test_jjc_kungfu_classifier.py`、`test_role_identity_jjc_kungfu.py`，先覆盖test-plan的A/I组，记录因缺少需求能力导致的失败；不以环境或语法错误充当RED。
- [x] 1.2 GREEN：主执行者在 `role_identity_repo.py` 增加批量心法读取与窄条件发布接口，新建 `src/services/jx3/jjc_kungfu_policy.py`；从kungfu.py提取共享纯判定并接回旧路径，保持十胜多数、平票、indicator回退行为，不新增严格赛季证据过滤。
- [x] 1.3 REFACTOR：统一规范心法ID与时效返回模型，心法不更新身份顶层时间；验证身份升级/ID回滚/画像归档边界及旧判定回归，保持Python3.9兼容。

### 2. RED → GREEN → REFACTOR：独立队列与两步发布

- [x] 2.1 RED：测试子agent新增 `test_jjc_kungfu_refresh_repo.py`、`test_jjc_kungfu_refresh_mongo.py`，覆盖Q/F组；先以真实隔离Mongo证明重复登记、领取竞争、写角色后未确认、迟到发布与scope切换预期失败。
- [x] 2.2 GREEN：主执行者新增 `src/storage/mongo_repos/jjc_kungfu_refresh_repo.py`，实现每角色长期任务、批量登记、原子领取、token条件确认、过期回收、scope条件切换和generation完整性检查；在 `src/infra/mongo.py` 只增加设计中的两条调度索引，不创建旧refresh_state/control集合。
- [x] 2.3 GREEN：新增 `src/services/jx3/jjc_kungfu_refresh.py` 的发布编排：固定定位快照、先条件写角色后确认、写入结果未知时重读、已知失败保留结果、DB不可用停止本轮；所有队列收尾使用token/代次/scope/租约守卫，不引入事务或角色执行租约镜像。
- [x] 2.4 REFACTOR：以独立连接/进程跑真实Mongo的Q/F组，验证角色级版本跨赛季不归零、任务误删不在线归零重建及确认失败可重复执行；检查领取/回收explain，提取共享条件但不扩展为通用队列平台。

### 3. RED → GREEN → REFACTOR：后台查询与运行

- [x] 3.1 RED：测试子agent新增 `test_tuilan_kungfu_client.py`、`test_jjc_kungfu_refresh.py`、`test_jjc_kungfu_refresh_runtime.py`，覆盖H/W组，先断言取消、退避、认证/429冷却、QQ离线与启停契约。
- [x] 3.2 GREEN：主执行者新增薄 `src/infra/tuilan_kungfu_client.py`，复用 `HttpClient(retries=0).arequest_json()`；只将必要签名/headers/body构造提为共享小函数，保持旧同步wrapper行为。添加请求/角色总deadline、本地请求间隔，基础刷新仅indicator/history。
- [x] 3.3 GREEN：完善刷新service，新增 `jjc_kungfu_refresh_runtime.py`，在singletons仅装配对象；bot.py挂接Mongo之后的启动/关闭，config.py增加两开关及三项时效参数；一个串行消费者和任务租约，无leader/control/heartbeat循环。
- [x] 3.4 REFACTOR：fake clock覆盖退避/追踪期，用本地延迟HTTP验证真实取消及无后续外呼；重复启动仅一个本地循环，故障退出可见且旧token不能释放新任务；回归既有HTTP/sync/live runtime。

### 4. RED → GREEN → REFACTOR：排名与冻结快照

- [x] 4.1 RED：测试子agent新增 `test_jjc_ranking_kungfu_cache.py` 并补现有快照/入口/展示测试，覆盖R/S组：冷热均零前台心法外呼、无等待、缺失保留名次、历史tag不登记、已有值不被旧辅助覆盖。
- [x] 4.2 GREEN：主执行者为RoleIdentityRepo增加严格批量榜单解析，在 `JjcRankingService` 接入批量读取、选择冻结及幂等登记，自动/default手动走相同开关；仅后台开启也可在当前榜单成功获取后预热登记。新路径不得逐人调用get_user_kungfu/random_sleep/实时兜底，不影响原完整同步水位。
- [x] 4.3 GREEN：最小修改 `jjc_ranking_stats_repo.py` 透传与排名payload，新增覆盖率/时效；renderer、实际使用的合并/拆分模板及 `public/index.html`、`public/jjc-ranking-stats.html` 只做未知和覆盖提示，辅助不完整标注或隐藏，不做新装备分母版本。
- [x] 4.4 REFACTOR：跑相关入口、快照、身份、网页导航和渲染回归，批量查询规模随批次数增长；验证后台变化不改旧快照、旧字段缺失不误判fresh，两网页入口一致。

### 5. 验证、文档与后续上线

- [x] 5.1 主执行者将数据库文档“待实施”说明更新为实际生效定义，同步PROJECT_CONTEXT、README/README-Docker、runbook中的职责、配置、单消费者约束、暂停/冷却、版本恢复和回滚；不写成已达到时效或性能。
- [x] 5.2 在隔离环境完成所有适用回归、Python3.9兼容、真实Mongo竞争及故障窗口、1000人冷热性能和一轮后台轮转；逐项记录RED/GREEN命令、版本与结果，未执行/跳过不算通过。
- [x] 5.3 独立子agent复核最终设计/实现/测试的衔接、发布失败窗口与首版范围，主执行者处理问题并更新review.md；不因这次设计评估就预填实现通过。
- [x] 5.4 用户授权后核对唯一写入实例并发布：双开关关闭首启→单消费者真实预热→修复并核验生产查询计划→双开关1切流→恢复同步；完成源码/配置回滚离线演练。初始有效率未达到建议95%/90%门槛，依本次启用指令保留冷启动unknown，记录实测且不宣称生产时效达标。
- [ ] 5.5 真实验收后同步OpenSpec基线、归档change并更新索引；保留队列代次和快照，记录未覆盖限制。

### 6. 已批准的可维护性优化（2026-11-06）

- [x] 6.1 保留版本/类型/空unknown协议：在role_identity_repo.py提取缺查询定位判定及补全结果验证，沿用既有安全upsert；先跑身份批量/真实Mongo行为基线，重构后确认完整热路径仍无逐人upsert。
- [x] 6.2 public双入口统一equipment_incomplete纯判断，分布图、紫武过滤、列表和导出共同复用；拆开判断与提示DOM写入，保留加载前/渲染前保护；补Node实际入口一致性及无副作用测试。
- [x] 6.3 回归真实Mongo、页面导航、快照、客户端/runtime及Python3.9可达路径，独立子agent只读复核两项重构；同步design/test-plan/review/acceptance，保留部署/归档待办。

### 7. 已授权生产发布与查询计划补齐（2026-11-06）

- [x] 7.1 提交并推送本次功能，按生产基线合并运行文件，保留既有独立修改；生产镜像离线回归与基线差异对照、备份及暂停同步后发布。
- [x] 7.2 真实Mongo先RED覆盖实际250人OR查询的winning plan，再由infra.mongo统一补普通(server,name)索引、global_id复用既有类型过滤；独立复核、双Python回归、生产queryPlanner确认无COLLSCAN后重测登记耗时。
- [x] 7.3 启用唯一后台消费者预热，验证真实成功发布/失败退避；启用缓存统计、恢复同步原状态，核对API/网页/文件哈希和日志，记录初始覆盖及未执行项，不主动改旧快照或发测试消息。

## Surprises & Discoveries

原计划将结果/任务同文档以换取原子提交，但用户要求心法归角色画像，三个独立评估也认可；因此需要明确至少一次与角色侧条件发布，而非保留旧MUST再引入事务。现有异步HttpClient可直接复用。身份顶层updated_at参与CAS及候选排序，心法不能改它。当前新旧scope同时写入不在首版支持范围。

## Decision Log

2026-11-06修订：一角色长期队列、角色级generation跨scope延续；先写角色后确认，允许重复查询；删除前台等待、control/双心跳、hash/同义unique、差异周期/防饥饿、seed平台、装备统计新版本。scope用于缓存复用，不额外增加缺上游赛季字段即未知的过滤。详细失败矩阵以design第5节为准。

## Outcomes & Retrospective

本地实现及独立复核完成，Python3.13.2/3.9.25各427项相关测试通过、无跳过。初版5项P2与发布阶段完整OR扫描问题均闭环；9071c9a/987429e已推送并在生产合并部署，两开关为1。30文件、API/Mongo/QQ/四worker及浏览器核验通过，后台真实成功值持续增加。初始覆盖不等于预热完成；后续快照覆盖率验收与归档保留5.5。

## Context and Orientation

仓库为WSL `/home/songjingjing/codes/jx3bot`，change为 `openspec/changes/jjc-ranking-kungfu-async-refresh/`。先读AGENTS/PROJECT_CONTEXT/docs/PLANS和本目录design/specs/test-plan；现有身份恢复和离线统计有无关未提交改动。首版只维护当前3v3；所有时间UTC，赛季起点从北京时间配置转换。数据库当前事实与待实施提案必须区分。

## Plan of Work

按四个纵向闭环推进，不先写全部测试再一次性实现：每组小行为先RED，再最小GREEN，最后重构并跑相关回归。测试子agent在固定输入输出契约后先写测试，主执行者实现和整合；测试与实现不同时写同一文件。允许classifier与repo测试准备并行，但依赖协议先定，Mongo/HTTP隔离先可用。用户批准后已分配测试、仓储和client/service子agent，主执行者负责整合。

## Concrete Steps

实施时从仓库根目录执行test-plan命令，先记录基线，再按A/I→Q/F→H/W→R/S运行。每次记录用例ID、真实测试方法、失败原因、RED/GREEN退出码和版本。先验证单元契约，再以真实隔离Mongo证明原子领取/条件写；不以mock代替跨集合窗口。长时间退避使用fake clock，HTTP失败用本地transport/延迟服务器，不请求生产上游。

变更范围固定为上述文件和最小展示入口；不创建旧 `jjc_kungfu_refresh_state`，不新增管理平台或通用调度抽象。实际模板路径在0.1枚举并记录。repo新增方法、service编排、client适配保持层次；singletons不承载业务。

## Validation and Acceptance

验收标准：冷热统计心法外呼0、无前台补齐等待；所有可定位榜单角色幂等登记；未知人数守恒；角色心法写不改身份时钟；失败和确认中断不丢成功值；旧结果不覆盖新成功值；真实Mongo覆盖全部关键失败窗口；旧入口/快照/完整历史同步无新增回归。

隔离1000人热路径30次P95目标<=5秒，仅心法解析与本地聚合。性能及覆盖需实测，不按任务数量判断完成；上线时至少一轮预热及实例核验，建议有效>=95%、fresh>=90%。精确用例、运行命令与未执行标记见test-plan；实际结果再填review/acceptance。计划校验仅证明文档结构，不证明业务通过。

## Implementation Log

2026-11-06：用户批准开发及实现后独立子agent复核。基线HEAD `e97c4886e2f580219f5e4612a46b077e3c190968`，既有未提交改动保留，基线diff保存于本机临时目录。基础回归156项通过（原判定/身份/HTTP/快照/离线统计），日志 `/tmp/jjc-kungfu-baseline-tests.log`。开发按文件分工：测试子agent先行A/I组；队列子agent先行Q/F与repo；client子agent先行H/W与适配器/runtime；主执行者负责基础实现、发布编排、排名/展示和整合。

2026-11-06整合：展示新增3项RED→GREEN，联合网页导航/前端18项通过；真实Mongo端到端4项通过（冷→热→云裳转冰心→快照冻结、超时退避、取消回收、发布后确认前退出），并验证不改身份时钟/完整历史水位。端到端发现personInfo接口不一致，新增有效RED后修复规范化。独立实现review开始；发现队列代次基础损坏时消费者应停止而非在线追代，修复验证中。Python3.9.25隔离依赖环境已建立于本机临时目录，等待完整相关验证。

2026-11-06最终验证：Python3.13.2与Python3.9.25各425项通过（主组403+独立进程router22），均无跳过；router测试的存量nonebot模块stub会污染同进程runtime测试，因此按模块边界隔离执行，未改无关测试。新增十角色隔离后台轮转10/10成功，到期积压0；真实BSON Int64代次经claim/发布/读取可用。Node实际执行紫武列表分支与Chromium页面/QQ合图视觉检查通过，JS错误0。真实Mongo千人×30次：热P95 672.774ms、冷674.041ms、半缺735.867ms、异scope679.139ms，上游调用均0；排除拉榜/完整历史同步/渲染发送，测试库仅1000角色。复现benchmark已纳入tests/benchmark_jjc_ranking_kungfu_cache.py。完整记录见test-plan/review/acceptance及validation-results.json。review两位独立agent只读通过，5项P2（代次损坏、弱身份补定位、数组schema、unknown残留、紫武列表）已闭环；删除未用参数并统一Int64整数口径，未加事务/control/心跳。未提交、部署或归档。

2026-11-06追加：用户确认可维护性优化方案并授权继续。范围只含弱身份补全小函数和前端装备完整性纯判断，保留现有代次损坏停止、Mongo原子类型约束、空unknown覆盖及双入口防护；不新增隔离状态/自动修代次/快照版本系统。当前源码快照存本机/tmp/jjc-kungfu-followup-before.json供独立复核。

2026-11-06可维护性优化完成：身份定位补全提取两个纯helper，两个网页入口统一装备完整性纯判断并拆开DOM提示。新增Node行为测试先RED（缺少纯判断能力）后GREEN；已有身份测试补充空白ID回退和补全不完整场景。定向108项通过，完整Python3.13.2/3.9.25各426项（主组404+独立router22）通过、无跳过。implementation_review独立54项真实Mongo/身份测试通过，并比较46,656组定位判定全部等价；ranking_review独立20项页面测试通过，均无新增问题。未改变数据库结构、发布协议或功能开关；未重新测性能，沿用前次实测并保留其适用范围。

2026-11-06发布进行中：用户授权提交/发布/打开开关，9071c9a已推送；生产30运行文件已合并发布，首启双开关关闭、API/Mongo/QQ恢复。生产镜像364项初跑中5项失败已在未修改生产基线上复现，属于既有live-refresh/其他页面差异；其余359项及独立router22项通过。生产首次登记遇146429角色库COLLSCAN：OR中的raw(server,name)分支无索引，已登记918任务但再次解析使独立预热总170秒超时，已终止该producer。只补必要非unique索引，不改变legacy匹配集合；后台可消费已登记任务，缓存统计暂关。

发布阻塞修复闭环：单加raw索引仍RED，完整OR的global_id裸等值不能使用现有partial string索引；复用既有_global_id_string_filter后GREEN，保留数组字符串与raw legacy匹配。独立55项通过，无新增阻断；主执行者Python3.13.2/3.9.25各427项（405+router22）通过，追加最新测试15项各通过，均无跳过。生产候选实际千人解析/登记11441.916ms（单次非P95），4个250人批次及单人winningPlan均IXSCAN/OR/FETCH/SUBPLAN，无COLLSCAN；1000人中918可定位，106已有成功值，其余持续后台刷新，不主动改历史快照。

2026-11-06生产发布完成：代码提交9071c9a、查询修正987429e已推送；17:35:32北京时间最终重启，双开关1实际加载。30运行文件哈希一致，其他生产配置语义不变，API HTTP200/status0、Mongo正常、QQ重连、四完整同步worker恢复；无Traceback/插件失败/消费者退出，RestartCount0。观测检查点已有210成功值、918长期任务、2条identity_mismatch退避、发布代次违规0。仅安全确认918/1000角色，82不强配而保留unknown；未主动重算快照/发测试消息。单消费者继续预热，离线回滚演练通过，未实际停服回滚；生产建议覆盖门槛尚未达到，不宣称生产SLA。证据见deployment-results.json，5.5待后续快照验收。

## 2026-11-06 21点故障修订（当前有效约定）

用户明确要求：逐个判断心法，已有可用缓存直接复用；没有可用缓存，本次统计必须直接等待查询，不能只登记异步任务后保存未知。此约定替代下文历史记录中的“冷热均无外呼、冷榜只保存unknown”。21点实际快照为663已知、337未知（254 missing、83 identity_unresolved），不是上游整体失败；紫武页因装备资料不完整隐藏列表是独立行为。

统计先批量读取角色画像，固定命中的本次采用值，仅为这些已有值批量登记周期刷新。随后按榜单顺序逐个直接查询缺失、过旧、跨scope或非法映射角色，无前10人或30秒总预算。安全身份走共享心法service的query_now，成功后写role_identities.jjc_kungfu并立即计入本轮；无安全身份走榜单定位的旧直接查询入口，不向冲突角色发布。真实查询失败保留未知并继续后续角色，不把旧对局缓存伪装新鲜查询。

直接查询复用长期队列的generation/token做发布记账：register后按角色_id原子claim_identity，忽略调度/退避时间并递增代次、换token，撤销旧后台尝试的执行权，然后当前调用直接执行共享查询/分类/条件发布。它不是等待后台消费。角色成功先持久化，再确认任务并安排下次刷新；确认异常时读回同代次/scope确认成功值，当前统计仍可使用，任务交租约恢复。版本预留失败、身份变化或上游失败均不得绕过条件发布。前后台使用同一个异步client和串行锁，保持请求间隔与每次查询预算；401/429冷却仍生效。未新增集合、字段、控制文档或第二套worker。

冷榜统计耗时随真实缺失数增长，不再承诺冷热同速。全热路径仍批量读取且零心法外呼。快照仍冻结本次采用值，后续后台不得回写历史快照。装备完整性检查保留，不把未知装备算为紫武。

2026-11-06 21点修复已发布93e9371。实际缺失角色已证client外呼，真实上游失败仍保留unknown；进程内60秒policy验证expired→直接查询/保存/本次采用→第二次零外呼成功。生产107候选通过，两开关1且配置字节不变；QQ/Mongo/完整同步正常，见deployment与cache-miss-validation。
