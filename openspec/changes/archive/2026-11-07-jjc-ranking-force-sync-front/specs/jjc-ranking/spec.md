## ADDED Requirements

### Requirement: 每轮排名统计触发角色重新同步

系统 MUST 对每轮排名统计范围内的有效角色提交独立同步请求；同轮去重不得抑制下一轮刷新。心法未知 MUST NOT 阻止身份有效角色入队。

#### Scenario: 角色冷却、完成或失败
- **WHEN** 新一轮排名统计包含 cooldown、exhausted 或 failed 角色
- **THEN** 该角色立即进入 queued，不等待角色 next_sync_after
- **AND** 其最新排名批次位于普通待处理队列之前

#### Scenario: 角色已排队
- **WHEN** 新一轮排名统计包含 queued 角色
- **THEN** 更新同一条任务至最新排名批次队首段，不重复建任务

#### Scenario: 角色正在同步
- **WHEN** 新一轮排名统计包含 syncing 角色
- **THEN** 保留当前租约，持久化最新待重排请求
- **AND** 当前执行释放或租约恢复后，合并请求使角色再同步一次

#### Scenario: 同轮重复触发及复用缓存的下一轮
- **WHEN** 同轮即时入口、保存入口或多个统计分组重复包含同一角色
- **THEN** 只提交一个有效请求
- **AND** 下一次实际统计即使 cache_time 相同也可重新提交

#### Scenario: 禁用、全局暂停及仅读页面
- **WHEN** 角色 disabled、系统全局暂停或用户仅读已保存快照
- **THEN** 分别保持禁用、暂停执行或只读行为
