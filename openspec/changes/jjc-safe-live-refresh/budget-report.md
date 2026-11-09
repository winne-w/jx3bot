> 2026-10-09 用户决定回退共享推栏预算桶：已恢复直连，移除预算配置、CAS 桶及官方请求范围限制；本文预算相关内容为历史方案，不代表当前运行行为。最新摘要任务、冷却和来源限频仍保留。

# 官方出口预算实施报告

## 交付文件

- `src/infra/tuilan_budget.py`：预算配置、指纹与许可结果值对象。
- `src/storage/mongo_repos/tuilan_request_budget_repo.py`：同步 PyMongo 单文档 CAS、分钟桶、30/70 分类份额、并发租约、全局/端点间隔、暂停与显式恢复。
- `src/infra/tuilan_client.py`：`request_scope()`、`protection_status()`、`resume_upstream()` 与受控重试；每次尝试重新签名并申请许可。
- `src/utils/tuilan_request.py`：保留原签名，兼容入口转发到受控适配器；移除临时进程内 5 秒门禁。
- `src/infra/http_client.py`：同步和异步错误响应保留数值或 HTTP 日期形式的 `Retry-After` 秒数。
- `config.py`：新增 `TUILAN_PROTECTION_ENABLED` 及预算配置；凭据改为环境变量，未保留旧硬编码值。
- `tests/test_tuilan_budget.py`、`tests/test_tuilan_official_client.py`：内存 collection 与本地 fake HTTP 覆盖。

## 对外接口与行为

- `tuilan_request(url, params=None)` 签名不变。
- `request_scope(traffic_class='interactive', max_attempts=4, retries=1)` 通过 `ContextVar` 传播；整个 scope 共享最多一次额外重试及四次总尝试，不按页面/端点重置。
- `protection_status()` 返回 `ready`、`disabled`、`invalid_config`、`upstream_paused` 或 `budget_unavailable`，不调用官方接口。
- 预算拒绝统一返回 `tuilan_budget_exhausted`、`tuilan_upstream_paused` 或 `tuilan_budget_unavailable` 与正数 `retry_after_seconds`。
- 401/403 和已识别的 Token/登录/鉴权业务错误在释放许可前写入无限期共享暂停，修复凭据后由管理员调用 `resume_upstream()` 恢复。429 在释放前按 `Retry-After` 写入定时暂停。
- 保护默认关闭；启用后，预算、Mongo URI、签名密钥、设备 ID 或 Ticket 缺失都会先拒绝联网。

## 验证记录

- TDD 红灯已观察：新预算类型/模块缺失、显式恢复接口缺失以及签名失败重复占额均先由测试失败暴露。
- `python -m unittest tests.test_tuilan_budget tests.test_tuilan_official_client`：通过。
- `python -m py_compile config.py src/infra/http_client.py src/infra/tuilan_budget.py src/infra/tuilan_client.py src/storage/mongo_repos/tuilan_request_budget_repo.py src/utils/tuilan_request.py`：通过。
- 隔离 Mongo `127.0.0.1:27947` 跨进程 CAS：8 个进程同时申请、并发上限 1 时仅 1 个获准，数据库仅保存 1 个租约和 1 次预算消耗；测试库随后删除。
- 全程未请求官方接口。

## 剩余风险与集成事项

- `src/infra/mongo.py` 的索引由主任务集成；本交付未修改该文件。
- PyMongo、写关注和 CAS 已在本地单节点 Mongo 验证；副本集故障转移下的 majority 语义仍需部署环境复测。
- HTTP 客户端设置 30 秒连接/套接字/CSOT 边界，但底层分阶段超时不等同于可强制中断的单一墙钟计时器；上游极端传输行为需线上观察。
- 端点最小间隔当前使用统一配置值、按 URL path 独立记账；若生产要求不同端点使用不同间隔，需要后续增加显式端点配置映射。
- 原硬编码推栏凭据已移除，部署升级前必须把实际值注入环境；报告不记录或回显旧值。
