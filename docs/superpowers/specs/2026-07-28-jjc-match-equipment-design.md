# 最近 3v3 对局装备快照设计

## Architecture

`属性/装分` matcher 保持表现层职责，只负责解析服务器和角色名、调用新的 JJC 装备查询 service、将成功结构交给模板渲染。service 负责身份解析、JX3API 补齐、推栏请求、最新对局选择和目标玩家精确匹配；Mongo 和外部 HTTP 均通过既有 repo/client 边界访问。

## Data Flow

1. 查询 `role_identities` 的同服同名最佳身份。
2. 如果缺少 `role_id`（兼容 `game_role_id`）或 `zone`，调用 JX3API `/role/detail` 并合并回写身份。
3. 用 `role_id + zone + server` 请求推栏 `/role/indicator`，取 `SK01-... global_role_id`。
4. 请求推栏 `/3c/mine/match/history`，过滤 `pvp_type=3`，按 `start_time` 倒序选最新 match ID。
5. 请求 `/3c/mine/match/detail`，在两队玩家中用规范化服务器和角色名精确定位目标角色。
6. 将装备、装分和属性转换为渲染模型，渲染图片并发送。

## Error Handling

身份未找到、JX3API 补齐失败、indicator 缺少 global role ID、没有 3v3、详情不存在目标玩家或 `armors` 为空均为终态错误。所有错误均明确告知用户，不用本地历史详情兜底。

## Testing

测试覆盖本地身份命中、JX3API 补齐与仓储回写、最近对局按对局时间选择、跨服同名不匹配、无对局/无装备等终态错误及渲染模型转换。现有 JJC matcher、身份仓储和对局详情测试持续回归。
