# JX3Bot Agent Guide

本文件只提供 agent 的最小入口。详细规则、架构和运行步骤拆分到 `docs/`，避免单文件失真。

## 你在维护什么

- 这是一个基于 NoneBot2 + OneBot V11 的剑网 3 QQ 机器人。
- 入口是 `bot.py`，同时挂载消息插件和 HTTP API。
- 当前代码已经从“单文件插件”演进为分层结构，新增功能应优先放入现有层次，而不是继续堆进 `src/plugins/jx3bot.py`。

## 开始之前先读

1. `README.md`
2. `project-architecture.md`
3. `project-roadmap.md`
4. `project-history.md`
5. `docs/design-docs/index.md`
6. `docs/references/index.md`
7. `docs/exec-plans/index.md`
8. `docs/tasks/all-tasks.md`

如果任务只涉及部署，再补读 `README-Docker.md`。

## 当前真实结构

- `bot.py`: NoneBot 启动入口，注册 OneBot 适配器与 HTTP 路由。
- `src/plugins/`: 消息入口层，只做命令匹配、参数提取、调用 service、发送消息。
- `src/plugins/jx3bot_handlers/`: 各命令 handler 注册与薄逻辑。
- `src/services/jx3/`: 业务编排层，负责查询流程、缓存策略、仓储调用。
- `src/infra/`: 外部系统适配层，如 HTTP、截图、jx3api 请求封装。
- `src/renderers/`: 模板渲染、图片生成、消息输出辅助。
- `src/storage/`: 存储适配与工厂。
- `src/api/routers/`: 对外 HTTP API。
- `templates/`, `mpimg/`, `data/`: 模板、缓存图片、运行数据。

## 强约束

- 依赖方向固定为 `plugins -> services -> infra/storage`，`utils` 只能被依赖，不能反向引用上层。
- `services` 不得直接依赖 NoneBot 事件对象、`MessageSegment` 或发送消息。
- `renderers` 只负责渲染，不写业务决策。
- 新增外部调用时，优先补到 `src/infra/`，不要在 handler 或 service 中直接散写请求。
- 涉及 `groups.json`、订阅、服务器别名缓存时，统一走 `src/storage/` 和对应 repo，不新增裸 `open(...)` 写法。
- 秘钥、票据、Cookie、邮箱、内网地址不得硬编码进代码和文档。

## 文档更新规则

- 改动启动方式、端口、环境变量时，同时更新 `README.md`、`README-Docker.md`、`docs/references/runbook.md`。
- 改动模块边界、目录职责时，同时更新 `project-architecture.md` 和 `docs/exec-plans/active/refactor-plan.md`。
- 改动 API 路由时，同时更新 `README.md` 中的接口说明。
- 改动手工验证路径时，同时更新 `docs/references/runbook.md` 的回归清单。

## 常用验证

- 本地启动: `python bot.py`
- 插件快速检查: `nb plugin list --json`
- 手工脚本: `python test_tuilan_match_history.py`

外部接口较多，很多验证依赖在线服务。无法离线证明正确时，至少补充手工回归路径。
