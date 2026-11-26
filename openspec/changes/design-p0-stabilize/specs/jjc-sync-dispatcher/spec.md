# JJC 同步自动补队列 Delta（design-p0-stabilize）

## ADDED Requirements

### Requirement: 非终态退避对局中断角色同步时按退避时间延迟重排

当角色同步遇到处于失败退避期（`status="failed"` 且 `detail_retry_after > now`）或其他 worker 正在持租（`status="syncing"` 且 `lease_expires_at > now`）的对局详情时，系统 MUST 中断当前角色以保护同步水位不越过未完成对局，且 MUST 将角色置为 `cooldown` 并设置对应的 `next_sync_after`，交由 dispatcher 在到期后重新补入 `queued`，不得无冷却立即重排导致高频重复翻页。

#### Scenario: 角色命中处于失败退避期的对局详情
- **WHEN** worker 翻页发现某场对局领取返回空且同步状态为 `failed`、`detail_retry_after > now`
- **THEN** 当前角色释放租约并转入 `cooldown`，`next_sync_after` 设为该对局的 `detail_retry_after`，角色既有水位保持不变

### Requirement: 内置同步 worker 与 dispatcher 异常退出后自动退避恢复

系统 MUST 对内置后台同步 worker 与 dispatcher 提供常驻监督循环；遇到非取消异常或错误退出时按有界指数退避自动重启，收到取消信号时干净退出。

#### Scenario: 后台 worker 遇到瞬时异常退出
- **WHEN** `run_worker` 抛出未预期运行时异常且未收到停止信号
- **THEN** 运行时记录异常日志并在退避等待后重新拉起该 worker 槽位
