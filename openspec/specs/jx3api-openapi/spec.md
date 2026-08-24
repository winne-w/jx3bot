# JX3API OpenAPI 兼容

## Purpose

定义仓库对当前 JX3API OpenAPI 的兼容行为，以及上游已移除能力的明确降级口径。

## Requirements

### Requirement: 使用当前 OpenAPI 路径

系统 MUST 通过当前 JX3API OpenAPI 路径访问仍受支持的能力，不得继续请求已下线的 `/data/...` 路径。

#### Scenario: 查询竞技场近期战绩
- **WHEN** 用户请求角色竞技场近期战绩
- **THEN** 基础设施适配层使用当前 OpenAPI 并向上层提供稳定字段

### Requirement: 无等价接口时明确降级

系统 MUST 对已无官方等价接口的能力返回可理解的降级结果，而不是调用已下线端点。

#### Scenario: 无参数百战查询
- **WHEN** 用户执行无参数百战命令
- **THEN** 系统说明该总览能力不可用且不发起不存在的上游请求
