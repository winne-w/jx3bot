# 执行计划入口

本文为 OpenSpec 任务入口，详细、持续维护的唯一执行计划见 [02-execution-plan.md](02-execution-plan.md)。用户于 2026-11-25 确认方案并要求输出执行计划，已确认执行计划；本地实现、验证及独立 review 完成，未部署。

## Purpose / Big Picture

取消心法查询的 JX3API 兜底，保留推栏、缓存和本地当前赛季胜场推断。

## Progress

- [x] 方案已确认，详细执行计划已形成。
- [x] 执行计划确认。
- [x] T1 测试先行与基线。
- [x] T2 实现及装配收敛。
- [x] T3 双版本定向回归及独立 review。
- [x] T4 文档、规格与本地交付。

## Surprises & Discoveries

update_kungfu_cache 的唯一生产调用位于将被移除的分支；已有测试依赖旧兜底。实际 WSL 仓库有大量既有 dirty 改动，须保护。

## Decision Log

方案确认范围和具体输出约定见详细计划，未授权发布、重启、提交或推送。

## Outcomes & Retrospective

本地实现及验证完成，双版本各372项通过、独立增量review通过；详见05-acceptance.md。未部署。

## Context and Orientation

实际仓库 /home/songjingjing/codes/jx3bot，核心文件 jjc_ranking.py 和 singletons.py；调用清单和测试清单详见详细计划。

## Plan of Work

T1 测试子 agent 先补行为测试；T2 主 agent 实现并调整构造；T3 独立 review 子 agent 只读复核、主 agent 整合回归；T4 同步文档交付。职责与依赖顺序详见详细计划。

## Concrete Steps

详细计划列出真实运行路径、完整 unittest 模块、双版本检查、扫描与增量回滚方式；执行时以其为准。

## Validation and Acceptance

心法失败场景零 JX3API 请求、零 JX3API history 心法采用；缓存和推栏成功、本地胜场约束、未知角色同步资格保持。全部命令及证据限制见详细计划。
