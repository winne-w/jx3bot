# JX3API OpenAPI 迁移验收记录

## Delivered Changes

- 迁移全部 JX3API `/data` 调用到当前 OpenAPI 路径。
- 新增 `src/infra/jx3api_compat.py`，适配烟花、角色百战、科举、骗子、日常和开服状态字段。
- 无参数百战和在线主服解析改为确认过的降级行为。
- 更新 JX3API 手工回归清单。

## Verification

- 自动化验证：`python -m unittest tests.test_jx3api_compat` 通过；真实响应兼容回放通过；`py_compile` 通过；`nb plugin list --json` 因环境未安装 `nb` 未执行。
- 手工冒烟：待在运行中的 bot 上执行 QQ 命令回归。
- review：实现者自审通过。

## Residual Risks

上游 OpenAPI 的字段没有版本锁定；资历仍依赖用户在剑网3魔盒绑定角色。

## Rollback

恢复本次 URL 和适配调用的代码改动；旧上游路径已失效，回滚不能恢复查询功能。

## Acceptance

待验收。
