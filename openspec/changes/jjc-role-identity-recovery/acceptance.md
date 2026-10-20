# 验收记录（待执行）

状态：本地TDD/review进行中，线上未验收。2026-10-20用户明确批准tasks计划并要求继续，含既定commit/发布及两次bot容器重启。已开发和执行本地业务测试，未commit、未生产写入/发布/重启。只读诊断不是恢复完成。

## 审批与版本

计划批准：2026-10-20本会话用户“我确认方案没有问题，你继续操作”。起始HEAD为c8156708c8f9a24c2273ecac328a314524b120c2。代码release commit、制品SHA256/allowlist、部署目录、运行文件hash、回滚版本：待填。纯文档证据提交与实际运行代码版本分别记录。

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

生产预检、配置未被覆盖、旧代码/数据/缓存备份位置和校验、原同步暂停状态、独立旧写者处置、实际停机区间、两次重启StartedAt/RestartCount、运行hash与健康/错误日志：待填。不记录凭据/完整Config.Env。

生产基线manifest+overlay release SHA+制品hash及隔离组合验证：待填。唯一发布开关首次0/试点后1、仅该配置项变更的审计、独立writer进程实际重载证明：待填。不得用本地commit通过代替线上组合通过。

## 线上与存量结果

小耶猫/颜魉/盖伊伊和健康对照：实时验证、独立数字映射、身份回读、公开业务API、真实桌面/手机页面、重启后持久结果：待填。指标取执行时响应，不固定诊断数字。

run_id/manifest hash、输入去重数、healthy/recovered/applied_unverified/conflict/concurrent_skip/no_candidate/upstream_error等互斥结果及守恒、完整备份/明细的受控位置：待填。无证据群体另列，不当健康，不从候选数或抽样估算故障/恢复数。

同步按原状态恢复、至少15分钟观察、实际历史写入/排名入口覆盖、自然周期未覆盖风险、是否触发回滚及CAS跳过、遗留角色后续建议：待填。全部门禁有证据后才同步基线spec/归档；不能因部署完成全勾验收。
