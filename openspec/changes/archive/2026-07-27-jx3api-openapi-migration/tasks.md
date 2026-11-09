# JX3API OpenAPI 迁移执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

恢复因 JX3API 路径迁移而失败的 QQ 查询，并让已变化字段继续满足现有展示层契约。

## Progress

- [x] 完成方案确认
- [x] 完成代码设计
- [x] 完成开发实现
- [x] 完成自动化验证
- [x] 完成冒烟验证
- [x] 完成 review
- [ ] 完成验收记录

## Surprises & Discoveries

- 官方 OpenAPI 中没有旧主服映射和无参数百战总览的等价端点。

## Decision Log

- 2026-07-27：用户确认以当前 OpenAPI 为准；上游无替代端点的功能明确降级。
- 2026-07-27：响应字段兼容放入 `src/infra/jx3api_compat.py`，避免 handler 与模板感知上游协议。

## Outcomes & Retrospective

已迁移全部仓库内 JX3API `/data` 调用。真实上游响应离线回放已验证烟花、角色百战、科举、骗子、日常和开服状态的兼容字段；线上实测仍需在 bot 运行环境中完成 QQ 回归。

## Context and Orientation

`config.py` 保存主要 URL；`src/infra/jx3api_get.py` 是角色查询的 GET 边界；`src/utils/defget.py` 的 `fetch_json` 服务于新闻和科举；`src/plugins/status_monitor/jobs.py` 处理日常与开服监控。已有模板依赖历史字段名。

## Plan of Work

先用真实响应结构建立纯函数单测，再增加协议适配器并接入 HTTP 调用。之后迁移 URL 和两个降级入口，最后编译、运行单测和在线冒烟。

## Concrete Steps

1. 新增 `tests/test_jx3api_compat.py`，覆盖 URL 映射和六类字段转换。
2. 新增 `src/infra/jx3api_compat.py`，实现 URL 常量、响应适配和状态规范化。
3. 修改 `config.py`、新闻/科举/骗子/启动缓存/状态监控/百战 handler，删除旧 `/data` 请求。
4. 修改 `src/infra/jx3api_get.py` 与 `src/utils/defget.py`，在成功响应后调用适配器。
5. 修改 `src/services/jx3/server_resolver.py`，缓存 miss 时不再发起上游主服映射请求。
6. 更新 `docs/references/runbook.md` 的 JX3API 回归清单和本需求的测试、review、验收记录。

## Validation and Acceptance

运行 `python -m unittest tests.test_jx3api_compat` 和相关既有单测，执行 Python 3.9 兼容的 `py_compile`。在线使用同一角色验证烟花、奇遇、战绩、名片、角色百战、日常、开服、科举和骗子；资历仅验证路径成功或返回上游绑定提示。
