# JX3API OpenAPI 迁移测试计划

## Test Scope

覆盖 URL 映射、烟花/百战/科举/骗子/日常/状态字段归一化、主服缓存 miss 不发起网络请求、无参数百战降级文案。

## Automated Checks

- `python -m unittest tests.test_jx3api_compat`
- `python -m py_compile config.py src/infra/jx3api_compat.py src/infra/jx3api_get.py src/services/jx3/server_resolver.py src/plugins/jx3bot_handlers/baizhan.py src/plugins/status_monitor/jobs.py`

## Manual Smoke Tests

- `烟花 唯我独尊 桃桃白糖`
- `奇遇 唯我独尊 桃桃白糖`
- `战绩 唯我独尊 桃桃白糖`
- `名片 唯我独尊 桃桃白糖`
- `百战 唯我独尊 桃桃白糖` 与 `百战`
- `日常`、`开服`、`答题 古琴`、`骗子 570790267`

## Data Regression

使用审计时保存的真实字段形状作为单测夹具；资历受上游角色绑定限制，验证其不再返回路径不存在即可。

## Observability

观察 `jx3api_get` 的请求 URL、状态监控错误日志及区服解析缓存 miss 日志，不记录 token 或 ticket。

## Result

- `python -m unittest tests.test_jx3api_compat`：5/5 通过。
- `py_compile`：所列配置、基础设施、service、handler 和状态监控文件通过。
- 使用审计保存的真实响应执行兼容回放：通过；未启动 bot 进行 QQ 线上回归。
- `nb plugin list --json`：当前环境未安装 `nb` 命令，未执行。
