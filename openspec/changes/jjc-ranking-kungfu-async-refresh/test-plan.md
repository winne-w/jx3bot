# TDD 测试与验收计划（修订版）

状态：2026-11-06，本地实现与隔离验证完成；下方矩阵是验收契约，实际RED/GREEN及未执行边界见文末。旧版67个场景被本矩阵替代，不保留前台等待、control选主、seed平台或装备分母升级测试。

## 方法与职责

按tasks四个闭环逐个小行为执行RED→GREEN→REFACTOR。测试子agent先写需求行为断言，主执行者实现/整合；不得将语法错误、依赖缺失或Mongo未连接当有效RED。每例记录case id、测试方法、版本、RED/GREEN命令/exit code及断言摘要。实现后的独立复核另行开展，不把本次方案评估当代码通过。

policy/classifier使用纯fixture与fake clock；repo单元验证契约，真实隔离Mongo验证唯一性、原子领取、条件写及两个集合之间的失败窗口。HTTP使用mock transport或本地延迟服务，不向真实上游压测。长退避不真实等待分钟/小时。

## 用例矩阵

文件名均省略 `tests/` 前缀；“同上”只指本组主文件。来源于既有行为的用例先作为特征测试固定，不能将计划的新过滤当作旧规则。

| ID | 场景与预期断言 | 主要测试文件 |
|---|---|---|
| A01 | indicator仅items非空的3v3指标按胜场最多选择，保持原平局行为，不用总场最多替代 | test_jjc_kungfu_classifier.py |
| A02 | 最近40条按上游既有顺序取10胜多数；云裳到冰心满足多数条件后改变判定 | 同上 |
| A03 | 十胜平票优先最近出现，候选相同时来源沿用旧行为 | 同上 |
| A04 | 不足十胜按原indicator回退；缺赛季声明不凭空拒绝，明确不同目标则拒绝；不伪造样本赛季证明 | 同上 |
| A05 | 统一周期边界为fresh，超过周期至最大年龄为stale，最大年龄刚超过为unknown | test_jjc_kungfu_policy.py |
| A06 | 跨scope、未来/缺时间、requested_at>verified_at、非法版本或未知映射不可命中 | 同上 |
| A07 | 规范ID来自最终心法，旧辅助ID不覆盖；无需武器/队友即可基础成功 | classifier及policy |
| A08 | 参数非法停用新功能；退避指数有上限；角色预算小于租约并留余量 | policy及runtime |
| I01 | 有条件写只修改jjc_kungfu，不改顶层updated_at/last_seen_at/身份水位 | test_role_identity_jjc_kungfu.py |
| I02 | 身份键升级/查询ID修复及字段回滚保留心法，心法刷新不造成额外身份CAS失配 | 同上及既有身份测试 |
| I03 | 心法刷新不改变同名候选资料排序，不触发画像历史归档；归档不承诺完整心法历史 | 同上 |
| I04 | 榜单ID与名称fallback冲突不复用心法；不同命名空间ID不混用，弱身份合法升级仍可定位 | 同上 |
| I05 | 读取以批量ID/已校验候选获取，不逐人find；不同角色不共享结果 | 同上 |
| I06 | 定位快照变化拒绝结果；身份不存在不upsert，错误schema子对象不被无条件覆盖 | 同上及Mongo |
| Q01 | 同角色并发100次首次登记只有一条任务；_id为身份ObjectId，不按scope多建行 | test_jjc_kungfu_refresh_repo.py及Mongo |
| Q02 | 相同scope重复登记只推进tracking，不重置next_run_at/失败数/generation/token | 同上 |
| Q03 | 迟到榜单不倒退last_seen/active_until，心法缺失也入队 | 同上 |
| Q04 | 两独立连接同时领取同一到期任务仅一个成功，代次递增、token不同 | test_jjc_kungfu_refresh_mongo.py |
| Q05 | 未到期或非活跃任务不领取；到期成功/失败通过同一pending与next_run_at调度 | repo及Mongo |
| Q06 | 正常确认/失败匹配token/代次/scope/租约；过期、错误token、旧代次动作均无效 | repo及Mongo |
| Q07 | running租约到期可回收，next_run_at=now；重新领取更大代次，离榜重新上榜仍保留版本/退避 | repo及Mongo |
| Q08 | scope切换CAS撤销旧token并递增，重复同scope不重置；不允许旧新配置并行回写目标 | repo及Mongo/部署核验 |
| Q09 | 两条调度索引存在、领取/回收explain可用，无TTL/control；索引失败停用新后台而非旧入口 | Mongo及runtime |
| F01 | 写角色成功后才确认任务，不存在任务已确认成功而结果未存的应用顺序 | test_jjc_kungfu_refresh.py及Mongo |
| F02 | 领取后或查询中退出，成功旧值保留，租约过期重新查询并发布 | 同上 |
| F03 | 查询成功但角色写前退出，任务不能被确认成功，下轮重查 | 同上 |
| F04 | 写角色成功、队列确认前退出，新结果可读；恢复重查以更大版本发布并收尾 | 同上 |
| F05 | A(n)迟到时B(n+1)已发布，A结果被拒且A失败/释放不能改变B任务 | Mongo |
| F06 | B已接手尚未发布时允许A(n)通过角色条件写，B成功覆盖；不把该允许窗口测成必须拒绝 | Mongo |
| F07 | 切赛季/算法后更大代次成功，旧scope更小代次不能覆盖；无新成功时旧scope可保存但不能被当前读者采用 | Mongo及policy |
| F08 | 写角色响应未知后重读本代次/scope可确认；无法重读保留running，不猜测成功或清结果 | service及Mongo故障注入 |
| F09 | 领取响应未知不发查询；确认响应未知只做条件重试/读取；Mongo中断不无条件重排或实时兜底 | service及repo |
| F10 | 队列丢失/代次低于角色版本时在线告警不从0恢复；停旧维护才能以角色版本为下限重建；未来数据不可伪装fresh | repo及Mongo/维护流程 |
| H01 | 薄client与旧wrapper共享签名/headers/body，旧wrapper默认超时/重试不变 | test_tuilan_kungfu_client.py |
| H02 | 每角色最多indicator/history两请求，无回放/详情/defget/不完整本地投影兜底 | 同上 |
| H03 | 请求10秒、角色25秒总deadline含所有await/间隔；慢流不绕过预算，取消后不继续下一请求 | 同上 |
| H04 | retries=0不叠加底层重试；本地请求间隔>=2秒，不写全局next_request_at | 同上及runtime |
| H05 | 认证冷却/告警与429有界Retry-After可区分；不宣称进程冷却跨重启持久化 | 同上及service |
| W01 | QQ未登录/离线仍能启动消费；重复本地启动只一个循环，停止幂等 | test_jjc_kungfu_refresh_runtime.py |
| W02 | 成功、失败按统一周期/退避调度，失败不推进成功时间，不修改完整历史同步水位 | test_jjc_kungfu_refresh.py |
| W03 | 退出取消请求并条件收尾，不无条件释放他人token；没有heartbeat/control任务 | runtime及service |
| W04 | 空队列/认证冷却/DB异常退避而不忙循环，异常退出有日志 | 同上 |
| W05 | 只有一个实例启用的部署核验；误启多进程不重复领取同一有效任务，但不声称全局请求速率受控 | Mongo及部署记录 |
| R01 | 1000人热缓存无前台心法外呼/random_sleep/逐人身份find；按批次读取 | test_jjc_ranking_kungfu_cache.py |
| R02 | 1000人全冷也无外呼、队列轮询或补齐等待；可定位者全部登记，未知保留名次/分数/总人数 | 同上 |
| R03 | fresh/stale/unknown各范围守恒，coverage空范围为null；过旧和跨scope不计有效心法 | 同上 |
| R04 | 读取后后台改值不改变本次选定结果，无第二cutoff补齐或重新取已选角色 | 同上 |
| R05 | 无消费者或冷却时统计仍成功；登记失败标degraded但已读有效值保留；读取失败报错 | 同上 |
| R06 | 新开关关闭保留旧参数/入口；历史tag不登记当前任务；后台独开也可从当前榜单预热 | 同上及入口测试 |
| R07 | 未知/身份冲突不按同名合并，不因新心法缺辅助信息触发实时兜底，历史同步职责独立 | 同上 |
| R08 | 新心法/规范ID不会被旧装备或队友字段覆盖，查询失败不导致成功缓存时间变新 | 同上 |
| S01 | summary/details/flat-members保留实际采用值/时间/来源/版本，后台刷新不改历史快照 | 既有ranking_stats_repo/router测试 |
| S02 | 旧快照字段缺失仍可读，显示未记录时效，不默认fresh | 既有frontend/renderer测试 |
| S03 | 装备不完整保持unchecked/unknown或隐藏/标注，不误报false/0%，不引入新分母版本 | 同上 |
| S04 | 两网页入口和QQ实际合并/拆分模板最小覆盖率/未知提示可用，原橙武开关兼容 | frontend/navigation/renderer |

## 发布故障注入的具体边界

F组不能只mock一个“publish成功”接口：应分开角色条件写、队列确认以及读回结果，在每个await边界注入退出/异常。真实Mongo至少证明：A/B领取竞争、B成功后A写失败、允许的A先写窗口、同一_id跨scope代次延续、角色写后未确认时读者仍可用。

F08区分“确定失败未写入”和“写入成功但客户端没收到响应”：后者先使真实写落库，再由测试适配器模拟响应丢失。重读匹配n/S才确认；读取不可用则保留running。Q/F里确认租约使用严格大于now，等于即失效；角色结果发布故意不将队列租约当同集合条件，不错误宣称强保证。

F10的维护重建仅验证明确停旧的受控入口/操作步骤，不新增通用恢复平台；在线路径只拒绝并报告。普通崩溃恢复不要求删除任务或人工恢复。

## 运行命令（本地实施阶段已执行）

在仓库根目录，测试存在后逐组RED/GREEN。下列不要求计划阶段创建测试或安装依赖：

```bash
.venv/bin/python -m unittest tests.test_jjc_kungfu_policy tests.test_jjc_kungfu_classifier tests.test_role_identity_jjc_kungfu
.venv/bin/python -m unittest tests.test_jjc_kungfu_refresh_repo tests.test_jjc_kungfu_refresh
.venv/bin/python -m unittest tests.test_tuilan_kungfu_client tests.test_jjc_kungfu_refresh_runtime
.venv/bin/python -m unittest tests.test_jjc_ranking_kungfu_cache

# 必须显式配置JJC_TEST_MONGO_URI，不允许读取MONGO_URI作为默认值
.venv/bin/python -m unittest tests.test_jjc_kungfu_refresh_mongo

# 既有判定/HTTP/快照/导航/离线采集/历史入口回归
.venv/bin/python -m unittest tests.test_jjc_ranking_history_win_kungfu tests.test_jjc_kungfu_global_id tests.test_jjc_kungfu_meta tests.test_tuilan_request
.venv/bin/python -m unittest tests.test_jjc_ranking_stats_repo tests.test_jjc_ranking_stats_router tests.test_jjc_ranking_stats_frontend tests.test_jjc_data_center_navigation
.venv/bin/python -m unittest tests.test_status_monitor_jobs_offline_statistics tests.test_status_monitor_jobs_admin_notification tests.test_status_monitor_jobs_config tests.test_jjc_peak_score_ranking
.venv/bin/python -m unittest tests.test_jjc_ranking_explicit_tag tests.test_jjc_ranking_command_tag tests.test_jjc_sync_worker_runtime tests.test_jjc_live_refresh_runtime

openspec validate jjc-ranking-kungfu-async-refresh --strict
git diff --check
```

新增身份测试与仓库现有身份恢复/匹配用例一并回归；0.1记录具体模块名，不假定本change修改未提交身份恢复逻辑。记录既有失败与本次新增失败，不用旧失败作为跳过相关回归的理由。

Python3.9兼容用真实3.9解释器检查新增/修改可达路径；不能用更高版本py_compile替代。若环境缺3.9则明确未执行，不能宣称兼容通过。

## 环境与数据隔离

Mongo必须显式测试URI，随机数据库名 `jjc_kungfu_test_<uuid>`，初始化拒绝生产库名/默认生产配置，清理只允许删除该次随机测试数据库。两个进程用独立连接。未配置URI可明确skip，但上线门禁不将skip算通过。HTTP用本地transport/延迟服务及脱敏fixture，日志不记录cookie/token/原始响应。

原plan阶段仅执行文档校验；用户批准后已在显式隔离Mongo与fake/MockTransport执行下述测试，未连接生产或真实推栏。

## 性能、预热与上线观察

冻结1000人榜单，分别测全热/全冷/一半缺失：前台心法外呼均0，无补齐等待；已有身份的读取量随批次数增长，新增身份创建成本单独记录。隔离全热30次，心法解析/本地聚合P50/P95目标P95<=5秒，排除拉榜/渲染/发送，不伪装为整次统计上限。

后台至少一完整轮转记录attempt耗时、成功率、队列深度/最老到期、外呼数、版本拒绝及身份冲突；验证统一6h周期是否有容量支撑，未达标不承诺时效。预热切流初值为全榜有效>=95%、fresh>=90%；真实数据与调参依据写入acceptance，不因达比例掩盖身份错配或版本回退。

部署前列出所有bot/worker实例，确认一个刷新开关开启；停旧后切scope/算法，不靠任务token声称跨进程总限流。QQ离线、当前/历史tag、冷热缓存、旧快照、两网页入口/QQ模板做最小手工回归。故障注入仅隔离环境；生产不压测、不清理任务、不批量伪造验证时间。

回滚先关统计再关后台，原入口恢复；保留角色结果、队列代次与快照，重启后代次延续。线上操作待单独授权。

## 完成标准

矩阵每例有自动或明确手工证据，关键Mongo用例实际执行，所有新功能测试具有有效RED/GREEN记录，相关回归无新增失败。发布恢复保证与允许窗口如实验证，前台无等待，未知不丢名次，心法不污染身份时钟。独立复核问题闭环后才能标实现验收；没有部署证据则上线仍待办。


## 实际执行记录（2026-11-06）

基线HEAD为e97c4886e2f580219f5e4612a46b077e3c190968，原身份恢复/离线统计未提交改动保留。原相关基线156项通过。

| 纵向闭环 | 有效RED | GREEN与实证 |
|---|---|---|
| A/I基础 | policy/classifier模块、publisher接口不存在，行为测试失败 | 第一闭环32项，通过后连旧判定/身份110项；最终同组随完整回归通过。 |
| Q/F仓储 | queue模块不存在；后续真实弱身份定位仍缺失、数组被错误覆盖断言失败 | 并发100次登记、独立连接/真实spawn进程领取、条件发布、恢复/索引真实Mongo通过。 |
| H/W客户端与运行 | client/runtime/service模块不存在；history超时回退断言失败；损坏代次未fatal断言失败 | cancellable HTTP/慢流总deadline、auth/429、运行时生命周期/本地串行、版本完整性停止通过。 |
| R/S排名 | 缺注入字段及resolve能力；真实personInfo无法创建队列；lazy policy/预热/关后台登记新增断言失败 | 冷热1000角色、严格身份、冻结证据、flags/tag、批量登记/降级、快照throughput与端到端通过。 |
| 展示及复评 | 覆盖标签缺失；Node运行purple实际请求次数1!=0；Mongo同anchor总数2!=1 | 页面/九模板提示、未知装备阻断、冷→热/新→旧清理、双入口一致与Chromium视觉通过。 |
| BSON整数 | Int64版本被policy/service当非法 | 标量int/long合法，bool/数组非法；真实Mongo Long代次claim→publish→read为fresh。 |

A01–A08由classifier/policy、client明确scope冲突、refresh canonical ID与budget测试覆盖；I01–I06由role_identity_jjc_kungfu、role_identity_ranking_batch、既有身份回归及真实Mongo覆盖；Q01–Q09/F01–F10由queue_repo/refresh_mongo/refresh/service/integration覆盖；H01–H05/W01–W04由client/runtime/service覆盖；R01–R08/S01–S04由ranking_cache、stats_repo/router、display、frontend/navigation及9项真实Mongo集成覆盖。Q08/W05的真实多实例部署清单核验和F10停旧人工恢复操作没有在生产执行，只验证在线拒绝和隔离竞争；与tasks 5.4保持待办，不标线上通过。

最终在Python3.13.2和真实Python3.9.25分别执行同一组425项测试，均通过、无skip。主组403项，路由组22项单独进程；已有router测试安装仅info的nonebot stub并泄漏sys.modules，合在一个进程会污染live runtime，故按模块边界隔离，不修改无关测试。该环境错误不作为RED或业务缺陷。

可复现主组为本节以上新增12个test模块及原判定、identity_repo/matching、离线统计/admin/config、stats_repo、peak_score、explicit_tag/command_tag、frontend/navigation、live_refresh/sync_worker_runtime/live_refresh_runtime、ranking_identity_recovery。执行方式：

```bash
export JJC_TEST_MONGO_URI=mongodb://127.0.0.1:27029/jjc_kungfu_test
# 先执行前文各组；router单独进程避免存量stub污染。
.venv/bin/python -m unittest tests.test_role_identity_ranking_batch tests.test_jjc_kungfu_refresh_integration tests.test_jjc_kungfu_display
.venv/bin/python -m unittest tests.test_jjc_ranking_stats_router
# 将解释器替换为真实Python3.9隔离依赖环境后重复相同模块。
# 性能脚本显式校验本地测试URI，随机库在finally清理。
.venv/bin/python -m tests.benchmark_jjc_ranking_kungfu_cache
```

最终分组、版本、耗时和性能明细保存在validation-results.json；本机原始日志位于/tmp/jjc-kungfu-Python-3.13.2-{main,router}.log和/tmp/jjc-kungfu-Python-3.9.25-{main,router}.log。性能每场景30轮真实本地Mongo：热P95 672.774ms、冷674.041ms、半缺735.867ms、异scope679.139ms，全部零前台外呼；排除项见acceptance。后台10角色fixture轮转10/10成功，轮后到期0，不将fakeclient速度当生产容量。

Chromium headless实际执行页面函数检查coverage/unknown与purple不完整说明，无pageerror；QQ合图实际渲染并截图检查。截图为本机/tmp/jjc-kungfu-web-qa.png、/tmp/jjc-kungfu-qq-qa.png，未发送真实QQ消息。两个独立实现审核者的发现与修复映射见review.md。

补充F08真实持久化故障注入：在实际publisher写Mongo后模拟响应丢失，同代scope重读可确认；实际写入已成功但readback也不可用时，角色值保留、任务running，90秒后领取下一代恢复。两个新增真实Mongo回归通过；最终完整计数425项（主组403+独立router22），两Python版本一致。编译使用真实3.9解释器；OpenSpec严格校验和git diff --check通过。

## 可维护性优化验证（2026-11-06追加）

身份批量解析保留原行为基线，补充空白game_role_id回退role_id、补全后仍缺请求ID的拒绝分支。前端新增实际Node函数测试先因缺少equipment纯判断而RED，实现后GREEN；覆盖无DOM/输入副作用、旧快照缺flag、分布/过滤/导出一致性及覆盖提示，列表加载/渲染双入口回归保留。

定向108项及身份/展示契约19项通过；最终同一完整模块集在Python3.13.2与真实3.9.25各426项通过、无跳过（主组404，独立router22）。3.13主组7.320秒、router0.121秒；3.9主组8.356秒、router0.158秒。该追加记录替代前节425项的最终计数，先前运行记录保留为历史。两位独立子agent另跑54项数据库/身份与20项前端回归，通过且无新增问题；46,656组新旧定位判断等价。性能未重测，仍以先前隔离实测及其排除范围为准。

## 发布阶段实际查询计划回归

新增真实Mongo测试 `TestRankingIdentityBatchMongo.test_full_ranking_or_uses_indexes_and_preserves_raw_name_fallback`：250人实际resolver产生2243个OR分支，含只能raw名称匹配的legacy；3000背景角色。先RED为SUBPLAN/COLLSCAN；只加(server,name)索引仍RED，global_id裸等值无法使用partial string索引。复用现有类型过滤后GREEN，250 docs/1746 keys、返回250，raw与数组字符串匹配等价、顺序和非unique定义保持。补3万背景诊断证明原问题并非小集合选择偏差；独立审核55项通过。

最新完整回归：Python3.13.2/3.9.25各427项通过（主组405，路由独立22），无skip；最新数组等价及显式类型断言追加运行15项各通过。该记录替代之前426项最终计数，历史执行记录保留。生产Python3.9.9候选359项及路由22项通过；另外5项既有live-refresh/其他页面差异在原生产代码复现，未作为本次通过项。生产planner四批与单人全无COLLSCAN；千人解析/登记单次11.442秒，不代表P95或整次统计耗时。原始证据见发布目录与deployment.md。

发布验证最终记录：生产镜像针对索引修正再跑89项通过，无skip；主组359/路由22和它重叠，不相加。四批真实250人planner与单人均indexed，30文件/配置语义/API/Mongo/QQ/四worker通过；生产浏览器两视口JS0，既有手机19px表单溢出基线同样409px。回滚仅在私有副本演练源码和配置恢复，未停服回滚。初始210成功/918登记、82榜单身份unknown、2条identity_mismatch退避，尚不满足建议预热95%/90%；未改旧快照，按用户启用指令完成开关开启，后续覆盖观察不算已通过。
