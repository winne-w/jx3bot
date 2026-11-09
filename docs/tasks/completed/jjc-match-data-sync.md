# Task: JJC Match Data Sync

状态：已完成
更新时间：2026-05-07

## 目标

- 通过 QQ 管理员命令维护 JJC 对局同步角色队列
- 通过官方推栏/JJC 接口按角色同步本赛季 3v3 对局历史与对局详情
- 复用现有 `jjc_match_detail` 存储链路保存详情
- 从已保存详情中发现更多角色并回填同步队列
- 支持服务重启后恢复过期租约，不因中断提前推进同步水位

## 范围

- `src/plugins/jx3bot_handlers/jjc_match_data_sync.py`
- `src/services/jx3/jjc_match_data_sync.py`
- `src/storage/mongo_repos/jjc_sync_repo.py`
- `src/infra/mongo.py`
- `docs/design-docs/database-design.md`
- `docs/references/runbook.md`

## 约束

- 第一阶段只做数据同步、去重、续拉和任务状态管理
- 不做职业分布、胜率、强弱分析或统计 API
- 不新增 HTTP 管理入口，入口只放 QQ 管理命令
- 同步任务不自动常驻启动，只由管理员命令显式触发一轮
- `full_synced_until_time` 只能在角色本轮完整同步成功后推进
- 对局详情失败时本角色同步失败，避免水位跳过未保存详情

## 完成标准

- 管理员可以添加角色、触发同步、查看状态、暂停/恢复、重置角色
- 非管理员无法执行 `/jjc同步*` 管理命令
- 新角色可回溯本赛季历史，已有水位角色可增量同步
- `syncing` / `detail_syncing` 过期租约可恢复
- 详情保存后能回填双方角色到同步队列
- 新增同步 service/repo 单测和现有 JJC 详情快照回归通过

详细计划：`docs/exec-plans/completed/jjc-match-data-sync-plan.md`
