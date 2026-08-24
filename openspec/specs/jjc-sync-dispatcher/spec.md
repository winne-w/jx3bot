# JJC 同步自动补队列

## Requirements

### Requirement: 队列不足时自动补充到期角色

系统 MUST 在 queued 深度不足时，通过既有入队服务把到期角色补入队列。

#### Scenario: worker 空闲且存在到期角色
- **WHEN** queued 队列深度低于 dispatcher 阈值且候选角色已到期
- **THEN** dispatcher 以既有状态过滤和优先级语义将候选入队

### Requirement: dispatcher 不直接执行同步

系统 MUST 只负责入队，不得绕过 worker、租约或角色状态机直接同步角色详情。

#### Scenario: dispatcher 发现候选
- **WHEN** dispatcher 选中可入队角色
- **THEN** 它写入 queued 记录并由既有 worker 消费
