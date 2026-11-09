# 验收记录（上线及四身份受限验收）

状态：2026-10-20 21:21完成本轮生产发布、两次受控重启及四身份验收。三例已知故障角色恢复、一例健康对照正常；全量受影响范围仍未知，不声称所有角色恢复。全量inventory容量风险与目标角色特定历史/排名入口验证未闭环，change保持active，不归档。此前暂停状态及零apply结论仅为19:39历史检查点，已被本记录的实际执行进展替代。

## 审批与版本

用户明确批准tasks计划并要求继续，含开发、子agent review、commit、发布及两次bot容器重启；网络恢复后再次要求继续。用户另明确说明全局同步paused=false是其主动操作，本轮未执行resume，也未将其改回pause。

起始HEAD c8156708c8f9a24c2273ecac328a314524b120c2。机制commit acc63576dc77e3e9affd7a043ce88831e5024a68，CLI投影优化commit ef2d723fd9c7297794a968d0461b671ad4b88ab5；最终运行overlay对应后者。4a96390为此前暂停阶段文档证据。没有push/amend；本次最终纯文档证据提交不改变运行代码。

## TDD、回归与审查

storage_tdd/service_tdd先完成原30/171基线及真实行为Red，主agent复现后授权最小Green；CLI由主agent测试先行。独立非实现作者reviewer静态只读审查，九项P2根因及发布中projection反例均补Red/Green、主agent验证、独立复审闭环。reviewer不冒称执行测试或生产操作。

实际最终production baseline+overlay，而非只测本地checkout：真实Python3.9.25/独立Mongo7核心及CLI84、服务222、详情快照50和singletons装配通过，无skip；核心84在3.13也通过。组间有重叠，不相加宣称独立测试总数。生产public齐全的路由/导航/indicator/live38项为35通过、3项与baseline相同失败（home/ranking入口一致性、共享visual shell、live-refresh首屏覆盖摘要），不称全绿，不夹带无关修复。测试Mongo只绑定127.0.0.1:27029，不触及生产。

本轮四身份临时运维工具未并入业务架构：targeted-manifest精确点查16项测试在3.9/3.13通过，deploy-second离线12项及browser验收14行为检查通过，主agent独立复验。natural-readback由service_tdd编写，4项离线fixture与3.9编译通过、独立静态复审通过，主agent运行生产只读回读12断言均真。唯一因果边界及force API字段假设修订见review.md；API marker不作公开契约，strict标记以Mongo回读证明。三份保存force响应补验hit=false和force_refresh=true，无重复调用。

## 制品、备份与两次重启

版本由生产基线manifest+overlay release SHA+制品hash确定，不用宿主旧Git HEAD冒称版本。生产基线tar SHA256 93212f431d2876b66475f69c41e06b776c829d50d3e2e755153dbb2d2dff8ef4。首发11文件tar SHA256 ef17791a1c9cd860226e444549ea39b84d553c17990f181eef2c8258d0b5d7c1；最终tar SHA256 45f66bc40cf7dedfa6c938b55475e552c2cac2cc603e6b47de8d594c00ac35e9。CLI最终SHA256 cc1da07c99ec191c59c1445ec375cf058fc5be983ddb2a84fb68ecd2082a00fa。

精确delta叠加生产副本，保留既有config helper、http_client/live-refresh及其他依赖，不整仓覆盖、不改镜像/依赖。原源码/运行配置字节、权限、hash、首次与最终staging、manifest和重启阶段日志保存在私有目录 /mnt/sata6-1/jx3bot-releases/role-identity-acc63576dc77-20261020。原全局pause（历史鉴权问题）、发布前active角色/详情均0及唯一bot writer已核实，未发现独立旧writer。

第一次stop请求10:23:04.705457Z、stopped10:24:05.049794Z、StartedAt10:24:05.558228336Z，应用10:24:34Z启动完成；等待约60秒，静默替换11文件，开关0，runtime config原字节不变，Mongo/公网health通过。

小耶猫CLI试点、公开API及真实桌面/手机页面通过并持久落盘后，第二次stop请求12:58:38.648435Z、stopped12:59:39.343610Z、start请求12:59:39.371886Z、StartedAt12:59:40.261225102Z。仅CLI与首发不同，其余10个业务依赖hash一致；仅修改获批JJC_ROLE_IDENTITY_RECOVERY_ENABLED为1，其他配置键保留。第二次pending记录在stop前fsync独占发布，阶段记录完整，成功phase=started不冒充业务验收。应用13:00:33Z启动完成；11文件hash、运行开关1、live-refresh0、Mongo ping和后续业务均通过。RestartCount=0且未持续增长；两次受控stop/start不以RestartCount相加计数。没有第三次证明性重启、宿主重启、回滚或擅自resume。

## 有界输入、预算和备份

私有操作root /app/data/role-identity-recovery-20261020，位于既有/app绑定。run_id=role-identity-acc63576dc77-20261020，release_sha绑定ef2d723fd9c7297794a968d0461b671ad4b88ab5，operation-manifest.json SHA256 b35e97a8ed1816a5a733a47c0f01da589d5538efbafc0b61b53cef6b094460f5，3491字节、4个去重身份、3个精确整数match_id。精确_id/已知match索引窄字段、limit2/maxTime2000、64KiB单doc/512KiB输出及维护进程自身512MiB/30秒限制；生成0.819秒、峰值RSS26056KiB。未调用原全量loader；manifest的未截断仅针对四输入，不代表全库。

同一run预算最终68/100，保留已有6、不切run/重置。CLI verify/apply均再次鲜验；手工公网force及两终端页面按每请求上界5保守预留（含一次关闭既有公告后的canary重截图）。本维护账本不涵盖用户恢复的后台worker或其他公众流量，不能宣称全站100调用上限。无新增业务预算平台。

CLI不可变BSON-aware before-image分别为data-backup/<identity_id>.json：小耶猫68079字节、SHA256 ec461036339c6413f890ebdaedb48063ef91a4552be64923a3a87884a8c5dc26；盖伊伊84834字节、SHA256 dd310d0ce0c665524923de4c6299b1befbfaa4227a6244446ac209b2c6fa14b4。备份保存关联缓存，写前fsync/0600，仓储另有旧快照归档。自然恢复前颜魉独立natural-before-6a1991a0bb1af2baecffe727.json为10370字节、SHA256 6dc718354ab28a759994ca21bbc90f51d11c929e14f84149f48d1266eb4113ca，包含完整身份及两份精确缓存，不调用apply伪造自然恢复。

## 四身份线上结果

| 身份 | 路径与查询ID | 公开验收指标（执行时） | 结果 |
| --- | --- | --- | --- |
| 梦江南/小耶猫 | CLI 31300496 -> 34945120 | 706场、56.2%、2808分、184最佳、15段 | fresh indicator+独立replay、备份CAS、两终端页面、重启后force复验均通过 |
| 唯我独尊/颜魉 | 在线自动 44421059 -> 31755654，无本run CLI apply | 458场、55%、2642分、36最佳、15段 | 新strict标记、旧CAS归档、成功缓存及两终端页面通过；不唯一归因页面 |
| 乾坤一掷/盖伊伊 | CLI 34971082 -> 26691973 | 420场、56.9%、2650分、93最佳、15段 | 新鲜verify+apply、备份CAS及公网force通过，未单独宣称两终端截图 |
| 梦江南/苍术 | 健康对照34750178保持 | 849场、79.4%、3368分、364最佳、15段 | 公网force及身份点查通过，未执行ID修复 |

两个CLI角色apply后立即回读expected-after通过，八个稳定身份/画像水位字段不变；13:21:06Z最终回读身份正确且画像水位仍未变。公开API会合法改变updated_at，不因此重apply或盲回滚。CLI记录仍applied_unverified；外部验收另存online-acceptance.json，不手工伪改CLI状态。四输入外部互斥结果为CLI recovered2+automatic recovered1+healthy1=4，未选入人口unknown；这个计数不是直接套CLI的最后一份单角色apply-report。

颜魉备份时旧ID44421059；13:12:54.899Z新strict标记与唯一归档时间一致，归档旧CAS逐字段missing/null和值与备份相符，七个稳定身份字段不变，after只改变两个ID/严格标记来源/时间/updated_at五字段。缓存raw code0、角色ID/SK01/区服一致、统计解析匹配，新cached_at通过；已知run无该角色apply记录。desktop hit=false、mobile hit=true，无强制刷新。同期自然sync已由用户恢复，因此这些证据只证明未手动apply的在线自动链路恢复和真实页面成功，不能排除sync先修后页面取值，不能唯一声称页面触发CAS。

小耶猫及颜魉原页面真实浏览器1440桌面/390手机均HTTP200、业务0、raw0，DOM四数值与响应一致，无“赛季战绩暂时不可用”、JS错误或横向溢出。既有公告关闭后主agent人工看图无遮挡；手机其他统计位于下方、DOM均校验，不冒称首屏显示全部。synced-role与synced-role-matches均200/业务0、global_id保持，列表非空；自动synced-role-refresh请求被明确阻断以避免额外上游。截图和17份证据文件hash保存在online-acceptance.json，无改前端。

三份重启后force（小耶猫/盖伊伊/苍术）均HTTP200、业务0、原raw0、hit=false/force_refresh=true；身份与指标为实际本次值，不只凭传force参数或旧缓存宣称鲜验。strict标记由Mongo另验，不依赖公开API是否序列化该字段。

## 观察、生产异常与保留范围

截至13:21:00.691Z，第二次启动后1280.4秒（超过21分钟），Running/StartedAt/RestartCount稳定。最近15分钟1746行、约172KiB，小于3000行/4MiB采证上限；本窗口未见traceback、Mongo超时、调度miss、恢复/身份投影失败、HTTP5xx、明确鉴权失败或ERROR级日志。最初启动后两分钟小尾部采集未找到startup字样，不能凭脚本exit0通过；随后独立90秒完整窗口147行明确找到Application startup complete及Uvicorn running。

后台自然同步运行中，窗口有457条详情身份投影完成日志，样例269331633/258563843显示projected=6；不是去重对局数，也不能证明三个修复角色被这些历史payload覆盖。未额外制造历史回放/排名写入或全榜抓取，修复角色特定历史防回退与排名入口的线上演练未观察；本地测试覆盖这些边界。NapCat502每分钟存量告警仍在（本15分钟15条），不是本修复引入，不称全部系统健康。host load约0.17、MemAvailable约1.2GB，最终公网Mongohealth再次业务0/connected=true/error=null，ping11.5ms，证据另存final-public-health.json。

19:24前后原全量inventory期间出现公网/SSH超时、调度miss和Mongo timeout；19:32后确认自有进程退出，19:39健康恢复，零业务apply为当时历史状态。网络异常与盘点资源风险的根因未唯一证实，不认定OOM（容器OOMKilled=false、可读dmesg无证）。用户随后明确网络恢复并授权继续。全量inventory仍保留所有身份/候选和一次性JSON编码，projection不能证明容量安全；本轮严禁重跑，未为发布新增领域对象/集合/worker。

所有角色影响范围与可恢复人数仍未知。证据不足、无候选、上游不可用或严格观测后再次转服/改名者不保证自动修复，保持unresolved；未把其他角色算healthy。完整有界盘点及逐批覆盖需要后续TDD/review，不能用这四例替代全量验收。G9及G10总体保持未完成，不同步基线spec或归档。

## 回滚与证据保全

本轮未触发回滚。代码/配置回滚只准原allowlist及获批配置项，保留其他键和数据；代码回退不等于ID数据回退。数据恢复以既有before/expected-after CAS为准，API或sync后续合法更新须跳过而非强写；颜魉自动恢复另据既有Mongo归档核实，不能假借CLI run盲回滚。用户当前同步状态不由本轮擅改。

完整证据留在生产私有release目录、操作root的run/data-backup/natural-before和online-acceptance.json，以及本地_diagnostics/2026-10-20-role-identity-recovery。Git只提交本脱敏摘要/tasks/review，不提交原始响应、角色完整资料、凭据或数据库连接串。最终三份文档经独立review通过，无新增P0/P1/P2；OpenSpec strict/diff检查及browser14项复验通过。证据doc-only commit见Git历史，不冒称再次代码发布。
