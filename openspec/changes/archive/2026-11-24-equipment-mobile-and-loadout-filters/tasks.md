# Execution Plan

## Purpose / Big Picture
让手机图片主文字可读且简洁，支持指定心法与配装类型。

## Progress
- [x] 读取官方OpenAPI与实际records/detail结构
- [x] 选择规则澄清与独立测试
- [x] 查询编排/handler/配置及移动展示实现
- [x] 本地/生产依赖回归、真实筛选及375px阅读视觉验证
- [x] 独立复核、commit/push、精确部署与运行验收

## Surprises & Discoveries
/detail必填kungfu+type，records含跨赛季三种组合；真实云裳PVP面板含percent，可直接正确显示24.9%会心、175%会效。首次20秒外呼超时，有限重试只读侦察成功，不算产品结果。

## Decision Log
root负责equipment_query.py、handler/config/compat、文档/集成部署；feature子agent负责equipment_mobile.py、role_queries调用及模板；测试子agent负责独立filter测试与最后复核。可选选择规则问题未阻塞独立样式工作。

## Context and Orientation
Python3.9+，plugins→services→infra/storage。原service/icon helper保留图标缓存/回退，新视图不用新增图片生成依赖。

## Plan of Work
先完成类型/心法解析和筛选fixture，确保所有类型/别名、缺参、多候选、业务错误、结果冲突及缓存隔离。样式用真实治疗PVP与攻击PVE各一图，对比参考结构及手机375宽有效字号；保留所有装备，实际行无横向越界，不用隐藏装备缩短图片。

## Concrete Steps
运行既有110回归及新增模块，Python3.9真实依赖编译/测试。候选依当前完整生产源码叠加本次受审补丁，config仅API及装备正则；原组合hash/备份/停启/条件恢复，不覆盖原配置和其他功能。只读真实查询，不向QQ群发消息。

## Validation and Acceptance
装备名有效手机字号≥14px、核心数字≥16px（375宽），宽760；图片不截断全部13件，12代表性指标与源一致。无筛选原命令、显式server、心法/type单独与共同筛选均可解释，错误不冒充成功或当前配置；不同配装不串缓存。QQ/HTTP/4fresh worker及配置守卫通过。

## Outcomes & Retrospective
已完成并部署；详见acceptance.md。
