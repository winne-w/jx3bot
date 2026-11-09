# TDD 操作计划：JJC 角色查询 ID 最小修复

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

版本：2026-10-20，精简方案后的执行计划。状态：G1-G8完成，两次受控重启及开启恢复已执行；三故障角色和一健康对照完成外部验收，观察超过21分钟。全量覆盖、修复角色特定历史/排名写入回退演练仍未闭环，G9-G10不全勾、不归档。命令与未勾选步骤不代表已执行。

## Purpose / Big Picture

修复转服后的“新服务器/名字 + 旧查询 ID”，覆盖所有本地身份的线索及可验证角色的存量恢复。按 Red -> Green -> Refactor，由子 agent 测试和开发、独立子 agent review、主 agent 集成验证、commit、发布重启和线上验收。不承诺缺证据者自动恢复。

用户已确认排查、精简方案和本详细计划，并明确要求继续。现按门禁顺序实施；commit/生产写入/发布/重启必须等待对应前置验证通过。需要新对象/字段、扩大业务范围、额外停机或出现生产冲突时暂停重新确认。

本计划额外明确供审核的发布控制：唯一配置JJC_ROLE_IDENTITY_RECOVERY_ENABLED默认0，第一次部署重启保持关闭；CLI试点通过后开启，第二次重启加载并验证自动恢复。它不增加Mongo业务字段/领域对象。G0须批准这两次容器重启及该配置修改，不能以同步pause冒充已隔离公开/排名自动写入。

## Progress

- [x] 核实原始 ID 来源、历史转服记录与真实输入的合并复现。
- [x] 对抗审查撤回新增对象、恢复集合、worker 建议。
- [x] 用户确认排查/精简方案，要求 TDD 完整操作计划。
- [x] 同步收敛 proposal/design/spec/test-plan/review/acceptance。
- [x] G0：2026-10-20用户明确确认方案并要求继续，批准既定开发、commit、发布及两次bot容器重启。
- [x] G1：冻结工作区、测试基线、写入口和子 agent 文件归属；本地Mongo7.0.28仅127.0.0.1:27029，真实Python3.9.25已准备。
- [x] G2：测试子 agent 完成可解释 Red，主 agent 复现；原规则30/服务171/路由38/快照50基线通过。
- [x] G3：开发子 agent 最小Green，独立review反例均补Red/Green闭环。
- [x] G4：主agent独立核心/CLI83及服务222在3.13/真实3.9各自全绿，真实隔离Mongo/回滚和相关回归通过，无skip。
- [x] G5：独立非实现作者子agent静态review，九项P2根因复审关闭，无未闭环P0/P1/P2，见review.md。
- [x] G6：release commit acc63576dc77，11文件精确delta叠加生产基线，制品/备份校验和真实3.9组合验证完成；存量失败独立复审通过。
- [x] 发布中projection性能反例补TDD/独立review，提交ef2d723fd9c7；最终overlay核心84/服务222/快照50及装配通过。
- [x] G7部分：首发acc635/off备份与一次受控重启成功，runtime config原字节保持，原global pause保持。
- [x] 历史生产异常处置：暂停并确认自有inventory退出；恢复后用户重新授权继续，原全量路径仍禁用。
- [x] G7：生产基线/备份/同步静默通过；两次受控stop/start完成，最终11文件hash一致，唯一开关1已加载。
- [x] G8：小耶猫试点/API/两终端页面通过，盖伊伊CLI后公网通过，颜魉未手工apply在线自动恢复及两终端通过，苍术健康对照通过；颜魉不唯一归因页面。
- [x] 四身份有界manifest/备份/逐条回读、同run 68/100额度及21分钟观察完成；用户主动恢复同步，保持其选择不擅自pause。
- [ ] G9剩余：全量覆盖未知，原inventory内存风险未解决；修复角色特定历史投影/排名入口的线上回退演练尚未覆盖。
- [ ] G10：本轮受限验收证据和未解决清单完成，最终独立文档复核已通过，证据单独提交，仍保持change active，不宣称全量验收归档。

## Surprises & Discoveries

三例旧 ID 有合法历史来源，不是另一套 replay ID。空 ID 详情更新 server/name 和整体水位，不能说明 ID 也被观察。正确 indicator 与同场补齐均被现有规则拒绝。不能仅补 replay、按 source 强写、把 > 改成 >=、只按 _id 刷新，或只保 ID而允许服务器回退。

旧盘点 140028 身份、16825 indicator、1104 ID 差异不是实时总数，且最新单一证据会漏候选；不能作完整故障名单或修复分母。三个转服样本独立数字映射已核实，另三个样本只证明候选 indicator 成功，不自动获得完整修复证据。

本地 .venv 是 Python3.13.2，生产 Dockerfile 为3.9，当前未发现独立 python3.9。发布前补真实3.9验证，不能以3.13 py_compile替代。Docker CLI 可见不代表 daemon/测试镜像可用，G1实测，不在本轮启动测试基础设施。

## Decision Log

2026-10-20 21:21本轮线上收尾：最终release ef2d723的11文件hash全部通过，第二次StartedAt=12:59:40.261225102Z，RestartCount=0，开关1/live-refresh0。小耶猫与盖伊伊CLI分别通过新鲜indicator+独立replay、不可变私有before-image及ID-only CAS，随后公网force为HTTP200/业务0/raw0且hit=false。颜魉未手工apply：采集时旧ID44421059，后回读31755654、新strict标记、关联旧CAS归档、缓存raw及两终端页面均通过；同期sync运行，不能唯一归因页面请求。苍术ID保持34750178。四身份结果为2 CLI外部验收recovered+1在线自动recovered+1healthy=4；CLI原applied_unverified不手工改写，以单独外部验收记录证明。原同run预算68/100（含保守API预留，不涵盖后台/公众自然流量）。13:21:00Z已运行1280.4秒，最近15分钟1746日志行未触发3000行上限，未见traceback/Mongo超时/调度miss/恢复或身份投影失败/接口5xx/真实鉴权失败；457条详情身份投影完成日志不是457个去重match，也不证明三个修复角色特定投影或排名入口已覆盖。NapCat502仍为存量告警。详见acceptance.md，完整敏感证据留私有操作目录。

2026-10-20用户明确说明paused=false为其主动操作、非发布异常，并要求继续；不再恢复旧pause，不擅自干预已运行同步。后续精确点查/备份及CAS按当前身份复核，允许正常更新时间/画像水位推进，不将其直接认定串号。全量inventory仍禁用，不为收集验收证据暂停用户同步或额外重启。


2026-10-20 20:17恢复执行：用户说明刚才网络异常、现已恢复，明确要求继续原安排。按既定试点apply/API/真实页面/第二次启用重启门禁继续，不将之前超时定性为程序故障；同时避免已确认的全量驻内存风险，不重跑inventory。复核host load0.03、MemAvailable约1.2GB、无旧inventory、首次StartedAt未变、运行开关0/global paused=true、原账本6/100、无manifest/run绑定。临时四身份manifest仅精确_id和三个已知match_id、窄字段、显式索引/limit2/maxTime、64KiB单文档/512KiB输出门禁及维护进程自身内存/时间限制，保留默认运行机制与release不变。临时运维脚本仍测试先行、主agent复现Red/Green、独立子agentreview，不把分页limit当全部负载保证；不新增领域对象/集合/worker。

2026-10-20 19:39稳定复核：全部自有inventory进程为空，manifest仍不存在；零字节临时文件mtime为11:24:32.790429Z，属于本轮，作为可能到达首次JSON写入前阶段线索保留。1分钟load已从20.37降为0.16，MemAvailable约1.2GB；容器StartedAt/RestartCount不变。第三次公网Mongohealth仍200/业务0，耗时0.184秒。19:34以来所取日志无新增Mongo超时/调度miss，仅既有NapCat502；这不是全链路健康或角色恢复验收。继续保持paused/off，不推进恢复。

2026-10-20 19:24-19:32生产可用性异常：第二次只读inventory期间公网Mongo health超时、SSH超时，调度日志出现miss/Mongo timeout。立即暂停verify/apply、第二次重启和启用；没有角色ID修复写入。原自有SSH guarded-stop无回执，不能将其记成已成功SIGTERM；约19:32重新连接后严格检查host PID9217已不存在，盘点无manifest，stdout/stderr空，仅零字节临时文件。不能确定退出原因；只记录与盘点并发的资源压力风险，不认定OOM。19:33容器running、OOMKilled=false、StartedAt仍10:24:05Z、RestartCount=0，host MemAvailable约1.2GB；19:34内核可读取日志未找到对应OOM条目，首发11文件和runtime config原hash一致。19:35运行开关0、Mongo ping成功、原paused=true；公网health已连续两次200且业务status_code=0。原run预算仍6/100，无run绑定/角色apply记录，第二次重启未发生。

新增容量门禁：两处projection只证明传输减少，不能证明全流程内存有界。inventory仍保留所有身份/候选，再一次性BSON-aware JSON编码与读回hash；Mongo batch_size不限制这些内存。本轮禁止重跑全量inventory，不以--name/--limit误认为缩小盘点（该分支忽略两者）。独立review要求先健康观察与证据保存，再向用户确认缩为3故障+1对照的明确有界只读点查；必须是精确_id/稳定ID/缓存键/已知match_id及必要字段，不能把limit当索引扫描或字节上限。进程资源保护只约束维护进程，不调整共享bot容器限额。四样本证据先审阅，apply/第二次启用重启重新过确认门禁。全量覆盖需以后单独证明分页、字节及逐批释放有界；不新增领域对象、集合、worker或预算平台。本修订尚未执行/获批，既有pause/off和预算保持。

2026-10-20发布中性能反例：原CLI下载完整rank成员和replay payload，完整历史rank扫描约30分钟，回放300份约20秒。核验PID后仅SIGTERM自有只读inventory（未生成manifest、零上游、零业务写），未停止bot、未重置run预算。service_tdd补真实Mongo CommandListener/wire payload行为Red，主agent复现1测试4失败；仅两处nested投影最小Green，保留dict/list replay、既有候选/顺序/match_id/计数/截断语义。独立review通过，补充commit ef2d723fd9c7297794a968d0461b671ad4b88ab5；双Python核心84、服务222，最终实际overlay核心84/服务222/快照50/装配通过，相关38仍35通过3相同存量失败。

最终tar SHA256 45f66bc40cf7dedfa6c938b55475e552c2cac2cc603e6b47de8d594c00ac35e9。仅CLI与first release不同，10个依赖hash一致。维护CLI从私有/tmp/jjc-role-maintenance-ef2d723fd9c7/scripts运行，cwd/PYTHONPATH=/app，目录只含CLI以免遮蔽配置/源码；bot仍acc635/off，第二次统一最终11文件和开启尚未执行。新CLI曾重跑同一inventory/run，已有6次账本保留；显式replay上限收紧为20000以减I/O，保留截断未知，不代表201万详情全覆盖或内存安全。异常前曾拟议6个已知样本在run绑定前复用已有索引候选读取补定位、保留原manifest、另pin操作manifest及原hash；目前该拟议路径暂停、未执行，不构成当前授权，也不绕过独立实时校验或鉴权stop。

2026-10-20 18:24首次发布：159个生产基线hash复核无变化，11文件备份和staging制品hash通过；release acc63576dc77，tar SHA256 ef17791a1c9cd860226e444549ea39b84d553c17990f181eef2c8258d0b5d7c1。第一次受控stop/start的StartedAt为2026-10-20T10:24:05.558228336Z，应用18:24:34启动完成，Mongo/公网health通过，开关0。生产原已因历史鉴权失败暂停，active角色/详情均0，本次不擅自resume；只读预检replay成功。本次调用已有status CLI触发了其既有索引初始化，不能将该步骤称纯只读。

2026-10-20生产组合验证：实际overlay在真实3.9/隔离Mongo核心83、服务222、快照50及singletons装配通过。补齐生产public后routes/indicator/navigation/live 38项中35通过，3项baseline与overlay完全相同的存量失败（两个静态布局契约及live-refresh首屏未合并）；不声称组合全绿，不夹带无关修复。独立review确认11文件差异与依赖兼容，没有新增P0/P1/P2阻断。

2026-10-20实施收敛：CLI不写战绩缓存，保存关联缓存before-image，ID成功后先标applied_unverified，由公开API验收写真实成功缓存；因此CLI数据回滚不删除后来的合法缓存。为避免跨子命令批次账本复杂化，将同run有效调用上限保守收紧为100（低于批准120），包含verify/apply/API预留；20只是每命令角色上限。resume用同run本地progress.json跳过各命令已处理终态，prepared崩溃项仍先回读；显式名字可重验。

2026-10-20证据覆盖：inventory保留全部缓存/历史/排名不同locator；额外replay采用显式--replay-scan-limit流式有界扫描并报告截断。页面候选仍仅有限索引命中，不能当全量库存。ranking复用原响应必要依赖为kungfu.py仅加真实请求开始时间到已有临时warmup，不新增Mongo字段。

2026-10-20生产基线：已只读捕获159个相关文件及manifest，未生产写入；主要身份模块逻辑与本地基线相同（部分CRLF不同），config另有未使用helper，http_client/live_refresh存在未发布依赖差异。发布制品将从已审commit的精确delta叠加生产副本，保留这些线上差异，再运行真实3.9/隔离Mongo组合验证；不能直接整份覆盖本地config删除线上helper。

2026-10-20实施启动：T1/storage_tdd负责仓储测试，T2/service_tdd负责服务测试，各自完成Red后才授权Green。为避免服务子agent同时承担CLI过载，CLI测试与实现由主agent承担，仍测试先行并交独立子agent审查；主agent独占共享文档和生产操作。无关dirty与起始HEAD复核未变。

2026-10-20：复用 role_id/game_role_id、既有历史集合和观测字段，不新建对象/字段/集合/worker/页面轮询/预算平台。必要共享模块只包含小函数，无恢复服务类或实例。严格校验、CAS、组合防回退缺一不可。

2026-10-20：计划审批前只写文档。主 agent 独占 commit和生产操作；子 agent开发需有文件归属，review只读。不得夹带或撤销原有无关改动，不能因格式校验通过声称业务验证完成。

## Outcomes & Retrospective

代码TDD/独立review、两次代码commit、两次生产受控重启及机制启用完成。三已知故障角色恢复并有公网外部证据，一健康对照未受损；21分钟观察覆盖正常详情流水线，未见本次相关新错误。用户主动resume同步，未修改其选择。首次网络/健康超时根因未证明，不认定OOM；原全量inventory保留驻内存风险，禁止再执行。

本轮交付的是已上线机制及四身份受限验收，不是全部用户已修复。所有角色的影响/候选覆盖未知，缺证据或严格观测后再次转服等情况仍保守unresolved；未为验收制造目标角色历史/排名写入。全量盘点需要另行完成字节/分页/逐批释放有界方案及TDD/review，才能关闭G9并归档；未将容量修订偷换为新增对象/worker。完整证据与样本计数见acceptance.md。

## Context and Orientation

开发仓库 /home/songjingjing/codes/jx3bot；起始HEAD c8156708c8f9a24c2273ecac328a314524b120c2，实施前重记。无关dirty包括 docs/superpowers 下删除、.playwright-mcp/、CODE_REVIEW_REPORT.md。禁止git add .、reset --hard、checkout --、amend和清理无关文件。

生产通过WSL ~/.bashrc的aliyun alias访问。已知容器jx3bot，/app绑定/mnt/sata6-1/jx3bot，发布前重核。只读必要状态，不打印key、ticket、完整Config.Env或Mongo URI；不默认远端Git干净/存在，或独立worker均已停。

### 文件和责任边界

| 文件 | 计划内容 | 负责者 |
| --- | --- | --- |
| src/services/jx3/role_identity_matching.py | 纯验证规则和查询组合冲突判断 | D1开发 |
| src/storage/mongo_repos/role_identity_repo.py | ID-only CAS、归档、既有标记、保护与投影 | D1开发 |
| src/services/jx3/role_identity_recovery.py（必要时新增） | 函数级共享候选/有限验证编排，无新类 | D2开发 |
| src/services/jx3/jjc_cache_repo.py | 窄转发、分开成功响应与兜底缓存权限 | D2开发 |
| src/services/jx3/jjc_ranking.py | 原始成功indicator/replay复用 | D2开发 |
| src/services/jx3/jjc_ranking_inspect.py | 页面失败有界兜底、合并/冷却/缓存 | D2开发 |
| src/services/jx3/jjc_match_data_sync.py | 既有刷新走安全边界、TTL/快照兼容 | D2开发 |
| src/storage/mongo_repos/jjc_sync_repo.py | 仅G1证实受保护字段旁路时局部收口 | D1或D2单一owner |
| scripts/recover_jjc_role_identities.py（新增） | 默认只读CLI、备份、更新/回读/继续/回滚 | D2开发 |
| config.py、runtime_config.example.json | 唯一默认关闭启用项及既有runtime白名单；不放凭据 | D2开发 |
| tests/test_role_identity_matching.py、test_role_identity_repo.py、test_role_identity_recovery_mongo.py（新增） | 规则、CAS、历史回退与真Mongo | T1测试 |
| tests/test_jjc_ranking_inspect.py、test_jjc_match_data_sync.py、test_role_identity_recovery.py、test_recover_jjc_role_identities.py、test_jjc_ranking_identity_recovery.py（后三者新增） | 服务、CLI、负载/排名兼容 | T2测试 |
| docs/design-docs/database-design.md、docs/references/runbook.md、README.md、README-Docker.md、当前change | 字段契约、配置/启用、操作和验收 | 主agent |

默认不改路由、HTML/CSS、依赖、镜像/compose和索引。singletons仅必要装配。旧回填脚本若存在旁路，先停止生产使用旧版本并复用仓储保护，不默认重写全部脚本。扩大文件范围先记录并确认。

## Plan of Work

### G1 基线、契约与隔离环境

主agent重读约束、保存status/HEAD/无关差异与本任务allowlist；分组跑已有相关测试，区分存量失败/测试污染，不改无关代码掩盖。列举所有当前查询组合写入口和刷新标记TTL，冻结函数签名、expected snapshot、严格来源值、候选/调用上限和CLI参数。

准备三个最小脱敏fixture，保留关键ID/时间关系，不提交原始大清单。准备真实本地Mongo与Python3.9；JJC_TEST_MONGO_URI显式指向本地隔离实例并拒绝生产URI，随机测试数据库有固定测试前缀，清理只准该数据库。上游默认stub，不在生产跑测试、装依赖或建测试集合。实测底层HTTP超时/重试，不能假装取消线程请求。

明确既有严格标记后的再次转服/改名不在ID-only自动迁移保证内：本期保守拒绝改变server/name/zone，记录unresolved供专项核验，不在开发中临时放开完整画像覆盖。超时返回不释放尚未结束HTTP的探测许可，其他角色不得叠加在途线程；预算不够允许未解决。

### G2 测试子agent先行 Red

T1只写规则/仓储/Mongo测试；T2只写服务/CLI/排名测试，各自独占文件。最多主agent+两测试agent并行，接口由主agent协调。记录每个Red命令、断言、实际失败和风险；新增函数不存在的ImportError可以是第一步，但骨架具备后必须证明行为断言失败，环境/拼写错误不算有效Red。

先覆盖混合资料复现、成功实时验证可修两个ID、同水位仍受历史规则约束、伪source/循环证明拒绝、迟到组合回退、CAS缺失/null、同角色并发、dry-run零写与备份失败零写。完整矩阵见test-plan.md。测试agent不改业务、不commit、不访问线上。主agent复现Red后才进入G3。

### G3 开发子agent最小 Green

D1实现matching/repo；D2实现共享编排、query/ranking/sync/CLI，可复用空闲测试agent，但最终reviewer不得为实现作者。先冻结并合入repo接口再依赖，不允许两agent同时改同一文件。修改测试须交原测试作者复核，不能删断言/放宽身份条件变绿。

顺序：严格ID-only CAS和归档→历史组合/直接刷新旁路保护→排名成功入口→页面有界兜底→一次性CLI。每片段先Red、最小实现、对应Green，保存输出。成功旧路径不依赖恢复可用；不新增框架。apply逐条重新验证后立即CAS，旧verify报告不能直接写库；备份/归档失败停写，鉴权/429/调用上限停止本轮，不改票据。

### G4 Refactor与主agent验证

仅Green后局部去重，不重写identity/sync架构。主agent独立跑核心、服务/排名/同步、路由/缓存、页面导航回归。真实隔离Mongo验证并发matched_count、missing/null、归档失败、崩溃重入/继续和after-image回滚；模拟验证期间转服、验证后迟到任务、两个进程竞争。冷却仅单进程承诺，跨进程正确性靠CAS。

真实Python3.9跑核心/服务测试和py_compile，3.13结果另记；每组有限时，测试污染用独立进程确认，skip不算通过。演练发布allowlist/hash和数据回滚：恢复原字段缺失、保留后续合法更新、不误删新缓存。同步数据库约束、runbook、change文档。

### G5 独立子agent只读 review

使用非实现作者的review子agent，读取本计划/design/spec、实际diff和Red/Green/验证证据，按适用本地code-review skill，只读不改。优先找伪indicator、数字串号、查询组合回退、CAS后缓存竞态、旧进程旁路、备份/回滚缺口、无界请求和凭据；评估新增方法/模块必要性。

P0/P1/P2关闭或用户明确接受后才发布。发现问题先补Red、修Green、主agent重跑、独立复审。推翻方案即暂停审批，不借review自动合并或发布。

### G6 commit与制品

主agent检查diff/敏感信息，只stage逐项allowlist，不夹带无关删除或角色原始清单。建议A为机制+测试+文档、B为CLI+测试/操作说明；可合为一个绿色commit，不提交半成品Red。记录每个SHA和验证；不amend。

从最终已审release commit导出发布文件和SHA256 manifest，同时记录目标旧基线hash。禁止dirty tree整目录tar/scp。默认不push；采用提交制品传输即可，若必须远端Git流程先明确remote/branch并确认。release commit与运行文件hash共同确定版本。

固定目标生产相关源码/依赖的基线manifest，隔离副本应用“实际将发布的overlay制品”，用脱敏测试配置运行相关回归、真实3.9/隔离Mongo和装配验证。只测本地release commit不够；若未覆盖依赖与本地不同且无法证明兼容，停止而不是扩大上传范围。运行版本三元组为生产基线manifest+overlay release SHA+制品hash；G7发现基线变化须重做组合验证。

### G7 生产预检、备份、发布与受控重启

仅G0已批准且G4/G5/G6通过后执行，主agent独占生产写入。复核容器/挂载/镜像/启动时间/重启计数、代码基线hash、磁盘、Mongo health、定时任务窗口和独立worker，不dump完整配置。目标路径/文件与基线不一致、未知改动、缺备份或权限异常即停止，不盲git pull/覆盖。

记录原全局同步暂停状态，使用现有CLI pause，等待活跃syncing/detail_syncing结束，最多120秒，超时暂停发布而非杀任务。所有可能写受保护字段的独立worker须升级同一release或停止并保持暂停，不能只更新bot。原本已暂停的环境结束时不擅自resume。

逐个记录writer的PID/容器/入口和启动时间；独立Python进程必须实际停止或升级后重启并证明重载新代码，文件hash改变不等于进程已加载。不能证明者保持停止；额外writer重启不在明确审批范围时先确认，两次bot重启期间同样适用。

在绑定代码目录外建立受控release目录，备份旧allowlist文件及存在状态/权限、hash、镜像ID/容器状态、原同步状态和回退步骤，读回校验；备份不可写或校验失败，在停容器前退出。数据/缓存before-image由apply逐条另备份；运行时自愈复用已落库历史归档。

上传制品到独立staging，校验相对路径无越界、allowlist和hash。先停止jx3bot，再替换/app绑定源中的文件，逐文件备份/替换避免半新半旧；不碰运行配置、凭据、数据和未列文件。启动同一容器，构成受控重启。无依赖/镜像变更不重建，不重启宿主机，不compose down/清库。

第一次启动JJC_ROLE_IDENTITY_RECOVERY_ENABLED必须为0，确认API/排名/同步的新增恢复写入口全部关闭；仓储组合保护仍开启，CLI显式apply可单独试点。唯一配置项的后续修改是上述“不碰运行配置”的明确例外：备份配置并保留其他键/凭据，只原子修改此获批项，严禁部署本地runtime_config覆盖生产文件。

### G8 重启健康与单角色试点

核对Running、StartedAt更新、RestartCount不持续增加，运行文件hash=release manifest。制品覆盖不改变宿主Git HEAD，不能用旧Git HEAD假称版本。检查最近日志无导入/语法/Mongo初始化及任务异常；检查内网及公网健康/查询业务响应。HTTP200或容器running不足以通过。

重新验证小耶猫当前/候选及独立replay，备份后apply --limit 1，再回读两个ID和稳定身份。公开role-indicator、synced-role、synced-role-matches业务成功且列表global_id不变。真实浏览器打开原页面，桌面/手机宽度确认赛季卡不再暂不可用、指标与本次上游一致、列表可加载。

启用前对颜魉/盖伊伊只读核对候选，健康对照苍术正常查询，不先批量apply。小耶猫CLI试点/API/页面通过后才将唯一配置置1，执行第二次受控重启并证明开关已加载，保持同步静默和备份。回读小耶猫验证持久性，再选一个尚未修复的代表角色经真实页面/API触发有界自愈，验证请求数、独立映射、归档和结果；补验另一个角色及健康对照。指标取执行时响应，不写死706场，不能只看缓存命中宣称恢复。无需第三次证明性重启。

### G9 分批恢复、同步恢复与观察

重新生成所有身份的线索清单并保留所有不同候选；当前有效标healthy，不换历史ID。无候选单列，不做14万角色上游普查。每批20、单并发、逻辑调用至少间隔1秒，每批最多100、本次运行最多120；底层重试另计，不连续重启绕上限。先试点、后批量，不在未通过试点时全量apply。

运维verify/apply/verify-applied及主动force_refresh的上游调用按同一run记录累计，切子命令不重置额度；公开缓存命中不新增上游调用，必须实时复验时计入剩余额度。自然公众流量另计，不声称CLI能控制全站。force_refresh不能绕过页面恢复冷却/调用/身份校验。

20是批次角色上限，不保证20个都能在100调用内完成apply与复验；剩余额度不足先缩批或留applied_unverified。运维公开API没有可靠调用计数时按每请求最多5调用预留，未知不记零，手工curl也先登记；同一窗口只允许一个运维执行者。verify-applied直接只读数据库/必要只读上游，不调可能写缓存/自愈的公开API；公开API验收另列允许写缓存/自愈的操作，不能称严格零写verify。

每批看成功/冲突/并发跳过/无候选/上游失败、耗时和错误。出现一个串号、越权字段变化或可复现回退即停止并评估回滚；鉴权/429立即停；5xx或重启循环先回退发布。只有回读及公开API业务成功计recovered，未公开验收者为applied_unverified；缓存失败明确标记。结果互斥状态之和=输入去重数，未知范围独列。

确认无旧写者、试点通过后按原状态resume同步，观察至少15分钟，覆盖一次真实正常同步/详情投影和单角色排名入口；不为验收强制跑全榜。自然周期未覆盖则受控单角色验证并记录未观察周期，不虚报。批次间复核，超过批准窗口保存进度停止。

### G10 验收、证据提交与回滚

acceptance记录release SHA/hash、Red/Green、测试计数/skip/失败、review、实际停机/两次重启、试点/对照、run_id/manifest、备份位置、批次结果与未解决清单。Git只提交脱敏摘要，敏感备份留受控操作目录。线上记录另做证据commit，不amend已发布commit；纯文档提交不冒称再次发布代码。

故障先停apply/探测，保留同步暂停。代码回退只恢复本次allowlist旧文件，校验并再启动容器；不reset全库。数据独立after-image CAS回滚，仅还原本次字段/缺失和观测标记；后续合法更新跳过并报告，只条件失效本次缓存。旧代码可能重新允许倒灌，回退后保持同步暂停直至风险确认。代码回滚不等于数据回滚。

回滚同时将获批启用配置恢复为发布前原值，保留其他配置/凭据，按启动加载方式验证生效。关闭开关既不解除仓储保护，也不等于回滚已更新数据；这三类结果分别记录。自动自愈发生在本次CLI清单之外的角色不能凭本run盲回滚，应先用既有归档单独核实。

完成后才同步基线spec和归档；未解释风险/未解决者不全勾完成，不把未知角色算健康。

## Concrete Steps

以下命令仅计划批准后执行。新脚本/参数为拟实现契约，先 --help 和测试核对，不复制不存在的命令直接上生产。

### 本地Red/Green、回归与兼容验证

```bash
cd /home/songjingjing/codes/jx3bot
git status --short
git rev-parse HEAD
git diff --check
.venv/bin/python -m unittest tests.test_role_identity_matching tests.test_role_identity_repo
.venv/bin/python -m unittest tests.test_role_identity_recovery tests.test_recover_jjc_role_identities tests.test_jjc_ranking_identity_recovery
.venv/bin/python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_match_data_sync tests.test_jjc_sync_repo
.venv/bin/python -m unittest tests.test_indicator_utils tests.test_jjc_ranking_stats_router tests.test_jjc_data_center_navigation tests.test_jjc_live_refresh
.venv/bin/python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration
# 显式JJC_TEST_MONGO_URI只指向本地隔离实例，skip不算通过。
.venv/bin/python -m unittest tests.test_role_identity_recovery_mongo
# PY39为G1准备的真实Python3.9；等价隔离容器执行另记录完整命令。
"$PY39" -m unittest tests.test_role_identity_matching tests.test_role_identity_repo tests.test_role_identity_recovery tests.test_jjc_ranking_inspect tests.test_recover_jjc_role_identities
"$PY39" -m py_compile src/services/jx3/role_identity_matching.py src/services/jx3/role_identity_recovery.py src/storage/mongo_repos/role_identity_repo.py src/services/jx3/jjc_ranking.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/jjc_match_data_sync.py scripts/recover_jjc_role_identities.py
openspec validate jjc-role-identity-recovery --strict
```

未新增共享模块则去掉该路径，新增改动文件补入验证列表。分组运行避免import stub污染；前端未改仍做真实桌面/手机验收。

### 一次性CLI契约

```bash
python scripts/recover_jjc_role_identities.py inventory --output "$INVENTORY_DIR" --batch-size 500 --replay-scan-limit 200000
python scripts/recover_jjc_role_identities.py verify --manifest "$MANIFEST" --manifest-sha256 "$HASH" --run-id "$RUN_ID" --release-sha "$RELEASE_SHA" --limit 1 --max-logical-calls 100 --run-dir "$RUN_DIR"
# apply须重新实时验证，不能用旧verify结果直接写库。
python scripts/recover_jjc_role_identities.py apply --manifest "$MANIFEST" --manifest-sha256 "$HASH" --run-id "$RUN_ID" --release-sha "$RELEASE_SHA" --run-dir "$RUN_DIR" --backup-dir "$BACKUP_DIR" --confirm-target "$TARGET" --limit 1 --yes
python scripts/recover_jjc_role_identities.py verify-applied --run-dir "$RUN_DIR" --max-logical-calls 100 --min-interval 1
python scripts/recover_jjc_role_identities.py apply --manifest "$MANIFEST" --manifest-sha256 "$HASH" --run-id "$RUN_ID" --release-sha "$RELEASE_SHA" --run-dir "$RUN_DIR" --backup-dir "$BACKUP_DIR" --confirm-target "$TARGET" --resume-from "$RUN_DIR" --limit 20 --max-logical-calls 100 --yes
# rollback默认预览，显式apply才写。
python scripts/recover_jjc_role_identities.py rollback --run-dir "$RUN_DIR"
python scripts/recover_jjc_role_identities.py rollback --run-dir "$RUN_DIR" --confirm-target "$TARGET" --apply --yes
```

所有操作目录为经校验绝对路径，备份仅运维可读，无凭据；run-dir/backup-dir/manifest关联由操作记录明确保存。写前flush/fsync。continue重新回读并核验，不能盲跳或重放。正式脚本显式校验运行目标及生产写入授权，verify不得顺手初始化索引。

### commit和发布操作骨架

```bash
# 用主agent审核过的逐文件清单替换占位符，禁止git add .
git add -- <本次明确文件清单>
git diff --cached --check
git diff --cached --stat
git commit -m "fix(jjc): recover verified role query ids safely"
# 从此commit导出allowlist制品与SHA256 manifest，而非dirty tree。
```

从WSL bash -ic加载aliyun alias，远端操作使用单一受审shell/script，凭据不写命令。以下能力已在仓库/诊断核对，但G7检查/备份/上传/校验不可省略：

```bash
aliyun -n -o BatchMode=yes 'docker inspect --format "{{.State.Status}} {{.State.StartedAt}} {{.RestartCount}}" jx3bot'
aliyun -n -o BatchMode=yes 'docker exec -w /app jx3bot python scripts/jjc_sync.py status'
aliyun -n -o BatchMode=yes 'docker exec -w /app jx3bot python scripts/jjc_sync.py pause --reason=role-identity-release'
# 完成静默、备份和staging制品校验后，stop→替换allowlist→start构成重启。
aliyun -n -o BatchMode=yes 'docker stop --time 60 jx3bot'
# 此处主agent发布已验证allowlist，不覆盖整个/app，不碰配置/运行数据。
# 首次启动恢复开关为0；CLI试点通过后，仅原子修改获批配置为1，再按相同受控步骤第二次重启。
aliyun -n -o BatchMode=yes 'docker start jx3bot'
aliyun -n -o BatchMode=yes 'docker logs --since 5m --tail 200 jx3bot 2>&1'
# 仅原本未暂停且门禁通过/无旧写者才恢复。
aliyun -n -o BatchMode=yes 'docker exec -w /app jx3bot python scripts/jjc_sync.py resume'
```

公网验证使用URL编码，并解析业务字段，curl --fail不能证明业务成功：

```bash
curl --fail --get 'https://qike.rickchen.cn/jx3bot/api/mongo/health'
curl --fail --get 'https://qike.rickchen.cn/jx3bot/api/jjc/ranking-stats/role-indicator' --data-urlencode 'server=梦江南' --data-urlencode 'name=小耶猫' --data-urlencode 'identity_only=true' --data-urlencode 'force_refresh=true'
curl --fail --get 'https://qike.rickchen.cn/jx3bot/api/jjc/ranking-stats/synced-role' --data-urlencode 'server=梦江南' --data-urlencode 'name=小耶猫'
curl --fail --get 'https://qike.rickchen.cn/jx3bot/api/jjc/ranking-stats/synced-role-matches' --data-urlencode 'server=梦江南' --data-urlencode 'name=小耶猫'
```

生产health和路由参数在G7重核；status_code/data内错误、稳定身份、缓存来源、指标逐项验。真实原页面为 https://qike.rickchen.cn/jx3/jjc-synced-matches.html?server=%E6%A2%A6%E6%B1%9F%E5%8D%97&name=%E5%B0%8F%E8%80%B6%E7%8C%AB 。本地fixture不能替代线上页面。

## Validation and Acceptance

G2有行为Red、G3对应Green、G4真实Mongo/3.9/回滚通过、G5重要发现关闭、G6制品来自已审commit、G7备份与重启通过、G8试点/对照成功、G9批次回读/历史防回退及观察、G10证据和未解决范围完整，前置未过不能跳阶段。

主键和同步水位不变；严格验证前不替换非空ID；同名不能串号；混合资料经验证可修且不再部分回退；候选和调用有界；缓存失败不伪报页面成功；无候选不伪造零场；回滚保留后续合法更新；无新增对象/字段/集合/worker；结果数量守恒；线上日志/API/页面/重启后持久结果一致。
