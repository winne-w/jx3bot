# 实现复核记录

2026-11-06：用户批准方案后按TDD完成实现，两名独立只读子agent执行实现review，未调用设计阶段排除的code-review技能。`implementation_review` 审发布协议、数据库与client/runtime，`ranking_review` 审排行榜、快照、装配、UI与复杂度。二者复评均通过，当前无阻断问题。历史设计评估见[design-assessment.md](design-assessment.md)，不是本次实现通过的依据。

| 问题 | 等级 | 修复与实证 |
|---|---|---|
| 队列代次损坏后普通重试可在线追平角色版本 | P2，关闭 | service查询前发现已有版本>=领取版本抛QueueIntegrityError；runtime停止本消费者。新增断言先RED后GREEN，不外呼、不确认；正常发布期间同代重读仍保留。 |
| 已有name-only/global-only身份缺查询定位永久无法刷新 | P2，关闭 | 仅兼容且缺区服/ID候选走既有安全upsert，重验同_id、全部ID和心法保留；真实Mongo先复现失败再GREEN，完整热角色仍每250人批查。 |
| Mongo查询$type匹配数组元素，可覆盖畸形结果 | P2，关闭 | $expr+$type限制标量object和int/long，再比较版本；真实Mongo拒绝数组结果/数组版本，合法标量照常接受。 |
| 同cache_time重算后unknown明细残留导致重复角色 | P2，关闭 | 每范围始终写unknown明细，空值也写[]；真实Mongo冷→热、新→旧回滚同anchor total均为1。 |
| 紫武排名列表仍把unchecked装备当紫武 | P2，关闭 | 加载和渲染入口同时检查equipment_incomplete；Node运行真实页面函数证明零请求并显示不可用说明，阻止缓存/异步结果误显示。 |

复评后的小幅简化：移除队列register未用refresh_seconds参数；整数校验统一接受Python int/BSON Int64并拒绝bool，未削弱代次/定位/租约守卫；requested_at明确为本轮尝试开始（含间隔等待），无需额外请求tracking层。

整体结论：角色结果与长期队列归属清楚，稳定ObjectId、角色级generation、定位条件发布、先写后确认和过期恢复符合批准设计。允许A在B尚未成功时写入n、但不覆盖B成功n+1的边界已测试；不宣称跨集合exactly-once。没有引入事务、control、leader、heartbeat、前台等待或通用队列平台。保守unchecked辅助资料及少量幂等重复登记可接受，无需扩大首版。

`implementation_review`首轮复评85项和追加126项均通过；`ranking_review`首轮94项，修复后85项普通测试+5项真实Mongo集成通过。主执行者最终Python3.13.2/3.9.25各426项通过且无跳过，详见[test-plan.md](test-plan.md)与[validation-results.json](validation-results.json)。独立计数与主执行者计数是不同重叠运行，不相加。

兼容边界：快照仍以榜单cache_time为anchor；后台刷新不主动写快照。同一榜单显式重新统计仍按既有语义upsert该anchor，未新增快照版本系统。保存summary与details沿用原有非事务写入，不宣称读者能跨文档获取原子快照。完整历史同步排队仍独立，性能测试排除该流程耗时。

本地复评阶段尚未执行生产部署、单消费者实例核验、真实推栏/QQ发送或生产覆盖率验收；这些不计入当时本地review通过。随后已授权发布的实证见下节及deployment.md。回滚保留角色成功结果、队列generation及历史产物，操作见runbook。

## 已批准的可维护性优化复核（2026-11-06）

两位子agent以本轮前源码快照为基线独立只读复核，均通过，无新增阻断项。implementation_review确认两个身份helper保留同_id、ID兼容、定位补齐及心法字段保留约束，空白game_role_id正确回退role_id；46,656组旧新判定等价，独立54项身份/发布/真实Mongo/集成测试通过。条件发布AST未变，类型和版本守卫不变。ranking_review确认纯装备判断无DOM或输入副作用，覆盖提示、分布、过滤、加载/渲染双保护及导出共用；双网页内容一致，独立20项展示/导航/前端测试通过。抽象范围适当，未新增状态或调度机制。

主执行者最终两Python版本各426项通过，无跳过；独立运行与主回归有重叠，不累加。

## 发布阶段查询计划修复复核

implementation_review独立复核通过：普通idx_server_name覆盖raw legacy分支；global_id复用已有类型helper使partial index可选，不改匹配优先级/冲突校验/顺序。只加raw索引不足，真实2243分支完整查询从COLLSCAN 3250docs/445ms变为IXSCAN 250docs/1746keys/51ms；3万背景和string-array等价亦验证。独立55项通过，无skip；两Python版本完整各427项通过，最终新增断言另跑15项各通过。生产实际四批和单人planner通过，测得单次千人解析登记11.442秒；本地P95不作为生产指标。没有拆查询、删除fallback或增加重复global索引。

生产发布后补充核对：四批及单人planner indexed，30运行文件一致，两个运行开关为1且其他配置语义保持；四完整同步worker恢复，唯一bot消费者持续成功发布，2条身份不匹配退避未强制合并，角色发布版本不高于队列generation。两网页公网哈希与候选一致，桌面/手机JS0；手机19px表单溢出在生产旧版复现，属既有表现。未进行生产故障注入、强制身份合并或历史快照重算。后续预热与统计时效以实际快照为准。

## 2026-11-06 21点缓存缺失修复验证

用户要求覆盖率优先：已有可用画像复用，缺失逐个直接查询，替代纯冷本地unknown约定。线上故障诊断证实21:00实际known663/1000，unknown337（missing254、identity_unresolved83）；紫武列表为空另外由equipment_incomplete保护触发，未发现快照保存错误。

TDD先复现缺失未查询、并发client重叠、Python3.9导入时锁绑定错误、旧对局兜底假fresh、ack失败丢当前成功结果、合法前台接管误杀后台、版本损坏读回假成功、等待执行位置提前消耗租约。修复复用query_now/_execute、定向原子版本预留以及懒创建的service/client执行锁，无新增数据库字段或worker。

完整回归Python3.13.2与真实Python3.9.25各450项通过（主组428+独立router22），无skip；独立ranking/client审核3.9下63项、service/queue审核双版本各104项通过，无剩余阻断。原始日志及汇总/tmp/jjc-direct-final313.json、/tmp/jjc-direct-final39.json。设备信息不完整检查保留，不将旧对局缓存当本次fresh。

增量发布与实际上游验证尚待完成，线上证据追加deployment.md。冷榜耗时由缺失数和上游响应决定，不再引用旧全冷零外呼性能作为整次统计承诺。
