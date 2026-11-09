# JJC 排名统计成员强制重新入队并从队首处理

状态：用户已确认方案，并要求 TDD 实现及完成后子 agent 评审；执行细节见 tasks.md。

## Why

已有 priority >= 1 的跳过规则把排队去重和跨轮刷新混在一起，使上榜角色在失败、冷却、已排队时可能不接受新一轮请求；priority=1 也无法使排名批次位于高优先级或旧排名批次之前。

## What Changes

以统计运行标识去重，仅合并同一轮重复触发，每一轮独立申请重新同步。排名请求原子更新现有角色任务，非同步中角色立即 queued 并加入队首段；同步中角色合并为释放后的一次重排。领取、排位计算、队列分页统一排序口径。保持 disabled、全局暂停和租约保护。详见 design.md 与 00-requirement.md。

## Impact

涉及 ranking service、同步 repo、worker 释放与租约恢复、Mongo 排序索引、队列展示与位置计算及对应回归测试。新增请求和队首排序元数据须更新 database-design.md；实际行为落地后同步 PROJECT_CONTEXT.md、runbook 和规格基线。既有未提交的身份恢复、离线统计等改动保留。

## Approval

用户已确认方案并要求按 TDD 细化实现；本次按 tasks.md 推进，完成后由子 agent 独立审阅。用户随后已明确授权 commit 与发布；已完成，见 deployment.md。
