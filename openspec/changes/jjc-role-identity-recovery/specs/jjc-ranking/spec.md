## ADDED Requirements

### Requirement: 严格验证的角色查询 ID 可条件更新

系统 MUST 复用现有 role_id/game_role_id，在原始实时 indicator 的 ID、区服、SK01 和独立 replay 数字 global_id 映射一致时条件更新。系统 MUST 保持稳定主键、非目标画像与同步/对局水位不变，更新前归档旧值；不能凭普通 source=indicator 获得覆盖权限。

#### Scenario: 旧 ID 空而候选通过独立验证
- **WHEN** 当前 ID 无效且候选原始 indicator 与精确数字身份 replay 证明一致
- **THEN** 系统归档并 CAS 更新两个 ID，成功响应来自本次有效战绩，不为旧缓存续期

#### Scenario: 缓存键或同名形成循环证明
- **WHEN** 候选只有同名、复制的缓存键 global_id 或相同 SK01，没有独立数字映射
- **THEN** 系统不强制更新，分类为未解决或冲突

#### Scenario: 目标在验证期间变化
- **WHEN** 目标原画像、水位或观测标记与 expected snapshot 不同
- **THEN** CAS 不匹配，系统重读而不强写或缓存迟到结果

#### Scenario: 普通缓存兜底借用 indicator 来源名
- **WHEN** 非原始成功响应通过通用 indicator upsert 写入
- **THEN** 系统保持原补缺权限，不授予替换非空 ID 的能力

### Requirement: 当前查询组合不得被历史部分回退

系统 MUST 复用既有观测字段区分严格验证与普通刷新，保护服务器、名字、区服和两个 ID 的一致组合。系统 MUST NOT 将整体画像水位视为 ID 水位，不得仅放宽同时间规则或仅保护 ID。

#### Scenario: 已修复后迟到历史任务
- **WHEN** 历史或未验证来源尝试改写已严格验证组合的冲突字段
- **THEN** 系统拒绝部分回退或先进行当前验证，不仅凭更晚比赛时间覆盖

#### Scenario: 未验证的旧身份
- **WHEN** 旧身份没有严格验证来源标记
- **THEN** 系统保留原历史兼容规则，不把普通刷新时间视为严格证明

### Requirement: 已收录角色失败查询支持有界自愈

系统 MUST 维持既有路由、响应格式和本地 identity_only 边界，在可恢复的参数/空画像错误后有限尝试已知候选。系统 MUST NOT 新增持久任务、领域对象、字段、集合、worker 或页面轮询；候选发现不得在请求中扫描历史全集。

此处“不新增字段”指Mongo业务schema，不禁止本计划明确审批的唯一默认关闭发布配置。新增恢复探测与ID发布 MUST 在首次CLI试点前保持关闭；关闭 MUST NOT 解除仓储安全保护。

#### Scenario: 当前角色健康
- **WHEN** 当前 ID 或有效成功缓存可用且身份一致
- **THEN** 系统保留当前 ID，不为历史差异额外探测

#### Scenario: 同角色并发与候选探测
- **WHEN** 同进程多个请求查询一个待恢复角色
- **THEN** 系统合并探测并有界冷却，单轮最多五个逻辑上游调用，线程重试不伪称已停止

#### Scenario: 无候选、超时、鉴权或限流
- **WHEN** 无可信候选或上游不可用/超时/鉴权失败/限流
- **THEN** 系统停止本轮、保留明确失败，不伪造零场或无限重试

#### Scenario: 超时但底层HTTP仍在途
- **WHEN** 请求deadline已到而线程内HTTP尚未结束
- **THEN** 探测许可保持占用直到实际完成，其他角色不叠加在途请求，迟到结果不发布

#### Scenario: 已验证组合之后再次迁移
- **WHEN** 新证据需要改变受保护server/name/zone
- **THEN** 本期ID-only流程保守列未解决，不部分迁移或偷偷扩大写权限

### Requirement: 存量恢复默认只读并可条件回滚

系统 MUST 提供默认只读盘点/核验，保留所有不同候选。显式更新 MUST 备份成功、重新实时验证后立即 CAS，不能直接发布旧 verify 结果；结果必须按去重输入数量守恒。

#### Scenario: 旧证据候选仍有效
- **WHEN** 最新来源等于当前画像但较旧来源包含不同候选
- **THEN** 候选不会被最新单一来源丢弃，实时核验决定是否可用

#### Scenario: 写前备份失败或旧结果过期
- **WHEN** 备份/归档失败或 apply 仅有旧 verify 结果
- **THEN** 系统不写身份，要求重新验证或修复操作条件

#### Scenario: 回滚遇到后续合法更新
- **WHEN** 本次更新的 after-image 已不匹配
- **THEN** 系统跳过冲突而不覆盖新资料；匹配者仅恢复本次字段和原缺失状态

### Requirement: TDD 与受控生产发布必须完成门禁

交付 MUST 包含有效 Red/Green/Refactor、子 agent 开发、独立子 agent review、隔离 Mongo/Python3.9 验证、绿色 commit、制品/备份校验、受控容器重启及线上真实验收。计划批准前 MUST NOT 开发或操作生产。

#### Scenario: 发布与线上试点
- **WHEN** 测试/review/commit门禁通过并完成生产预检备份
- **THEN** 先验证生产基线与制品overlay组合，首次重启保持新自动恢复关闭，CLI试点通过再第二次重启启用；所有独立writer实际重载后才恢复同步

#### Scenario: 缺证据角色与未完成验收
- **WHEN** 某角色无证据、上游无战绩或公开 API 未验收成功
- **THEN** 系统单列原因，不把候选、写入成功或部署成功等同全体用户恢复
