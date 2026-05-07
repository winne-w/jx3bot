# PROJECT_CONTEXT.md

本文件是仓库级项目上下文单一事实源。`AGENTS.md` 与 `CLAUDE.md` 不再重复维护项目说明；涉及仓库事实、架构、约束、验证、文档联动时，统一以本文件为准。

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
   - 数据库相关改动必须补读 `docs/design-docs/database-design.md`
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

## DDD 修改流程

以后修改项目时，默认按 DDD 思路推进：

1. 先设计用例：明确触发入口、参与角色、输入输出、业务规则、异常分支和验收标准。
2. 再修改代码：把领域规则放在 `services` 可编排的业务层或更内聚的领域对象中，入口层只做参数提取和调用，外部系统能力通过 `infra/storage/renderers` 适配。
3. 最后验证用例：针对设计用例逐项执行自动化或手工验证，说明覆盖到的正常路径、异常路径，以及无法离线验证的外部依赖。

如果现有代码尚未完全符合 DDD 分层，优先在本次改动范围内收敛边界，不为无关模块做大规模重构。

## 二阶段开发流程

以后修改本项目时，默认只要求区分“需求澄清与计划设计”和“按计划实现”两个阶段。该流程适用于实现、重构、排查修复、文档联动等仓库任务。所有代码改动必须先有对应计划文档作为依据；即使用户明确要求直接改代码，也必须先创建或更新 `docs/exec-plans/active/` 下的计划文档并同步 `docs/exec-plans/index.md`，再开始修改代码。只有纯问答、只读排查、运行验证命令、数据查询、git 操作、以及不改变仓库文件的临时诊断命令可不新增计划文档。

### 阶段 1：需求澄清与修改计划

目标：先把需求、边界、开发方案和验证方式想清楚，再进入实现。

执行规则：

1. 先与用户澄清需求，明确目标、入口、影响范围、非目标、兼容要求和回滚要求。
2. 生成详细修改计划，计划必须细化到具体开发方案设计，不能只写方向。
3. 计划需要覆盖：
   - 涉及的模块、文件和分层边界
   - 数据结构、存储集合、索引、迁移脚本和兼容策略
   - API、前端、定时任务、缓存、外部接口的改动点
   - 每个实施步骤的验证方式
   - 自动化测试、手工测试、数据回归和线上观察点
   - 风险、回滚方案和灰度/双写/fallback 策略
4. 阶段性计划写入 `docs/exec-plans/active/`，并同步更新 `docs/exec-plans/index.md`。
5. 阶段 1 默认只允许需求澄清、计划撰写、代码阅读和方案设计，不做业务代码实现；只有用户确认进入执行阶段后，才开始阶段 2。
6. 如果用户要求“直接改”“马上实现”或类似指令，仍需先补最小可执行计划文档；计划可简短，但必须明确变更文件、行为规则、验证命令和回滚方式。

### 阶段 2：按计划实现

目标：严格按阶段 1 的计划落地，并对照计划完成实现、验证和必要文档更新。

执行规则：

1. 按阶段 1 的计划逐项修改代码或文档，不随意扩大改动范围。
2. 每完成一个计划步骤，更新执行状态；涉及数据库、API、运行手册或架构边界的改动，按文档更新规则同步相关文档。
3. 完成后运行计划中定义的验证命令；无法离线验证的外部依赖，补充手工回归路径和风险说明。
4. 完成后给出实现结果、验证结果、未覆盖风险和后续建议。
5. 代码实现和验证完成但尚未提交时，计划仍保留在 `docs/exec-plans/active/`；只能在计划内记录“已实现/已验证/待提交”状态，不得提前移动到 `docs/exec-plans/completed/`。

如需把阶段 2 拆给子 agent 并行实现，使用全局 `subagent-implementation` skill；本项目文档不重复维护通用子 agent 调度细节。

## 强约束

- 运行时基线是 `Python 3.9+`。新增类型注解必须兼容 Python 3.9，不要在 FastAPI/Pydantic 会解析的代码路径里使用 `str | None`、`dict[str, Any] | None` 这类 `|` 联合写法，统一改用 `typing.Optional[...]`、`typing.Union[...]`。其他位置也尽量不用。
- `services` 不得直接依赖 NoneBot 事件对象、`Bot`、`Event`、`MessageSegment` 或发送消息。
- `renderers` 只负责渲染，不写业务决策。
- 新增外部调用时，优先补到 `src/infra/`，不要在 handler 或 service 中直接散写请求。
- 配置优先来自环境变量和 `config.py`，秘钥、票据、Cookie、邮箱、内网地址不得硬编码进代码和文档。
- 群配置、订阅、服务器别名缓存、运行时缓存统一走 `src/storage/`，当前优先使用 MongoDB 相关 repo（如 `src/storage/mongo_repos/`），不新增裸 `open(...)` 或 JSON 文件读写。
- 数据库设计以 `docs/design-docs/database-design.md` 为准。新增、删除、重命名集合或字段，调整索引、TTL、迁移脚本、存储归属时，必须同步更新该文档。
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
- 改动数据库集合、字段、索引、TTL、迁移脚本或存储 repo 时，同时更新 `docs/design-docs/database-design.md`。
- 改动手工验证路径时，同时更新 `docs/references/runbook.md` 的回归清单。
- 生成阶段性执行计划时，写入 `docs/exec-plans/active/` 并同步更新 `docs/exec-plans/index.md`；相关代码提交后，才可将计划移入 `docs/exec-plans/completed/` 并更新索引。

## 已知遗留问题

- 多处仍使用 `print()` 而非结构化日志，详见 `docs/exec-plans/active/refactor-plan.md`。新代码使用 `nonebot.logger` 或 `loguru`，不要继续新增 `print()`。
- `src/utils/defget.py` 仍有向 handler 的兼容导入，涉及相关改造时注意依赖方向不要继续恶化。

## 常用验证

- 本地启动: `python bot.py`
- 插件快速检查: `nb plugin list --json`
- 手工脚本: `python test_tuilan_match_history.py`
- 改过 FastAPI 路由、Pydantic 会解析的函数签名或新增类型注解后，至少执行一次 `python -m py_compile <相关文件>`，重点确认没有 Python 3.9 注解兼容问题。
- JJC 对局详情快照相关单测：
  ```bash
  python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration tests.test_scripts_jjc_snapshot
  python -m py_compile src/services/jx3/match_detail_snapshots.py src/storage/mongo_repos/jjc_match_snapshot_repo.py src/storage/mongo_repos/jjc_inspect_repo.py scripts/clear_jjc_match_detail_snapshot_cache.py scripts/verify_jjc_match_detail_snapshot_storage.py
  ```

外部接口较多，很多验证依赖在线服务。无法离线证明正确时，至少补充手工回归路径。
