# JX3Bot Agent Guide

本文件提供 agent 在本仓库工作的统一入口说明。`AGENTS.md` 与 `CLAUDE.md` 应保持同一套事实口径；详细规则、架构和运行步骤拆分到 `docs/`，避免单文件失真。

## 你在维护什么

- 这是一个基于 NoneBot2 + OneBot V11 的剑网 3 QQ 机器人，同时暴露 FastAPI HTTP API。
- 入口是 `bot.py`，负责启动 NoneBot、注册 OneBot V11 适配器，并挂载 HTTP 路由。
- 插件从 `src/plugins/` 自动加载。
- 当前代码已经从“单文件插件”演进为分层结构，新增功能应优先落入现有层次，而不是继续堆进 `src/plugins/jx3bot.py`。

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

## 常用命令

```bash
# 启动
python bot.py

# 容器入口（启动 mpimg 静态服务 + bot）
bash start.sh

# Docker
docker compose up --build -d

# 验证插件加载
nb plugin list --json

# 手工测试推栏接口
python test_tuilan_match_history.py

# 类型注解兼容性检查（Python 3.9）
python -m py_compile src/api/routers/<router>.py
python -m py_compile <相关 service/storage 文件>
```

## 当前真实结构

- `bot.py`: NoneBot 启动入口，注册 OneBot 适配器与 HTTP 路由。
- `src/plugins/`: 消息入口层，只做命令匹配、参数提取、调用 service、发送消息。
- `src/plugins/jx3bot_handlers/`: 各命令 handler 注册与薄逻辑。
- `src/services/jx3/`: 业务编排层，负责查询流程、缓存策略、仓储调用。
- `src/services/jx3/singletons.py`: 共享对象装配，只做实例组装（Jinja env、repo、service 实例），不追加新的业务逻辑。
- `src/infra/`: 外部系统适配层，如 HTTP、截图、jx3api 请求封装。
- `src/renderers/`: 模板渲染、图片生成、消息输出辅助。
- `src/storage/`: 存储适配与工厂。
- `src/api/routers/`: 对外 HTTP API。
- `templates/`, `mpimg/`, `data/`: 模板、缓存图片、运行数据。

## 分层架构与依赖方向

依赖方向固定为：`plugins -> services -> infra/storage`，`utils` 只能被依赖，不能反向引用上层。

| 层 | 目录 | 职责 | 禁止 |
|---|---|---|---|
| 入口 | `bot.py` | 启动、注册适配器、挂载 API | — |
| 消息表现 | `src/plugins/`, `src/plugins/jx3bot_handlers/` | 命令匹配、参数提取、调用 service、组织回复 | 写业务逻辑、散写外部请求 |
| 业务编排 | `src/services/jx3/` | 查询流程、缓存策略、多数据源聚合 | 依赖 NoneBot 事件/Message/Bot；发送消息；渲染细节 |
| 外部适配 | `src/infra/` | HTTP、截图、第三方 API 封装 | 写领域规则、命令分发 |
| 存储 | `src/storage/` | 统一存储抽象与访问 | 存储抽象中写业务逻辑 |
| 渲染 | `src/renderers/` | 模板渲染、图片生成 | 写业务判断分支 |
| HTTP API | `src/api/routers/` | FastAPI 路由、参数校验、调用 service | 直接读写文件、调用截图/消息发送 |

## 强约束

- 运行时基线是 `Python 3.9+`。新增类型注解必须兼容 Python 3.9，不要在 FastAPI/Pydantic 会解析的代码路径里使用 `str | None`、`dict[str, Any] | None` 这类 `|` 联合写法，统一改用 `typing.Optional[...]`、`typing.Union[...]`。其他位置也尽量不用。
- `services` 不得直接依赖 NoneBot 事件对象、`Bot`、`Event`、`MessageSegment` 或发送消息。
- `renderers` 只负责渲染，不写业务决策。
- 新增外部调用时，优先补到 `src/infra/`，不要在 handler 或 service 中直接散写请求。
- 配置优先来自环境变量和 `config.py`，秘钥、票据、Cookie、邮箱、内网地址不得硬编码进代码和文档。
- 群配置、订阅、服务器别名缓存、运行时缓存统一走 `src/storage/`，当前优先使用 MongoDB 相关 repo（如 `src/storage/mongo_repos/`），不新增裸 `open(...)` 或 JSON 文件读写。
- JJC 统计文件写入 `data/jjc_ranking_stats/<timestamp>/summary.json`，明细按需拆分在 `details/` 子目录。

## API 响应格式

所有 HTTP API 返回统一结构：

```json
{"status_code": 0, "status_msg": "success", "data": {}}
```

路由注册见 `src/api/__init__.py`，响应构造走 `src/api/response.py`。

## 文档更新规则

- 改动启动方式、端口、环境变量时，同时更新 `README.md`、`README-Docker.md`、`docs/references/runbook.md`。
- 改动模块边界、目录职责时，同时更新 `project-architecture.md` 和 `docs/exec-plans/active/refactor-plan.md`。
- 改动 API 路由时，同时更新 `README.md` 中的接口说明。
- 改动手工验证路径时，同时更新 `docs/references/runbook.md` 的回归清单。

## 已知遗留问题

- 多处仍使用 `print()` 而非结构化日志，详见 `docs/exec-plans/active/refactor-plan.md`。新代码使用 `nonebot.logger` 或 `loguru`，不要继续新增 `print()`。
- `src/utils/defget.py` 仍有向 handler 的兼容导入，涉及相关改造时注意依赖方向不要继续恶化。

## 常用验证

- 本地启动: `python bot.py`
- 插件快速检查: `nb plugin list --json`
- 手工脚本: `python test_tuilan_match_history.py`
- 改过 FastAPI 路由、Pydantic 会解析的函数签名或新增类型注解后，至少执行一次 `python -m py_compile <相关文件>`，重点确认没有 Python 3.9 注解兼容问题。

外部接口较多，很多验证依赖在线服务。无法离线证明正确时，至少补充手工回归路径。
