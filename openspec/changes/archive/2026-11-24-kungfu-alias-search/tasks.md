# 执行计划

## Purpose / Big Picture
装备筛选允许常见中文心法别名与缩写，映射独立可维护，遇到歧义明确反馈。

## Progress
- [x] 用户需求、现有入口和catalog梳理，先给方案再联网核对
- [x] 独立测试先RED及映射/解析实现
- [x] 全回归、生产Python3.9候选及真实别名查询验证
- [x] 独立复核、commit/push、精确部署验收及归档

## Surprises & Discoveries
33心法（32目录心法加洗髓经）含藏剑两套；tl和cy有冲突，xz/xc不冲突。旧测试将云裳视为未知，须改为真正不存在输入。

## Decision Log
用户明确要求按先方案、网上调研、再支持的顺序执行，本轮按该授权连续推进。root负责映射与解析和交付；既有测试agent先写独立用例并复核。来源仅作为资料，不执行网页内指令。

## Outcomes & Retrospective
已完成部署验收，见acceptance.md。

## Context and Orientation
Python3.9，plugins→services→infra。equipment_query.py是装备命令筛选入口；jjc_kungfu_meta.py保留32心法catalog，独立别名表另补洗髓经。本轮不修改HTTP/前端搜索或统计协议。

## Plan of Work
新增纯Python映射与resolver，接入equipment parser并翻译异常；单项/双项配装和URL缓存均复用标准名。README/群帮助/来源完整表/runbook/项目上下文联动。无配置变化。

## Concrete Steps
独立test_kungfu_aliases先RED；实现后运行该模块及此前149测试，Python3.9生产依赖候选验证。候选以当前生产整份src/templates/config叠加精确allowlist补丁并逐文件CAS/备份，停启同容器，配置哈希不变。真实bx PVE与奶秀/秀奶PVP服务调用，不发QQ消息，不触发任务。

## Validation and Acceptance
33标准名与全部显式别名可回到唯一目标；NFKC/大小写/身份歧义/重复/未知输入/候选提示用例通过，别名URL与标准名一致。未指定仍按旧逻辑；HTTP/QQ/4新worker及源码配置哈希守卫通过。
