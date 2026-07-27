# JX3API OpenAPI 迁移需求澄清

## Background

JX3API 已移除仓库仍在使用的 `/data/...` 路径。当前 QQ 战绩命令因此返回 `App.Data.Arena_Recent 不存在`。对官方 OpenAPI 与真实响应的审计还发现多处字段变更。

## Goals

- 将全部仍在使用的 JX3API 调用迁移到官方当前 OpenAPI 路径。
- 在基础设施层归一化已确认变化的响应字段，保持既有 QQ 命令和模板的展示语义。
- 将无官方等价接口的百战总览和在线主服解析改为明确、可理解的降级行为。
- 为路径映射和字段适配建立离线回归测试。

## Non-Goals

- 不修改推栏 `m.pvp.xoyo.com`、JX3BOX、万宝楼等非 JX3API 依赖。
- 不新增 Mongo 集合、迁移或持久化格式。
- 不恢复上游已停止提供的百战总览或主服映射数据。

## Scope

影响 QQ 查询、状态监控、启动区服目录更新和相关配置。用户命令保持不变；`百战` 无参数改为明确提示，`百战 <角色>` 与 `百战 <区服> <角色>`继续提供角色百战信息。

## Business Rules

- 所有 JX3API URL 使用当前 OpenAPI 定义的根路径，不再使用 `/data` 前缀。
- API 协议兼容只能在 `src/infra/` 中适配；service、handler、模板继续使用稳定字段。
- 当用户输入区服不在本地区服目录中时，不再访问已下线的主服映射接口；直接提示输入当前正式区服名。
- 无参数百战不调用不存在的上游端点。

## Dependencies

- JX3API OpenAPI：`https://www.jx3api.com/openapi`
- 本地 `runtime_config.json` 的 `TOKEN` 和 `TICKET`
- `server_data.json` 的本地区服目录

## Open Questions

- 无。用户已确认采用“完整迁移 + 明确降级”。

## Confirmation

2026-07-27，用户确认按上述方案直接在当前分支实施。
