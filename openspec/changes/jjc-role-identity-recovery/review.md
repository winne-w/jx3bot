# Review

## 已完成的方案对抗审查

原adversarial_plan_review子agent在原始replay/转服历史证据核实后撤回独立查询对象建议，确认新服旧ID混合资料及indicator fill-only阻断链。只补replay、放宽同时间规则、按source强制覆盖、无条件按_id刷新和仅保护ID不保护server/zone均被反例否定。

审查支持复用两个ID、严格验证后CAS、无新增集合/字段/worker；要求同时保护查询组合、防缓存竞态、记录未解决范围。上述是方案判断，不是实现review通过。

## 本轮计划审查

历史计划审查：两轮只读审查的六项重要修订均复核通过，后补开关原值回滚与“每批最多20”。2026-10-20用户随后明确批准执行；下面记录实际实现审查，不能将计划审查代替代码审查。

修订包括：验证生产基线+实际overlay组合；首次关闭自动写入、CLI试点后第二次重启启用的唯一配置；独立writer进程实际重载而非只更新文件；严格观测后再次转服/改名保守列未解决；HTTP超时许可持有至实际完成；将公开API复验纳入同一运维额度并区分零写验证。均不要求新增恢复对象/集合/worker；唯一新增配置明确提交用户审核。

## 实施后的独立代码审查门禁

G5使用非实现作者子agent，只读检查实际diff和Red/Green/验证证据，不修改源码或操作生产。重点为独立数字映射、伪source、CAS/历史组合防回退、观测字段TTL、所有直接写入口、缓存竞态、备份/fsync、条件回滚、负载上限、凭据和最小复杂度。

P0/P1/P2逐条补Red、修Green、主agent重跑并独立复审；未关闭仅用户可明确接受。代码审查不代替生产验收。

## 实际代码审查：已通过

此为容量异常前的业务正确性审查结论，不等于后述生产容量门禁已通过；全量inventory目前禁止执行。

reviewer为独立非实现作者子agent `independent_review`。遵循已批准G5范围：本change完整diff、新文件及相关写入口/依赖，未扩大为无关全仓审计。仅静态，只读，未执行项目代码、构建、测试或生产操作；未修改源文件。未发现新增/加重凭据红线，最终无未闭环P0/P1/P2。

以下九项P2根因均补充有效Red、最小Green后复审关闭：CLI resume卡在首批20；合并/冷却遗漏查询身份语义；库存漏replay-only线索；切命令绕每批额度；异服候选先占两名额；候选/history/replay认证失败未沿用同步暂停；ranking未先检查当前健康ID；瞬时HTTP busy误入角色180秒冷却；save末端竞态导致错误身份缓存长期命中（含真实loader丢global_id/role_id依赖）。另主agent补fsync后15秒期限Red/Green。没有因此新增领域对象、Mongo字段/集合、worker或预算平台。

业务文件覆盖：config.py、runtime_config.example.json、scripts/recover_jjc_role_identities.py、matching/recovery/cache/ranking/inspect/sync/kungfu服务、role_identity_repo和jjc_inspect_repo；测试覆盖本change七个测试文件的完整新增断言及Fake/真实实现差异。相关依赖核对包括同步仓储/身份投影、三类client、HTTP超时重试、历史归档、missing/null CAS与条件回滚。README/Docker/数据库/runbook/change文档同步由主agent负责。

冻结关键SHA256：

```text
CLI             0c709c6569cad0c10f9fe4a402424146f65dfa95a9b316434b7f1d8630347b8a
recovery        971d965ab56d7ad909d407250782ab33ff3f6ed5fd8b7d0bf48ea23d37dd5d08
inspect service 06b83a56b4e545a557c9537fdc93ba6a843c5837b72c4b648652d3e0e1a2ae74
inspect repo    483979440b7858a99892a5b3dbf4d67aab02b599d2658341eb0ba1a4dfeb2ad6
identity repo   3bee91bf9a492ec0de959b4a2aaabb5d13522abbebaa89d8be8e046f96b178a9
```

主agent历史本地checkout独立分组验证：真实Mongo参与的核心/CLI 83和服务222，在Python3.13/真实3.9各自全通过无skip；原本地checkout的38路由/导航/live及50详情快照回归均在3.9通过。这不是production overlay结果；后者相关38为35通过/3存量失败，见下。此为主agent执行，不冒称reviewer运行测试；当时commit、生产基线overlay组合、备份/重启/线上验收尚为后续独立门禁。
## 生产容量异常后的独立复审：后续推进阻断

19:24后只读inventory期间发生健康/SSH超时，19:32后确认自有进程已退出并恢复健康。independent_review静态复核后要求不再执行原全量路径，保持paused/off、原预算6/100、零apply和未执行第二次重启。未访问生产、未执行代码/测试、未修改文件。

新发现的容量风险未闭环：inventory把全部身份、历史及候选留在内存，atomic_write_json再一次性编码，之后hash读回也非流式；窄projection只减少传输，并不证明完整链路安全。故障同时发生并不能证明OOM；容器OOMKilled=false、可读内核日志无相应条目，退出原因未定。零字节临时文件只能作为可能到达JSON首次写入前阶段的线索。

修订方案的三个反例：inventory分支忽略--name/--limit，不能靠两个参数缩小范围；既有load_query_id_recovery_candidates的limit不限制扫描/排序量或大文档字节；时间保护不限制峰值内存，且不得给共享bot容器收紧限额以免牵连业务。改成仅三故障+一对照的精确_id/稳定ID/缓存键/已知match_id窄字段点查，独立生成四身份manifest，不调用全量函数，不新增领域对象/集合/worker。资源保护只约束维护进程；歧义停止、不取首条。结果先展示，角色apply和第二次启用重启重新过确认门禁。

四角色通过不能推出全部用户可恢复；完整覆盖需后续另证分页、字节和逐批释放内存有界，原始证据缺失者必须保持unknown/unresolved。当前仅完成修订建议，未新增实现或在生产试跑，不得将本节记录为容量验证通过。

# 生产 Overlay 兼容性复审补记

本节为可用性异常前的历史兼容性审查；其执行许可现已暂停，不构成当前授权。后续一律以当前容量门禁及用户重新确认为准。

发布中发现CLI两处projection读取无关完整payload。service_tdd仅修改CLI两处find（9增2删）及77行真实Mongo测试，主agent复现Red并独立确认双Python核心84通过、最终生产overlay核心84/服务222/快照50/装配通过。独立reviewer逐项核对replay解析五身份字段、dict/list两种shape、rank八字段、Mongo数组顺序/旧关联/候选/match_id/扫描界限，静态PASS，无新P0/P1/P2。补充提交ef2d723fd9c7297794a968d0461b671ad4b88ab5，不修改业务验证/写库链。

异常前独立review曾同意私有维护CLI先执行、最终第二次stop时统一11文件/开启的兼容路径；必须记录first bot acc635/off与最终CLI版本区分，维护目录只含CLI、cwd/PYTHONPATH显式/app、10依赖hash不变，run沿用已有6预算且绑定最终release SHA，第二次以first已部署hash作expected-before。当时方案无需第三次restart；20k replay只限覆盖数量，不保证内存安全或所有用户可恢复。目前此路径暂停，不能直接续跑。

2026-10-20，独立非实现作者reviewer继续只读复审实际release acc63576dc77、生产baseline及11文件overlay，结论无新增P0/P1/P2阻断。10个业务/CLI文件与已审commit hash一致；config只保留生产helper并加入批准的默认0开关/runtime key。既有http_client/live-refresh及依赖hash不变。

最初routes38的9个异常中8个属于隔离快照缺public的测试装配缺口，不能宣称通过。主agent随后只读补入实际生产public，baseline和overlay均为35通过/3相同失败：home/ranking入口一致性、共享visual shell契约、live-refresh首屏覆盖40条为20条。静态文件及live-refresh不在本次11文件delta中，不夹带修复；运行日志和产物在私有诊断目录。当时结论仅针对兼容性，不等于线上角色已恢复，且不构成当前继续发布授权。
