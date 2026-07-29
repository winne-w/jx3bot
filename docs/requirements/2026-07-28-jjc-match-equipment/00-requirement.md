# 最近 3v3 对局装备查询需求澄清

## Background

JX3API 已下线通用角色装备属性接口，现有 `属性/装分` QQ 命令只能提示不可用。推栏 3v3 对局详情仍提供参赛角色在对局发生时的装备、精炼、附魔、五彩石、装分拆分和属性面板，可作为明确标注时效的替代查询能力。

## Goals

- 将 `属性/装分 <服务器> <角色>` 改为展示目标角色最近一场 3v3 对局的完整装备与属性快照。
- 优先从本地 `role_identities` 按服务器和角色名解析身份；缺失或字段不完整时调用 JX3API `/role/detail` 补齐角色 ID 和大区。
- 将 JX3API 成功补齐的身份字段写回 `role_identities`，减少后续外部查询。
- 在结果中明确展示该数据是“最近 3v3 对局装备快照”及对局时间。

## Non-Goals

- 不提供当前实时角色装备或 PVE 装备查询。
- 不从本地历史已同步对局回退读取装备。
- 不新增对外 HTTP API 或静态页面。

## Scope

本需求影响 QQ `属性/装分` 命令、JX3 service、JX3API/推栏调用编排、角色身份仓储写入、装备图片模板及对应单元测试和运行手册。

## Business Rules

1. 身份解析按同服同名精确匹配本地 `role_identities`；只有同时具备可用 `role_id`（可兼容 `game_role_id`）和 `zone` 才可直接进入推栏链路。
2. 本地未命中或字段不足时，调用 JX3API `/role/detail`，取得 `roleId`、`zoneName`、`globalId` 等信息后合并回写本地身份。
3. 使用推栏 `/role/indicator` 取得 `SK01-...` 格式的 `global_role_id`，再用 `/3c/mine/match/history` 获取对局；仅选择 `pvp_type=3` 且 `start_time` 最新的一场。
4. 使用 `/3c/mine/match/detail` 读取详情，并按规范化 `server + role_name` 精确定位目标玩家，不得使用同名或跨服兜底。
5. 查询失败、无 3v3 对局、详情缺少目标玩家或装备时，直接给出原因明确的提示，不读取本地历史快照。

## Dependencies

- MongoDB：`role_identities`。
- JX3API：`/role/detail`，需要现有站点 token。
- 推栏：`/role/indicator`、`/3c/mine/match/history`、`/3c/mine/match/detail`，使用已有签名请求适配。
- QQ 命令、Jinja 图片模板与截图发送能力。

## Open Questions

无。用户已确认本需求的身份补齐、无历史兜底和完整面板展示口径。

## Confirmation

2026-07-28：用户确认本地优先、JX3API 补齐并回写身份；展示完整装备和属性面板；无可用数据直接提示。

2026-07-29：用户确认装分只显示总装分，计算为推栏装备分、精炼分和五彩石分之和；不展示三项拆分、五彩石槽位或武器五彩石属性。属性仅展示指定且上游实际存在的字段；缺失字段不展示。保留装备名称、品质、精炼和附魔文字。
