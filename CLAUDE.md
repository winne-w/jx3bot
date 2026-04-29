# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概要

基于 NoneBot2 + OneBot V11 的剑网3 QQ 机器人，同时暴露 FastAPI HTTP API。入口是 `bot.py`，插件自动从 `src/plugins/` 加载。

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

## 分层架构与依赖方向

依赖方向固定为：**`plugins → services → infra/storage`**，`utils` 只能被依赖，不能反向引用上层。

| 层 | 目录 | 职责 | 禁止 |
|---|---|---|---|
| 入口 | `bot.py` | 启动、注册适配器、挂载 API | — |
| 消息表现 | `src/plugins/`, `src/plugins/jx3bot_handlers/` | 命令匹配、参数提取、调用 service、组织回复 | 写业务逻辑、散写外部请求 |
| 业务编排 | `src/services/jx3/` | 查询流程、缓存策略、多数据源聚合 | 依赖 NoneBot 事件/Message/Bot；发送消息；渲染细节 |
| 外部适配 | `src/infra/` | HTTP、截图、第三方 API 封装 | 写领域规则、命令分发 |
| 存储 | `src/storage/` | 统一存储抽象与访问 | 存储抽象中写业务逻辑 |
| 渲染 | `src/renderers/` | 模板渲染、图片生成 | 写业务判断分支 |
| HTTP API | `src/api/routers/` | FastAPI 路由、参数校验、调用 service | 直接读写文件、调用截图/消息发送 |

共享对象装配：`src/services/jx3/singletons.py` 只做实例组装（Jinja env、repo、service 实例），不追加新的业务逻辑。

## 关键约束

- **Python 3.9+**：FastAPI 路由、Pydantic 解析的函数签名、模块级类型声明中，禁止使用 `X | None`、`dict[str, Any] | None` 等 `|` 联合写法，统一用 `typing.Optional[...]`、`typing.Union[...]`。其他位置也尽量不用。
- `services` 不得直接依赖 `nonebot.adapters.*`、`Bot`、`Event`、`MessageSegment`。
- 配置优先来自环境变量和 `config.py`，秘钥/token/Cookie/邮箱/内网地址不得硬编码。
- 新增外部调用先补到 `src/infra/`，不要在 handler/service 中散写请求。
- 群配置、订阅、服务器别名缓存、运行时缓存统一走 MongoDB（`src/storage/mongo_repos/`），不新增裸 `open(...)` 或 JSON 文件读写。
- JJC 统计文件写入 `data/jjc_ranking_stats/<timestamp>/summary.json`，明细按需拆分在 `details/` 子目录。

## API 响应格式

所有 HTTP API 返回统一结构：
```json
{"status_code": 0, "status_msg": "success", "data": {}}
```

路由注册见 `src/api/__init__.py`，响应构造走 `src/api/response.py`。

## 文档联动规则

- 改动启动方式/端口/环境变量 → 更新 `README.md`、`README-Docker.md`、`docs/references/runbook.md`
- 改动模块边界/目录职责 → 更新 `project-architecture.md`、`docs/exec-plans/active/refactor-plan.md`
- 改动 API 路由 → 更新 `README.md` 中的接口说明
- 改动回归路径 → 更新 `docs/references/runbook.md`

## 已知遗留问题

多处仍使用 `print()` 而非结构化日志（见 `docs/exec-plans/active/refactor-plan.md` 中的详细列表），`src/utils/defget.py` 仍有向 handler 的兼容导入。新代码使用 `nonebot.logger` 或 `loguru`，不要继续新增 `print()`。
