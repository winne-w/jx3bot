# 验收记录（暂停于生产容量门禁）

状态：本地TDD/review和release commit完成，已发布默认关闭的机制并完成第一次受控重启；生产只读盘点期间发生可用性异常，健康恢复后暂停后续。2026-10-20用户明确批准tasks计划并要求继续，含既定commit/发布及两次bot容器重启。实际仅重启一次、零角色apply，不能声称页面或所有角色恢复。

## 审批与版本

计划批准：2026-10-20本会话用户“我确认方案没有问题，你继续操作”。起始HEAD为c8156708c8f9a24c2273ecac328a314524b120c2。代码commit acc63576dc77e3e9affd7a043ce88831e5024a68及ef2d723fd9c7297794a968d0461b671ad4b88ab5；前者为当前bot运行版本，后者仅追加CLI projection性能修复，私有维护CLI已使用后者。生产发布不是全仓Git覆盖，具体基线/制品hash见下。没有push/amend。纯文档证据提交不改变实际运行代码版本。

## TDD与审查

storage_tdd和service_tdd先完成原30/171测试基线，再交付真实行为Red，主agent独立复现后授权最小Green；CLI由主agent测试先行。独立reviewer非实现作者、只读静态审查，重要发现补Red/Green再复审。未弱化身份断言，接口类型时间统一UTC毫秒datetime有明确记录。

主agent最新独立命令（最后缓存loader透传补丁后服务已再次复验）：

```bash
JJC_TEST_MONGO_URI=mongodb://127.0.0.1:27029/jjc_test_role_identity .venv/bin/python -m unittest tests.test_role_identity_matching tests.test_role_identity_repo tests.test_role_identity_recovery_mongo tests.test_recover_jjc_role_identities
# 83 tests OK，含13仓储Mongo与2 CLI Mongo端到端，无skip
.venv/bin/python -m unittest tests.test_role_identity_recovery tests.test_jjc_ranking_identity_recovery tests.test_jjc_ranking_inspect tests.test_jjc_match_data_sync
# 222 tests OK，无skip
```

以上两组在真实Python3.9.25（/tmp/jjc-recovery-py39/bin/python）各自同样83/222全部通过；本地日常venv为3.13.2。Mongo7.0.28仅绑定127.0.0.1:27029，随机测试库前缀且安全清理，不触碰生产。独立review静态PASS与九项根因闭环见review.md。

分组回归：indicator/router/navigation/live-refresh 38，detail/snapshot/hydration 50，sync-repo/indicator 56，均通过；组间有重叠，不把总和声称独立测试数。3.9单独import singletons装配通过。Red/Green日志留在/tmp/jjc-*及/tmp/service-*，完整上线后补受控证据归档。真实Mongo覆盖双进程CAS、各字段竞态、missing/null、归档失败零写、崩溃重入和条件回滚。

## 发布与重启

release commit：acc63576dc77e3e9affd7a043ce88831e5024a68；生产源码基线tar SHA256：93212f431d2876b66475f69c41e06b776c829d50d3e2e755153dbb2d2dff8ef4。精确delta叠加生产副本，保留生产config helper和既有http_client/live-refresh，不以本地文件全覆盖。11文件发布tar SHA256：ef17791a1c9cd860226e444549ea39b84d553c17990f181eef2c8258d0b5d7c1。生产release/源码配置备份：/mnt/sata6-1/jx3bot-releases/role-identity-acc63576dc77-20261020，私有目录。

实际overlay的真实3.9/隔离Mongo核心83、服务222、快照50及装配通过。生产public补齐后的相关38项中35通过，3项与未修改baseline相同的存量失败：home/ranking入口不一致、共享视觉shell契约、live-refresh第一屏覆盖旧摘要。独立review静态确认不构成本次新增集成冲突；不声称线上组合全部通过。

首次stop请求2026-10-20T10:23:04.705457Z，stopped 10:24:05.049794Z，StartedAt 10:24:05.558228336Z，应用启动完成10:24:34Z；停止等待约60秒，进程静默后替换11文件并重读hash，未改镜像/依赖/全目录。第一次健康检查running、RestartCount=0（不能与重启前历史6直接相加）、Mongo ping及公网业务health成功，开关加载0，runtime config保持原字节。第二次启用重启及角色证据待填。

原同步状态已暂停（历史推栏战局历史403），本轮发布前active syncing/detail_syncing均0，未发现独立运行旧writer；四个bot内部worker随容器重载。原状态和原因保存在受控备份，不能为验收擅自resume。只读预检一次replay返回code0；这不证明历史接口鉴权已修复。已有status CLI会初始化既有索引（出现一个存量重复索引跳过警告），本轮不将其称零写操作。

生产预检、配置未被覆盖、旧代码/数据/缓存备份位置和校验、原同步暂停状态、独立旧写者处置、实际停机区间、两次重启StartedAt/RestartCount、运行hash与健康/错误日志：待填。不记录凭据/完整Config.Env。

生产基线manifest+overlay release SHA+制品hash及隔离组合验证：待填。唯一发布开关首次0/试点后1、仅该配置项变更的审计、独立writer进程实际重载证明：待填。不得用本地commit通过代替线上组合通过。

## 线上与存量结果

### 生产异常与实际停止位置

最终稳定复核截至19:39：三次公网Mongo health均200/业务0，耗时0.218/0.105/0.184秒。自有inventory进程列表为空，容器未额外重启；1分钟load降至0.16。零字节临时文件mtime=2026-10-20T11:24:32.790429Z，属于本轮；只作为首次JSON写入前的阶段线索，不作根因证明。19:34后所取日志无新Mongo timeout/调度miss，仍有既有NapCat502，不能声称所有子系统健康。原暂停与开关0保持。

2026-10-20 19:24后出现调度延迟/Mongo timeout，公网Mongo health超时、SSH亦超时。第一份旧inventory此前已按精确命令身份SIGTERM；第二份projection优化inventory的host PID9217在约19:32重连后确认已不存在，原guarded-stop未收到成功回执，不能断言其成功或退出原因。无manifest，stdout/stderr均为空，inventory仅有零字节临时文件。后者与到达JSON首次写入前阶段相容，不证明OOM或其他根因。

19:33复核容器running、OOMKilled=false、StartedAt仍2026-10-20T10:24:05.558228336Z、RestartCount=0，host MemAvailable约1.2GB、swap约180MiB；可读dmesg未找到对应OOM条目。19:34首发11源码hash全匹配，runtime_config.json与发布前hash相同，key仍缺失默认off。19:35运行配置实际0、Mongo ping=1、原global paused=true。公网Mongo health两次均HTTP200、业务status_code=0/connected=true，耗时约0.218/0.105秒。没有为恢复健康重启bot/主机、解除pause或启用开关。完整本地脱敏证据位于诊断目录incident-evidence-*.json、incident-health-config.json和incident-public-health-*.txt。

run目录/app/data/role-identity-recovery-20261020/run仍6/100，含1次既有预检replay及健康对照公开API保守预留5次；未新建run绕过限额，未绑定manifest。没有任何角色apply/角色备份记录、verify-applied或rollback。健康对照苍术/梦江南公开force indicator曾真实成功（849场，执行时响应），属于正常API可写缓存验收，不是零写盘点；不能替代故障角色验收。小耶猫/颜魉/盖伊伊尚未修复，也没有真实桌面/手机截图。

最终维护制品SHA256 45f66bc40cf7dedfa6c938b55475e552c2cac2cc603e6b47de8d594c00ac35e9，基于生产基线及ef2d723；仅CLI与首发制品不同、其他10文件hash一致。最终实际overlay真实3.9核心/CLI84、服务222、快照50、装配通过；核心84在3.13亦通过。第二次部署/启用/重启尚未执行，不能写成最终版本已生效。

未闭环容量门禁：全量inventory仍在内存保留身份/候选并整体JSON编码，projection减少传输但不足以证明容量安全。独立review要求禁止再跑该路径，先向用户确认三故障+一对照的精确点查/窄字段/维护进程单独资源保护；检查结果先审阅，角色apply和第二次启用重启另过确认门禁。四角色不等于全用户覆盖，全量范围与可恢复人数均未知。后续有界方案未执行，不能将暂停改写成验收通过。

小耶猫/颜魉/盖伊伊和健康对照：实时验证、独立数字映射、身份回读、公开业务API、真实桌面/手机页面、重启后持久结果：待填。指标取执行时响应，不固定诊断数字。

run_id/manifest hash、输入去重数、healthy/recovered/applied_unverified/conflict/concurrent_skip/no_candidate/upstream_error等互斥结果及守恒、完整备份/明细的受控位置：待填。无证据群体另列，不当健康，不从候选数或抽样估算故障/恢复数。

同步按原状态恢复、至少15分钟观察、实际历史写入/排名入口覆盖、自然周期未覆盖风险、是否触发回滚及CAS跳过、遗留角色后续建议：待填。全部门禁有证据后才同步基线spec/归档；不能因部署完成全勾验收。
