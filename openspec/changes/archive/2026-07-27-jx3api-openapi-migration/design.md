# JX3API OpenAPI 迁移方案文档

## Problem

旧 `/data/...` 路由整体失效，且部分新端点更改了响应字段。只替换 URL 会导致烟花、百战、骗子、科举、日常和开服状态展示错误。

## Goals

- 路径迁移后，现有可替代命令可继续工作。
- 字段转换集中于基础设施边界并由单元测试固定。

## Non-Goals

- 不为上游未提供替代的能力伪造数据。

## Current State

`config.py` 与多个 handler 硬编码 JX3API URL。`src/infra/jx3api_get.py` 是大多数角色查询的统一 GET 入口，但新闻、状态和日常仍有独立请求。`server_resolver.py` 在本地目录未命中时调用已下线的主服映射接口。

## Proposed Solution

新增 `src/infra/jx3api_compat.py`，只处理响应数据：

- 烟花项把 `receiver/mapName/firework` 投影为历史消费者使用的 `receive/map_name/name`。
- 角色百战把 `zone/server/globalId/skillEnergy/skillStamina` 投影为 `zoneName/serverName/globalRoleId/gameEnergy/gameStamina`。
- 科举项把 `index` 补为兼容的 `id`。
- 骗子扁平项转换为历史格式化器所需的 `server/tieba/data[]`。
- 日常把 `lucky/weekly` 投影为 `luck/team`，其中 `weekly.conn/raid` 组成三段 `team`。
- 开服状态把文本状态映射为兼容的数值状态，并补入本次采样时间；监控只需要稳定比较值和时间戳。

在 HTTP 入口响应成功后按 URL 调用兼容适配。配置和硬编码 URL 统一迁移到当前端点。区服主服解析仅查本地 Mongo 缓存，缓存 miss 时返回原值。

## Data and Storage Impact

不新增集合或字段。已有 `server_master_cache` 只继续读取历史别名映射，停止向已下线上游补充数据。状态监控缓存仍保存既有数值状态和时间戳。

## API and UI Impact

QQ 命令语法不变。无参数 `百战` 改为“官方接口暂未提供百战总览”；角色百战继续返回图片。其他命令继续使用既有模板和文案。

## Risks and Rollback

上游字段可能再次变化；适配器在未知字段缺失时保留空值而不抛异常，并由接口错误文案反馈。回滚时恢复 URL 与兼容适配调用即可，但旧 URL 已失效，回滚仅用于排查而不恢复功能。

## Confirmation

2026-07-27，用户确认“完整迁移 + 明确降级”方案。
