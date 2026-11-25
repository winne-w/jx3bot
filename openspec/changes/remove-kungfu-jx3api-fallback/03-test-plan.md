# 测试计划与实际结果

2026-11-25。执行计划已确认，以下记录实际离线验证。完整命令及模块见02-execution-plan.md。

## 用例与结果

新增 tests/test_jjc_kungfu_no_jx3api_fallback.py 覆盖推栏空心法、空字符串、异常，榜单失败、未匹配、缺身份，本地胜场命中/未命中、缓存命中、推栏成功资料/预热、可用JX3API历史不采用以及旧依赖移除。tests/test_jjc_ranking_history_win_kungfu.py保留仓储的身份/赛季/胜场/来源约束，替换旧外部兜底断言，新增未知心法角色仍入队回归。

原实现RED：6项测试，10个失败（含矩阵子用例），明确包含“JX3API must not be queried for kungfu”，不是仅由签名或导入失败导致。最终新行为及历史胜场专项：Python3.13/3.9各47项通过。

完整定向回归：Python3.13.2共372项，20.941秒，OK；Python3.9.25共372项，23.409秒，OK。均无失败、错误或跳过。覆盖执行计划中的15个模块，含实际隔离Mongo集成测试。修改Python文件在两版py_compile通过，git diff --check通过。

## 环境和限制

测试Mongo只绑定127.0.0.1:27029，数据目录和进程由本次runner新建并独占，使用明确JJC_TEST_MONGO_URI和随机测试库，结束后自有mongod已停止。初次未配置Mongo、动态端口不符fixture白名单、以及中途构造参数尚未改完的失败日志均保留，不计为最终通过。完整无Mongo基线未通过，因此不宣称已得到干净的全量修改前基线。

使用fake推栏或回环HTTP测试服务；未访问真实上游、生产Mongo或线上页面。不声明线上性能或生产行为已生效。现有普通竞技查询实现未修改。

## 证据

私有证据目录 /home/songjingjing/.cache/remove-kungfu-jx3api-fallback-20261125/，含 red-new-tests.log、test-agent-integration.log、test-agent-py39.log、final-r2-py313.log、final-r2-py39.log、final-r2-results.json、implementation.diff、manifest.json及before文件。独立review专项日志另存independent-review.log。仓库evidence/verification-summary.json保留可追踪结果和最终文件指纹，不复制配置或凭据。
