# 开发决策指南

更新时间：2026-03-09

本文回答一个具体问题：新需求或改动进来时，代码应该落在哪一层，避免再次把仓库写回“单文件插件”。

## 先判断改动类型

### 消息命令改动

放置原则：

- 命令匹配和参数解析放 `src/plugins/` 或 `src/plugins/jx3bot_handlers/`
- 业务流程放 `src/services/jx3/`
- 图片和模板输出放 `src/renderers/`

不要做：

- 在 handler 内直接堆业务逻辑
- 在 handler 内直接拼第三方请求

### 新增 HTTP API

放置原则：

- 路由定义放 `src/api/routers/`
- 参数校验后直接调用 `services`
- 响应统一走 `src/api/response.py`

不要做：

- 在 router 内直接读写文件
- 在 router 内直接调用截图或消息发送逻辑

### 新增第三方接口

放置原则：

- 外部请求封装放 `src/infra/`
- 业务聚合和容错放 `src/services/`

不要做：

- 在插件、handler、router 中直接散写请求代码

### 新增持久化数据

放置原则：

- 存储抽象放 `src/storage/ports.py` 或对应 repo
- 具体适配实现放在 `src/storage/` 下的对应模块
- 业务层只依赖 repo 接口或门面，不直接依赖底层细节

不要做：

- 直接在业务代码里新增裸 `open(...)`
- 直接在 service 里拼底层存储查询细节

## 推荐实现路径

### 新增一个查询命令

1. 在 handler 注册命令和参数解析
2. 在 `services` 中新增一个返回结构化数据的函数或类方法
3. 如需调用外部接口，在 `infra` 增加适配
4. 如需图片输出，在 `renderers` 补模板或渲染函数
5. 更新 `docs/references/runbook.md` 的回归路径

### 新增一个定时任务

1. 调度入口放 `src/plugins/status_monitor/jobs.py`
2. 查询或聚合逻辑放 `services`
3. 告警或外发通道优先放 `notify.py` 或进一步下沉到 `infra`
4. 缓存访问避免散落，优先复用现有存储封装

### 改一个历史巨型函数

顺序：

1. 先识别它属于哪一层
2. 先搬运，再收口，不要一步到位重写
3. 先把 I/O、请求、渲染和业务判断拆开
4. 兼容层必须显式标注，不允许无限增长

## 提交前最小检查

- 插件仍能被 NoneBot 发现
- 改动路径经过手工回归
- 文档同步更新

最小命令：

```bash
nb plugin list --json
python test_tuilan_match_history.py
```

## 什么时候必须改文档

- 新增或删除命令
- 新增或删除 API
- 新增环境变量
- 改缓存路径、存储方式、启动方式
- 改模块边界

对应更新位置：

- `README.md`
- `project-architecture.md`
- `docs/references/runbook.md`
- `docs/exec-plans/active/refactor-plan.md`
- `docs/tasks/all-tasks.md`
- `AGENTS.md`

## 简化判断

如果你在写的代码要回答以下问题：

- “怎么和外部世界交互？” 放 `infra`
- “怎么组合业务规则？” 放 `services`
- “怎么接收 QQ / HTTP 输入？” 放 `plugins` 或 `api`
- “怎么展示图片或文本？” 放 `renderers`
- “怎么落盘或读库？” 放 `storage`

拿不准时，优先保持 `services` 纯净，再把 I/O 往下沉。
